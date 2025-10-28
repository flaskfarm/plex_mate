import sqlite3
import pathlib
from xml.etree import ElementTree

from support import SupportFile

from .plex_db import PlexDBHandle, dict_factory
from .plex_web import PlexWebHandle
from .setup import *

TAG = {
    'poster' : ['thumb', 'posters'],
    'art' : ['art', 'art'],
    'banner' : ['banner', 'banners'],
    'theme' : ['music', 'themes'],
    'logo' : ['clear_logo', 'clearLogos'],
}

logger = P.logger


class Task(object):

    @staticmethod
    @F.celery.task(bind=True)
    def start(self, command: str, section_id: str, dryrun: str, remove_orphans: str) -> str:
        if command == 'start4':
            logger.warning(f'4단계는 현재 지원하지 않습니다.')
            return 'stop'
        config = P.load_config()
        try:
            dryrun = True if dryrun.lower() == 'true'  else False
        except Exception:
            dryrun = False

        try:
            remove_orphans = True if remove_orphans.lower() == 'true'  else False
        except Exception:
            remove_orphans = False


        db_file = P.ModelSetting.get('base_path_db')
        with sqlite3.connect(db_file) as con:
            cur = con.cursor()
            #ce = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 1 AND library_section_id = ? ORDER BY title', (section_id,))
            #ce = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 1 AND library_section_id = ? AND user_thumb_url NOT LIKE "upload%" AND (user_thumb_url NOT LIKE "http%" OR refreshed_at is NULL) ORDER BY title', (section_id,))
            query = config.get('파일정리 TV 쿼리', 'SELECT * FROM metadata_items WHERE metadata_type = 2 AND library_section_id = ? ORDER BY title')
            #query = "SELECT * FROM metadata_items WHERE metadata_type = 2 AND library_section_id = ? and title like '기분%' ORDER BY title"
            ce = con.execute(query, (section_id,))
            ce.row_factory = dict_factory
            query_count = query.replace("SELECT *", "SELECT COUNT(*)")
            row_count = con.execute(query_count, (section_id,)).fetchone()
            status = {'is_working':'run', 'total_size':0, 'remove_size':0, 'count':row_count[0], 'current':0}

            for show in ce:
                try:
                    if P.ModelSetting.get_bool('clear_show_task_stop_flag'):
                        return 'stop'
                    time.sleep(0.05)
                    status['current'] += 1
                    data = {'mode':'show', 'status':status, 'command':command, 'section_id':section_id, 'dryrun':dryrun, 'process':{}, 'file_count':0, 'remove_count':0, 'remove_orphans': remove_orphans}
                    data['db'] = show

                    Task.show_process(data, con, cur)

                    data['status']['total_size'] += data['meta']['total']
                    data['status']['remove_size'] += data['meta']['remove']
                    if 'media' in data:
                        data['status']['total_size'] += data['media']['total']
                        data['status']['remove_size'] += data['media']['remove']
                    #P.logic.get_module('clear').receive_from_task(data, celery=False)
                    #continue
                    """
                    if 'use_filepath' in data:
                        del data['use_filepath']
                    if 'remove_filepath' in data:
                        del data['remove_filepath']
                    if 'seasons' in data:
                        del data['seasons']
                    """
                    if F.config['use_celery']:
                        self.update_state(state='PROGRESS', meta=data)
                    else:
                        self.receive_from_task(data, celery=False)
                except Exception as e:
                    P.logger.error(f'Exception:{str(e)}')
                    P.logger.error(traceback.format_exc())
                    P.logger.error(show['title'])
            P.logger.warning(f"종료: {command=} {section_id=} {dryrun=} {remove_orphans=}")
            return 'wait'




    @staticmethod
    def show_process(data, con, cur):
      try:   
        data['meta'] = {'remove':0}
        data['meta']['metapath'] = os.path.join(P.ModelSetting.get('base_path_metadata'), 'TV Shows', data['db']['hash'][0], f"{data['db']['hash'][1:]}.bundle")

        data['meta']['total'] = SupportFile.size(start_path=data['meta']['metapath'])
        if data['command'] == 'start0':
            return
        combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'Info.xml')
        
        data['use_filepath'] = []
        data['remove_filepath'] = []
        data['seasons'] = {}
        data['media'] = {'total':0, 'remove':0}

        Task.xml_analysis(combined_xmlpath, data, data, con)

        season_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 3 and parent_id = ? ORDER BY "index"', (data['db']['id'],))
        season_cs.row_factory = dict_factory
        for season in season_cs.fetchall():
            episode_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 4 and parent_id = ? ORDER BY "index"', (season['id'],))
            episode_cs.row_factory = dict_factory

            for episode in episode_cs.fetchall():
                try:
                    season_index = season['index']
                    episode_index = episode['index']
                    if episode['index'] == -1:
                        tmp = episode['guid']
                        match = re.compile(r'\/(?P<season>\d{4})\/(?P<epi>\d{4}-\d{2}-\d{2})').search(episode['guid'])
                        if match:
                            episode_index = match.group('epi')
                    if season_index not in data['seasons']:
                        data['seasons'][season_index] = {'db':season}
                        combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'seasons', f"{season_index}.xml")
                        ret = Task.xml_analysis(combined_xmlpath, data['seasons'][season_index], data, con)
                        data['seasons'][season_index]['episodes'] = {}
                    data['seasons'][season_index]['episodes'][episode_index] = {'db':episode}
                    combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'seasons', f"{season_index}", "episodes", f"{episode_index}.xml")
                    ret = Task.xml_analysis(combined_xmlpath, data['seasons'][season_index]['episodes'][episode_index], data, con, is_episode=True)
                except Exception as e:
                    P.logger.error(f'Exception:{str(e)}')
                    P.logger.error(traceback.format_exc())
        query = ""
        if data['command'] in ['start22', 'start3', 'start4']:
            # 쇼 http로 
            sql = 'UPDATE metadata_items SET '
            for tag in TAG:
                tag_data = data['process'].get(tag, {})
                if web_url := tag_data.get('url'):
                    gdrive_url = Task.process_step4(data, web_url)
                    sql += f" user_{TAG[tag][0]}_url = '{gdrive_url}', "
                    try: data['use_filepath'].remove(tag_data.get('localpath', ''))
                    except: pass
                    try: data['use_filepath'].remove(tag_data.get('realpath', ''))
                    except: pass
                
            if sql != 'UPDATE metadata_items SET ':
                sql = sql.strip().rstrip(',')
                sql += '  WHERE id = {} ;\n'.format(data['db']['id'])
                query += sql

            for season_index, season in data['seasons'].items():
                if 'process' not in season:
                    continue
                sql = 'UPDATE metadata_items SET '
                for tag in TAG:
                    tag_data = season['process'].get(tag, {})
                    if web_url := tag_data.get('url'):
                        gdrive_url = Task.process_step4(data, web_url)
                        sql += f" user_{TAG[tag][0]}_url = '{gdrive_url}', "
                        try: data['use_filepath'].remove(tag_data.get('localpath', ''))
                        except: pass
                        try: data['use_filepath'].remove(tag_data.get('realpath', ''))
                        except: pass

                if sql != 'UPDATE metadata_items SET ':
                    sql = sql.strip().rstrip(',')
                    sql += '  WHERE id = {} ;\n'.format(season['db']['id'])
                    query += sql

        
        if data['command'] in ['start21', 'start22', 'start3', 'start4']:
            
            for season_index, season in data['seasons'].items():
                for episode_index, episode in (season.get('episodes') or {}).items():
                    #P.logger.warning(episode['process']['thumb'])
                    media_item_cs = con.execute('SELECT * FROM media_items WHERE metadata_item_id = ? ORDER BY id', (episode['db']['id'],))
                    media_item_cs.row_factory = dict_factory
                    episode['media_list'] = []

                    for media_item in media_item_cs.fetchall():
                        media_part_cs = con.execute('SELECT * FROM media_parts WHERE media_item_id = ? ORDER BY id', (media_item['id'],))
                        media_part_cs.row_factory = dict_factory
                        for media_part in media_part_cs.fetchall():
                            media_hash = media_part['hash']
                            #P.logger.warning(f"  파일 : {media_part['file']} {media_hash}")
                            if media_hash == '':
                                continue

                            mediapath = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost', media_hash[0], f"{media_hash[1:]}.bundle", 'Contents', 'Thumbnails', 'thumb1.jpg')
                            if os.path.exists(mediapath):
                                #P.logger.warning("미디오 썸네일 있음")
                                episode['media_list'].append(mediapath)
                                data['media']['total'] = os.path.getsize(mediapath)
                                #data['remove_size'] += os.stat(mediapath).st_size
                                #os.remove(mediapath)
                                #media://0/10c056239442666d0931c90996ff69673861d95.bundle/Contents/Thumbnails/thumb1.jpg
                    # 2021-11-01
                    # 4단계 미디어파일을 디코에 올리고 그 url로 대체한다.
                    # 
                    #P.logger.info(episode['process']['thumb']['db_type'] )
                    if data['command'] == 'start4' and episode['process']['thumb']['db_type'] == 'media':
                        localpath = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost', episode['process']['thumb']['db'].replace('media://', ''))
                        if localpath[0] != '/':
                            localpath = localpath.replace('/', '\\')
                        if os.path.exists(localpath):
                            if data['dryrun'] == False:
                                try:
                                    from gds_tool import SSGDrive
                                    discord_url = SSGDrive.upload_from_path(localpath)
                                    if discord_url is not None:
                                        episode['process']['thumb']['url'] = discord_url
                                        P.logger.warning(discord_url)
                                except Exception as e:
                                    P.logger.error(f'Exception:{str(e)}')
                                    #P.logger.error(traceback.format_exc())
                        else:
                            #P.logger.warning(episode)
                            P.logger.warning(f"썸네일 없음 1 분석 실행: {episode['db']['id']}")
                            PlexWebHandle.analyze_by_id(episode['db']['id'])
                            continue
                    if data['command'] == 'start4' and episode['process']['thumb']['db'] == '':
                        P.logger.warning(f"썸네일 없음 분석 2: {episode['db']['id']}")
                        PlexWebHandle.analyze_by_id(episode['db']['id'])
                        continue



                    if episode['process']['thumb']['url'] != '':
                        query += f'UPDATE metadata_items SET user_thumb_url = "{episode["process"]["thumb"]["url"]}" WHERE id = {episode["db"]["id"]};\n'
                        try: data['use_filepath'].remove(episode['process']['thumb']['localpath'])
                        except: pass
                        try: data['use_filepath'].remove(episode['process']['thumb']['realpath'])
                        except: pass
                        if data['command'] in ['start3', 'start4']:
                            for mediafilepath in episode['media_list']:
                                if os.path.exists(mediapath):
                                    data['media']['remove'] += os.path.getsize(mediapath)
                                    if data['dryrun'] == False:
                                        os.remove(mediapath)
                    elif episode['process']['thumb']['db'] == '':
                        if len(episode['media_list']) > 0:
                            tmp = f"media://{episode['media_list'][0].split('localhost/')[1]}"
                            query += f'UPDATE metadata_items SET user_thumb_url = "{tmp}" WHERE id = {episode["db"]["id"]};\n'

                    
                    if data['dryrun'] == False and data['command'] in ['start3', 'start4']:
                        for mediafilepath in episode['media_list']:
                            content_folder = os.path.dirname(os.path.dirname(mediafilepath))
                            for base, folders, files in os.walk(content_folder):
                                if not folders and not files:
                                    os.removedirs(base)


        #P.logger.error(data['command'])
        #P.logger.error(query)
        if query != '' and data['dryrun'] == False:
            PlexDBHandle.execute_query(query)


        # 2022-11-22 
        # 에피소드 user_thumb_url 이 metadata나 media이면 디코로 전환
        not_http_count = 0
        if data['command'] in ['start4']:
            season_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 3 and parent_id = ? ORDER BY "index"', (data['db']['id'],))
            season_cs.row_factory = dict_factory
            for season in season_cs.fetchall():
                episode_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 4 and parent_id = ? ORDER BY "index"', (season['id'],))
                episode_cs.row_factory = dict_factory

                for episode in episode_cs.fetchall():
                    if episode['user_thumb_url'].startswith('https://thumb.kakaocdn.net/dna/kamp/source'):
                    #if episode['user_thumb_url'].startswith('http'):
                        if data['dryrun'] == False:
                            try:
                                from gds_tool import SSGDrive
                                imgur_url = SSGDrive.upload_from_url(episode['user_thumb_url'])
                                if imgur_url is not None:
                                    P.logger.warning(imgur_url)
                                    sql = 'UPDATE metadata_items SET '
                                    sql += ' user_thumb_url = "{}" '.format(imgur_url)
                                    sql += '  WHERE id = {} ;\n'.format(episode['id'])
                                    ret = PlexDBHandle.execute_query(sql)
                                    if ret.find('database is locked') == -1:
                                        pass
                            except Exception as e:
                                    P.logger.error(f'Exception:{str(e)}')
                                    P.logger.error(traceback.format_exc())

                    elif episode['user_thumb_url'].startswith('http'):
                    #if episode['user_thumb_url'].find('drive.google.com') != -1:
                        continue

                    not_http_count += 1

                    if episode['user_thumb_url'] == None or episode['user_thumb_url'] == '':
                        PlexWebHandle.analyze_by_id(episode['id'])
                        continue
                    localpath = None
                    if episode['user_thumb_url'].startswith('media://'):
                        localpath = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost', episode['user_thumb_url'].replace('media://', ''))

                    elif episode['user_thumb_url'].startswith('metadata://'):
                        tmp = combined_xmlpath.split('/_combined/')
                        tmp2 = episode['user_thumb_url'].split('metadata://')
                        localpath = f"{tmp[0]}/_combined/{tmp2[1]}"
                    if localpath == None:
                        continue
                    if localpath[0] != '/':
                        localpath = localpath.replace('/', '\\')
                    
                    if os.path.exists(localpath):
                        if data['dryrun'] == False:
                            try:
                                from gds_tool import SSGDrive
                                discord_url = SSGDrive.upload_from_path(localpath)
                                if discord_url is not None:
                                    P.logger.warning(discord_url)
                                    sql = 'UPDATE metadata_items SET '
                                    sql += ' user_thumb_url = "{}" '.format(discord_url)
                                    sql += '  WHERE id = {} ;\n'.format(episode['id'])
                                    ret = PlexDBHandle.execute_query(sql)
                                    if ret.find('database is locked') == -1:
                                        data['meta']['remove'] += os.path.getsize(localpath)
                                        os.remove(localpath)
                            except Exception as e:
                                    P.logger.error(f'Exception:{str(e)}')
                    else:
                        P.logger.warning(f"파일 없음. 메타 새로고침 필요. {data['db']['title']}")

        #P.logger.error(data['meta']['remove'] )
        #P.logger.error(data['use_filepath'] )

        for base, folders, files in os.walk(data['meta']['metapath']):
            for f in files:
                if P.ModelSetting.get_bool('clear_show_task_stop_flag'):
                    return
                if f.endswith('.xml'):
                    continue
                data['file_count'] += 1
                filepath = os.path.join(base, f)
                
                if os.path.islink(filepath):
                    if os.path.exists(os.path.realpath(filepath)) == False:
                        P.logger.info(f"링크제거 : {filepath}")
                        os.remove(filepath)
                        #file_size = os.path.getsize(filepath)
                        #data['meta']['remove'] += file_size
                        continue

                '''
                2025.04.07 halfaider
                기존 로직은 1~3 단계 실행시 일괄 삭제.
                1, 2-1 단계는 url로 변경하지 않아 사용하는 파일이 삭제됨.
                그렇다고 각 파일을 DB 조회로 판단할 경우 오래 걸림.
                => 1, 2-1 단계에서는 삭제를 건너뛰고 2-2 이상부터 일괄 삭제, 4 단계는 기존 조건 유지.
                '''
                #if data['command'] in ['start4'] and not_http_count == 0:
                if data['command'] in ['start2-2', 'start3'] or data['command'] == 'start4' and not_http_count < 1:
                    # metadata의 리소스 url이 모두 http
                    if data['dryrun'] == False:
                        P.logger.info(f"일괄 삭제: {filepath}")
                        file_size = os.path.getsize(filepath)
                        data['meta']['remove'] += file_size
                        os.remove(filepath)
                elif data['command'] == 'start4' and not_http_count > 0:
                    tmp = f.split('.')[-1]
                    using = PlexDBHandle.select(f"SELECT id, guid, user_thumb_url FROM metadata_items WHERE user_thumb_url LIKE '%{tmp}' OR user_art_url LIKE '%{tmp}';")
                    if len(using) == 0:
                    #if filepath not in data['use_filepath']:
                        if os.path.exists(filepath):
                            data['remove_count'] += 1
                            if filepath not in data['remove_filepath']:
                                data['remove_filepath'].append(filepath)
                            file_size = os.path.getsize(filepath)
                            data['meta']['remove'] += file_size
                            if data['dryrun'] == False:
                                P.logger.debug(f"안쓰는 파일 삭제 : {filepath}")
                                file_size = os.path.getsize(filepath)
                                os.remove(filepath)
                        else:
                            P.logger.error('.................. 파일 없음')
                    else:
                        P.logger.debug(f"파일 사용: {filepath}")

        while True:
            count = 0
            for base, folders, files in os.walk(data['meta']['metapath']):
                if not folders and not files:
                    os.removedirs(base)
                    P.logger.debug(f"빈 폴더 삭제: {base} ")
                    count += 1
            if count == 0:
                break


        

        if data['command'] == 'start1':
            return                  

      except Exception as e:
        P.logger.error(f'Exception:{str(e)}')
        P.logger.error(traceback.format_exc())
                
    

    @staticmethod
    def xml_analysis(combined_xmlpath, data, show_data, con, is_episode=False):
        #P.logger.warning(combined_xmlpath)

        #text = ToolBaseFile.read(combined_xmlpath)
        #P.logger.warning(text)
        # 2021-12-11 4단계로 media파일을 디코 이미로 대체할때 시즌0 같이 아예 0.xml 파일이 없을 때도 동작하도록 추가
        contents_path = pathlib.Path(combined_xmlpath.split('/_combined/')[0])
        if os.path.exists(combined_xmlpath) == False:
            #P.logger.info(f"xml 파일 없음 : {combined_xmlpath}")
            #P.logger.error(data['process']['thumb'])
            #P.logger.debug(data)
            #P.logger.debug(is_episode)
            '''
            2025.04.05 halfaider
            새로운 Plex 기본 에이전트는 Info.xml을 사용하지 않고 DB에 포스터 url을 저장함
            '''
            data.setdefault('process', {})

            for key in (tags := {'thumb' : ['thumb', 'thumbs']} if is_episode else TAG):
                data['process'].setdefault(key, {
                        'db': '',
                        'db_type': '',
                        'url': '',
                        'filename': '',
                    })
                tagging_cursor = con.execute(
                    f"""SELECT id, text, thumb_url
                    FROM taggings
                    WHERE thumb_url = ? AND metadata_item_id = ?""",
                    (data['db'][f'user_{tags[key][0]}_url'], data['db']['id'])
                )
                tagging_cursor.row_factory = dict_factory
                tagging_row = tagging_cursor.fetchone()
                if tagging_row and (web_url := tagging_row.get('text', '')).startswith('http'):
                    # metadata://posters/tv.plex.agents.series_ad850f879b2796738bfb6bf9c41333fdfd092900
                    column_url = data['db'][f'user_{tags[key][0]}_url'] or ''
                    db_type = column_url.split('://')[0]
                    # media://8/0ee1dffac9aff7c4f02c95dd675f82167725235.bundle/Contents/Thumbnails/thumb1.jpg
                    if not db_type.startswith('metadata'):
                        continue
                    data['process'][key]['db'] = column_url
                    data['process'][key]['db_type'] = db_type
                    data['process'][key]['filename'] = column_url.split('/')[-1]
                    data['process'][key]['url'] = web_url
                    local_path: pathlib.Path = contents_path / '_combined' / tags[key][1] / data['process'][key]['filename']
                    if local_path.exists():
                        data['process'][key]['localpath'] = str(local_path)
                        if str(local_path) not in show_data['use_filepath']:
                            show_data['use_filepath'].append(str(local_path))
            return True
        if combined_xmlpath not in show_data['use_filepath']:
            show_data['use_filepath'].append(combined_xmlpath)

        tree = ElementTree.parse(combined_xmlpath)
        root = tree.getroot()
        data['xml_info'] = {}
        if is_episode == False:
            tags = TAG
        else:
            tags = {'thumb' : ['thumb', 'thumbs']}
        path_xml = pathlib.Path(combined_xmlpath)

        update_xml = False
        orphans = {}
        for tag, value in tags.items():
            tmp = root.find(value[1])
            if root.find(value[1]) is None:
                continue
            data['xml_info'][value[1]] = []
            for item in root.find(value[1]).findall('item'):
                entity = {}
                if 'url' not in item.attrib:
                    continue
                entity['url'] = item.attrib['url']
                if 'preview' in item.attrib:
                    entity['filename'] = item.attrib['preview']
                elif 'media' in item.attrib:
                    entity['filename'] = item.attrib['media']
                entity['provider'] = item.attrib['provider']
                data['xml_info'][value[1]].append(entity)
                """
                2025.10.28 halfaider
                FF에 메타데이터 요청시 자료 업데이트로 과거의 이미지 URL이 누락되면 그 이미지 URL은 고아가 됨.
                플렉스에서 메타데이터 새로고침을 하면 FF의 메타데이터에 명시된 이미지 URL만 파일로 저장이 되고,
                명시되지 않은 고아 URL은 내용물이 'None'인 4 bytes 파일로 저장됨.
                그래서 plex_mate로 파일정리를 한 후 메타데이터 새로고침을 하게 되면 고아 파일은 정상적인 이미지 파일이 아니라 썸네일이 표시되지 않음.
                만약 고아 파일이 xml 파일 정보에 계속 남아 있을 경우 새로고침시 다시 생성됨.
                """
                if not show_data.get('remove_orphans', False):
                    continue
                if path_xml.name == 'Info.xml':
                    path_target = path_xml.parent / value[1] / entity['filename']
                else:
                    path_target = path_xml.parent / path_xml.stem / value[1] / entity['filename']
                try:
                    path_resolved = path_target.resolve()
                    if (size_resolved := path_resolved.stat().st_size) > 10:
                        raise Exception("정상 파일")
                except Exception:
                    continue
                # 파일 내용이 'None' 네 글자만 있는 4 bytes 파일
                P.logger.info(f"고아 파일 발견: {size_resolved} bytes {path_resolved}")
                if show_data.get('dryrun', True):
                    continue
                tmp.remove(item)
                if path_xml.name == 'Info.xml':
                    path_xml_original = path_resolved.parent.parent / path_xml.name
                else:
                    path_xml_original = path_resolved.parent.parent.parent / path_xml.name
                orphans.setdefault(str(path_xml_original), set())
                orphans[str(path_xml_original)].add(path_resolved.name)
                #path_target.unlink(missing_ok=True)
                update_xml = True

        if update_xml:
            write_xml(tree, combined_xmlpath)

        for orphan_xml in orphans:
            try:
                orphan_tree = ElementTree.parse(orphan_xml)
            except Exception:
                continue
            orphan_root = orphan_tree.getroot()
            orphan_tag = orphan_root.find(value[1])
            if orphan_tag is None:
                continue
            orphan_update_xml = False
            for orphan_item in orphan_tag.findall('item'):
                orpahn_preview = orphan_item.get('preview')
                orphan_media = orphan_item.get('media')
                if orpahn_preview in orphans[orphan_xml] or orphan_media in orphans[orphan_xml]:
                    orphan_tag.remove(orphan_item)
                    orphan_update_xml = True
            if orphan_update_xml:
                write_xml(orphan_tree, orphan_xml)

        data.setdefault('process', {})
        for tag, value in tags.items():
            if value[1] in data['xml_info']:
                data['process'][tag] = {
                    'db' : data['db'][f'user_{value[0]}_url'],
                    'db_type' : '', 
                    'url' : '',
                    'filename' : '',
                }

        for tag, value in tags.items():
            if value[1] in data['xml_info']:
                if data['process'][tag]['db']:
                    #P.logger.error(data['process'][tag]['db'])
                    data['process'][tag]['db_type'] = data['process'][tag]['db'].split('://')[0]
                    if data['process'][tag]['db_type'] != 'metadata':
                        #P.logger.warning(combined_xmlpath)
                        #P.logger.warning(data['process'][tag]['db_type'])
                        continue
                    
                    data['process'][tag]['filename'] = data['process'][tag]['db'].split('/')[-1]
                    # db에 현재 선택되어 있는 이미지파일에 맞는 url을 가져온다
                    for item in data['xml_info'][value[1]]:
                        if data['process'][tag]['filename'] == item['filename']:
                            data['process'][tag]['url'] = item['url']
                            tmp = combined_xmlpath.split('/_combined/')
                            tmp2 = data['process'][tag]['db'].split('metadata://')
                            filepath = f"{tmp[0]}/_combined/{tmp2[1]}"
                            if os.path.exists(filepath):
                                data['process'][tag]['localpath'] = filepath
                                if filepath not in show_data['use_filepath']:
                                    show_data['use_filepath'].append(filepath)
                                
                                if os.path.islink(filepath):
                                    data['process'][tag]['islink'] = True
                                    data['process'][tag]['realpath'] = os.path.realpath(filepath)
                                    if data['process'][tag]['realpath'] not in show_data['use_filepath']:
                                        show_data['use_filepath'].append(data['process'][tag]['realpath'])
                                else:
                                    data['process'][tag]['islink'] = False
 
                            break
                        
        return True



    @staticmethod
    def process_step4(data, url):
        return url
        if data['command'] == 'start4':
            from gds_tool import SSGDrive
            drive_url = SSGDrive.upload_from_url(url)
            if drive_url:
                return drive_url
        return url


def write_xml(tree: ElementTree, file_path: str) -> None:
    try:
        tree.write(file_path, encoding='utf-8', xml_declaration=True)
        logger.debug(f"XML 파일 수정 완료: {file_path}")
    except Exception:
        logger.exception(f"XML 파일 수정 실패: {file_path}")
