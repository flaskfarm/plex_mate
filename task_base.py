import pathlib
import urllib.parse

from support import SupportFile, SupportOSCommand, SupportSubprocess

from .setup import *

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
                sections = {section['id'] for section in P.PlexDBHandle.library_sections() if section['section_type'] in [1, 2]}
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
                    row = P.PlexDBHandle.select_arg('SELECT * FROM metadata_items WHERE id = ?', (metadata_id,))[0]
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
                                art_tag_id = P.PlexDBHandle.select('SELECT id FROM tags WHERE tag_type = 313')[0]['id']
                            # taggings에서 metadata:// 프로토콜의 art url을 조회
                            thumbs = P.PlexDBHandle.select_arg("SELECT thumb_url FROM taggings WHERE tag_id = ? AND metadata_item_id = ?", (art_tag_id, metadata_id))
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
            P.PlexDBHandle.execute_query('BEGIN TRANSACTION;\n' + ';\n'.join(update_quries) + ';\n' + 'COMMIT;')
        logger.info(f'End retrieving category: {section_id=}')
