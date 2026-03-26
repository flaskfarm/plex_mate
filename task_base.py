import time
import pathlib
import urllib.parse

from support import SupportFile, SupportOSCommand, SupportSubprocess

from .setup import *
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle

logger = P.logger


class Task(object):
    
    @staticmethod
    @celery.task()
    def get_size(args):
        logger.warning(args)
        ret = SupportOSCommand.get_size(args[0])
        #logger.warning(ret)
        return ret

    @staticmethod
    @celery.task()
    def backup(args):
        try:
            logger.warning(args)
            db_path = args[0]
            if os.path.exists(db_path):
                dirname = os.path.dirname(db_path)
                basename = os.path.basename(db_path)
                tmp = os.path.splitext(basename)
                newfilename = f"{tmp[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{tmp[1]}"
                if P.ModelSetting.get_bool('base_backup_location_mode'):
                    newpath = os.path.join(dirname, newfilename)
                else:
                    newpath = os.path.join(P.ModelSetting.get('base_backup_location_manual'), newfilename)
                shutil.copy(db_path, newpath)
                ret = {'ret':'success', 'target':newpath}
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            ret = {'ret':'fail', 'log':str(e)}
        return ret
         
    @staticmethod
    @celery.task()
    def clear(args):
        if os.path.basename(os.path.normpath(args[0])) == 'PhotoTranscoder':
            for root, dirs, files in os.walk(args[0], topdown=False):
                try:
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
                except:
                    logger.error(traceback.format_exc())
        else:
            ret = SupportFile.rmtree(args[0])
            os.makedirs(args[0], exist_ok=True)
        # 범주
        if P.ModelSetting.get_bool('clear_cache_retrieve_category'):
            P.get_module('base').task_interface2('retrieve_category', -1)
        return Task.get_size(args)


    @staticmethod
    @celery.task()
    def agent_update(args):
        ret = {'recent_version':None, 'local_version':None, 'need_update':False}
        # 버전
        regex = re.compile("VERSION\s=\s'(?P<version>.*?)'")
        text = requests.get('https://raw.githubusercontent.com/soju6jan/SjvaAgent.bundle/main/Contents/Code/version.py').text
        match = regex.search(text)
        if match:
            ret['recent_version'] = match.group('version')
        if ret['recent_version'] == None:
            return "접속실패"
        all_agent_path = os.path.join(P.ModelSetting.get('base_path_data'), 'Plug-ins')
        sjva_agent_path = os.path.join(all_agent_path, 'SjvaAgent.bundle')
        version_path = os.path.join(sjva_agent_path, 'Contents', 'Code', 'version.py')
        if os.path.exists(version_path):
            text = SupportFile.read_file(version_path)
            match = regex.search(text)
            if match:
                ret['local_version'] = match.group('version')
                if ret['local_version'] != ret['recent_version']:
                    ret['need_update'] = True
        else:
            ret['need_update'] = True

        #ret['need_update'] = True
        ret['flag_clone'] = False
        if ret['need_update'] == False:
            ret['log'] = "최신 버전"
            return ret

        git_path = os.path.join(sjva_agent_path, '.git')
        if os.path.exists(sjva_agent_path):
            if os.path.exists(git_path):
                command = ['git', '-C', sjva_agent_path, 'reset', '--hard', 'HEAD']
                result = SupportSubprocess.execute_command_return(command)
                F.logger.debug(d(result))
                command = ['git', '-C', sjva_agent_path, 'pull']
                result = SupportSubprocess.execute_command_return(command)
                F.logger.debug(d(result))
                ret['git_update'] = True
            else:
                result = SupportFile.rmtree(sjva_agent_path)
                P.logger.error(result)
                if result == False:
                    ret['log'] = "플러그인 폴더 삭제 필요"
                    return ret
                else:
                    ret['flag_clone'] = True
        else:
            ret['flag_clone'] = True
                
        if ret['flag_clone']:
            command = ['git', '-C', all_agent_path, 'clone', 'https://github.com/soju6jan/SjvaAgent.bundle' + '.git', '--depth', '1']
            log = SupportSubprocess.execute_command_return(command, log=True)
            F.logger.debug(log)

        for folder in ['dummy_agent', 'standalone_agent']:
            dummy = os.path.join(sjva_agent_path, folder)
            for name in os.listdir(dummy):
                source_path = os.path.join(dummy, name)
                if os.path.isdir(source_path) == False:
                    continue
                target_path = os.path.join(all_agent_path, name)
                SupportFile.rmtree(target_path)
                shutil.move(source_path, all_agent_path)


        for base, dirs, files in os.walk(os.path.join(sjva_agent_path, 'Scanners')):
            for name in files:
                source_path = os.path.join(base, name)
                #P.logger.error(base)
                target_folder = base.replace(os.sep+'Plug-ins'+os.sep+'SjvaAgent.bundle', '')
                #P.logger.error(target_folder)
                if os.path.exists(os.path.join(target_folder, name)):
                    os.remove(os.path.join(target_folder, name))
                os.makedirs(target_folder, exist_ok=True)
                shutil.move(source_path, target_folder)
        ret['log'] = '정상 완료'
        return ret

    @classmethod
    @celery.task(bind=False)
    def retrieve_category(section_id: int = -1) -> None:
        '''
        2025-07-02 halfaider

        증상:
            user_art_url이 웹 url인 경우 범주 페이지에서 캐시 이미지를 생성할 때 플렉스 서버가 다운 됨
            10개의 범주가 웹 url을 사용할 경우 10번 다운 되고 나서야 정상화 됨
            metadata:// 형식의 주소는 대상 파일이 존재하지 않더라도 서버가 다운되는 현상이 없음
        대안:
            범주 페이지 접속시 웹 url의 캐시 이미지를 생성하는 과정이 발생하지 않도록
            ../Cache/PhotoTranscoder 폴더를 비운 직후 미리 범주의 배경 이미지 캐시를 요청
        예외:
            웹 url이 유효하지 않아서 캐시 이미지를 미리 생성하지 못하는 경우가 있음
        조치:
            가능하면 user_art_url을 metadata:// 형식으로 복구
        '''
        logger.info(f'Start retrieving category: {section_id=}')
        token = P.ModelSetting.get('base_token')
        base_url = P.ModelSetting.get('base_url')
        params = {
            'includeCollections': 1,
            'includeExternalMedia': 1,
            'includeAdvanced': 1,
            'includeMeta': 1,
            'X-Plex-Features': 'external-media%2Cindirect-media%2Chub-style-list',
            'X-Plex-Model': 'bundled',
            'X-Plex-Container-Start': 0,
            'X-Plex-Container-Size': 500,
            'X-Plex-Text-Format': 'plain',
            'X-Plex-Language': 'ko',
            'X-Plex-Token': token,
        }
        headers = {
            'Accept': 'application/json',
            'X-Plex-Token': token
        }
        art_tag_id = None
        update_quries = []
        try:
            if section_id > 0:
                sections = {section_id}
            else:
                sections = {section['id'] for section in PlexDBHandle.library_sections() if section['section_type'] in [1, 2]}
        except Exception:
            logger.exception('라이브러리 섹션을 가져올 수 없어서 작업을 중단합니다.')
            return
        for section in sections:
            url_category = urllib.parse.urljoin(base_url, f'/library/sections/{section}/categories')
            try:
                response = requests.get(url_category, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                directory = data['MediaContainer']['Directory']
            except Exception:
                logger.exception(f'범주 데이터를 가져올 수 없습니다: {section=}')
                continue
            for category in directory:
                # 범주의 대표 메타데이터를 조회
                try:
                    query = dict(urllib.parse.parse_qsl(category['thumb']))
                    paths = (query.get('url') or '').split('/')
                    if 'metadata' not in paths:
                        continue
                    metadata_id = paths[paths.index('metadata') + 1]
                    row = PlexDBHandle.select_arg('SELECT * FROM metadata_items WHERE id = ?', (metadata_id,))[0]
                except Exception:
                    logger.exception(f'범주의 대표 메타데이터를 가져올 수 없습니다: {section=} {category=}')
                    continue
                # 대표 메타데이터의 user_art_url scheme이 http가 아니면 처리하지 않음 (metatata://는 재생성시 오류나지 않음)
                if not (user_art_url := (row.get('user_art_url') or '')).startswith('http'):
                    continue
                # http면 범주 이미지를 요청해서 재생성 유도
                url_photo = urllib.parse.urljoin(base_url, category['thumb'])
                try:
                    response = requests.get(url_photo, headers=headers)
                    response.raise_for_status()
                except Exception:
                    # 범주 이미지 요청이 비정상적으로 응답할 경우 추가 조치
                    logger.exception(f'범주 이미지 요청 실패: {category["key"]} {metadata_id=} {user_art_url=}')
                    try:
                        # 플렉스 기본 에이전트는 taggings에서 검색
                        if row['guid'].startswith('plex://'):
                            if art_tag_id is None:
                                art_tag_id = PlexDBHandle.select('SELECT id FROM tags WHERE tag_type = 313')[0]['id']
                            # taggings에서 metadata:// 프로토콜의 art url을 조회
                            thumbs = PlexDBHandle.select_arg("SELECT thumb_url FROM taggings WHERE tag_id = ? AND metadata_item_id = ?", (art_tag_id, metadata_id))
                            # 번들 폴더에 art 파일이 없으면 메타데이터 새로고침해서 파일을 생성해야 범주 이미지가 생성됨. 새로고침은 사용자 판단에 따라...
                            new_user_art_url = thumbs[0]['thumb_url'] if thumbs else ''
                        # 기본 에이전트가 아닌 경우 번들 폴더에서 검색
                        else:
                            match row['metadata_type']:
                                case 1:
                                    content_type = 'Movies'
                                case 2:
                                    content_type = 'TV Shows'
                                case _:
                                    continue
                            bundle_path = pathlib.Path(P.ModelSetting.get('base_path_metadata'), content_type, row['hash'][0], f"{row['hash'][1:]}.bundle")
                            art_path = bundle_path / 'Contents' / '_combined' / 'art'
                            art_file = next(art_path.glob('*'), None)
                            new_user_art_url = f'metadata://art/{art_file.name}' if art_file else ''
                        if not new_user_art_url:
                            logger.warning(f'user_art_url 복구 경로 조회 실패: {category["key"]} {metadata_id=} {user_art_url=}')
                        logger.debug(f'user_art_url 변경: {category["key"]} {metadata_id=} {user_art_url} -> {new_user_art_url}')
                        update_quries.append(f"UPDATE metadata_items SET user_art_url = '{new_user_art_url}' WHERE id = {metadata_id}")
                    except Exception:
                        logger.exception(f'{category["key"]} {metadata_id=}')
        if update_quries:
            PlexDBHandle.execute_query('BEGIN TRANSACTION;\n' + ';\n'.join(update_quries) + ';\n' + 'COMMIT;')
        logger.info(f'End retrieving category: {section_id=}')


def _plex_exclusive_should_stop(task_id: str, start_time: float) -> bool:
    stop_id = f"tool:simple:plex_exclusive:stop"
    if P.cache.get(task_id) == 'false':
        return True
    if (stop_time := P.cache.get(stop_id)) and float(stop_time) > start_time:
        return True
    return False


def stop_plex_exclusive() -> None:
    stop_id = f"tool:simple:plex_exclusive:stop"
    P.cache.set(stop_id, str(time.time()))
    logger.info("모든 plex_exclusive() 작업을 중단합니다.")


@celery.task
def plex_exclusive(section_id: int = 0, metadata_id: int = 0, reset: bool = False, manual: bool = False, allowed_sections: tuple = ()) -> None:
    if not section_id and not metadata_id:
        logger.error('라이브러리 혹은 메타데이터 ID를 입력해 주세요.')
        return
    task_id = f"tool:simple:plex_exclusive:{section_id}:{metadata_id}"
    if P.cache.get(task_id) == 'true':
        logger.warning(f"이전 작업 실행중: {task_id}")
        return
    P.cache.set(task_id, 'true')
    start_time = time.time()
    try:
        logger.info(f"시작: {task_id}")
        select_query = """SELECT id, guid, metadata_type, title, year, library_section_id, slug, user_clear_logo_url
            FROM metadata_items
            WHERE metadata_type IN (1, 2)"""
        oprt = "!=" if reset else "="
        select_query += f" AND (COALESCE(user_clear_logo_url, '') {oprt} '' OR COALESCE(slug, '') {oprt} '')"
        if metadata_id:
            select_query += f" AND id = ?"
            select_id = metadata_id
        elif section_id:
            select_query += f" AND library_section_id = ?"
            select_id = section_id
        else:
            return
        # 자동일 경우 대상 섹션을 검증
        if not manual and not metadata_id and section_id not in allowed_sections:
            logger.info(f"대상 섹션이 아닙니다: {section_id}")
            return
        rows = PlexDBHandle.select_arg(select_query, (select_id,))
        updates = []
        for row in rows:
            # 작업 중단 체크
            if _plex_exclusive_should_stop(task_id, start_time):
                break
            meta_section_id = row.get('library_section_id')
            # section_id를 지정하지 않으면 조회후 알 수 있으므로
            if not manual and meta_section_id not in allowed_sections:
                logger.info(f"대상 섹션이 아닙니다: {meta_section_id}")
                continue
            meta_id = row.get('id')
            if reset:
                if slug := row.get('slug'):
                    updates.append(('slug', '', meta_id))
                if clear_logo := row.get('user_clear_logo_url'):
                    updates.append(('user_clear_logo_url', '', meta_id))
                continue
            meta_type = row.get('metadata_type')
            meta_agent = 'tv.plex.agents.movie' if meta_type == 1 else 'tv.plex.agents.series'
            meta_title = row.get('title')
            meta_year = row.get('year')
            meta_slug = row.get('slug')
            meta_clear_logo = row.get('user_clear_logo_url')
            try:
                meta_guid_path = (row.get('guid') or '').split("?")[0].split("://")[-1]
                meta_guid_parts = meta_guid_path.split("/")
                meta_code, _, _ = (meta_guid_parts + [None, None])[:3]
                #P.logger.info(f"{meta_id=} {meta_code=} {meta_title=} {meta_year=} {meta_agent=}")
                # 기본 에이전트로 검색
                search_title = f"tmdb-{meta_code[2:]}" if meta_code.startswith(("FT", "MT")) else meta_title
                matches = PlexWebHandle.get_matches(meta_id, search_title, meta_year, agent=meta_agent)
                if not matches:
                    continue
                sr = matches[0]
                sr_type = sr.get('type')
                if (meta_type == 1 and sr_type != 'movie') or (meta_type == 2 and sr_type != 'show'):
                    continue
                plex_guid = sr.get('guid')
                plex_metadata = PlexWebHandle.get_metadata(plex_guid)
                if not plex_metadata:
                    continue
                slug = plex_metadata.get('slug')
                if slug and slug != meta_slug:
                    P.logger.debug(f"{meta_title} ({meta_year}): {slug=} {plex_metadata.get('title')} ({plex_metadata.get('year')})")
                    updates.append(('slug', slug, meta_id))
                clear_logo = None
                if tmdb_guids := [g.get('id') for g in plex_metadata.get('Guid') or () if (g.get('id') or '').startswith("tmdb")]:
                    try:
                        tmdb_id = int(tmdb_guids[0].split("://")[-1])
                        from support_site.site_tmdb import tmdbsimple, SiteTmdb
                        tmdb_class = tmdbsimple.Movies if meta_type == 1 else tmdbsimple.TV
                        images = []
                        SiteTmdb._process_image(tmdb_class(tmdb_id), images)
                        for art in sorted(images, key=lambda k: k.get('score') or 0, reverse=True):
                            if art.get('aspect') == 'logo':
                                clear_logo = art.get('value') or art.get('thumb')
                                break
                    except Exception as e:
                        logger.error(f"TMDB 로고를 가져오지 못 했습니다: {str(e)}")
                if not clear_logo:
                    # 플렉스 로고는 영문일 확률이 높음
                    images = plex_metadata.get('Image') or ()
                    for image in images:
                        if image.get('type') == 'clearLogo':
                            clear_logo = image.get('url')
                if clear_logo and clear_logo != meta_clear_logo:
                    P.logger.debug(f"{meta_title} ({meta_year}): {clear_logo=}")
                    updates.append(('user_clear_logo_url', clear_logo, meta_id))
            except Exception as e:
                P.logger.error(f"{meta_id=} error='{str(e)}'")
        
        if updates:
            try:
                # DB lock 30초 대기
                sql_lines = ["PRAGMA busy_timeout = 30000;", "BEGIN TRANSACTION;"]
                for column, value, metadata_id in updates:
                    # 작업 중단 체크
                    if _plex_exclusive_should_stop(task_id, start_time):
                        break
                    if value is None:
                        value = ''
                    else:
                        value = str(value).replace("'", "''")
                    sql_lines.append(f"UPDATE metadata_items SET {column} = '{value}' WHERE id = {metadata_id};")
                sql_lines.append("COMMIT;")
                # 작업 중단 체크
                if _plex_exclusive_should_stop(task_id, start_time):
                    logger.info(f"작업 중단으로 DB 업데이트 취소: {task_id}")
                    return
                logger.info(f"DB 업데이트 쿼리 실행: {task_id}")
                PlexDBHandle.execute_query("\n".join(sql_lines))
            except Exception:
                logger.exception(f"DB 업데이트 오류: {task_id}")
    except Exception:
        logger.exception(f"오류: {task_id}")
    finally:
        P.cache.set(task_id, 'false')
        logger.info(f"종료: {task_id}")
