import platform
import sqlite3

from support import SupportFile, d

from .plex_db import PlexDBHandle, dict_factory
from .plex_web import PlexWebHandle
from .setup import *
from .task_clear_show import TAG, SQL_QUERIES, set_tag_ids


logger = P.logger


class Task(object):

    @staticmethod
    @celery.task(bind=True)
    def start(self, command, section_id, dryrun):
        if command == 'start4':
            logger.warning(f'4단계는 현재 지원하지 않습니다.')
            return 'stop'
        config = P.load_config()
        logger.warning(command)
        logger.warning(section_id)
        dryrun = True if dryrun == 'true'  else False
        logger.warning(dryrun)

        db_file = P.ModelSetting.get('base_path_db')
        with sqlite3.connect(db_file) as con:
            cur = con.cursor()
            query = config.get('파일정리 영화 쿼리', 'SELECT * FROM metadata_items WHERE metadata_type = 1 AND library_section_id = ? ORDER BY title')
            ce = con.execute(query, (section_id,))
            ce.row_factory = dict_factory
            query_count = query.replace("SELECT *", "SELECT COUNT(*)")
            row_count = con.execute(query_count, (section_id,)).fetchone()
            status = {'is_working':'run', 'total_size':0, 'remove_size':0, 'count':row_count[0], 'current':0}

            agent = (PlexDBHandle.library_section(section_id).get('agent') or '').strip()
            if agent == 'tv.plex.agents.series':
                set_tag_ids(con)

            for movie in ce:
                try:
                    if P.ModelSetting.get_bool('clear_movie_task_stop_flag'):
                        return 'stop'
                    time.sleep(0.05)
                    status['current'] += 1
                    data = {'mode':'movie', 'status':status, 'command':command, 'section_id':section_id, 'dryrun':dryrun, 'process':{}}
                    data['db'] = movie
                    data['agent'] = agent

                    Task.analysis(data, con, cur)
                    data['status']['total_size'] += data['meta']['total']
                    data['status']['remove_size'] += data['meta']['remove']
                    if 'media' in data:
                        data['status']['total_size'] += data['media']['total']
                        data['status']['remove_size'] += data['media']['remove']
                    if F.config['use_celery']:
                        self.update_state(state='PROGRESS', meta=data)
                    else:
                        self.receive_from_task(data, celery=False)
                except Exception as e:
                    logger.error(f'Exception:{str(e)}')
                    logger.error(traceback.format_exc())
                    logger.error(movie['title'])
            logger.warning(f"종료")
            return 'wait'



    @staticmethod
    def analysis(data, con, cur):
        Task.thumb_process(data, con)

        if data['command'] == 'start1':
            return
        
        # 2단계 TAG별 URL 로 세팅하고 xml 파일만 남기고 제거
        if data['dryrun'] == False:
            sql = 'UPDATE metadata_items SET '
            should_execute = False
            for key in TAG:
                if url := data['process'].get(key, {}).get('url', ''):
                    should_execute = True
                    sql += f" user_{TAG[key][0]}_url = '{url}', "
            if should_execute:
                sql = sql.strip().rstrip(',')
                sql += '  WHERE id = {} ;'.format(data['db']['id'])
                sql_filepath = os.path.join(path_data, 'tmp', f"movie_{data['db']['id']}.sql")
                PlexDBHandle.execute_query(sql, sql_filepath=sql_filepath)
            else:
                Task.process_agent_none(data, con, cur)
        
        c_upload_path = os.path.join(data['meta']['metapath'], 'Uploads')
        if os.path.exists(c_upload_path):
            if data['dryrun'] == False:
                data['meta']['remove'] += SupportFile.size(start_path=c_upload_path)
                SupportFile.rmtree(c_upload_path)
                logger.debug(f"삭제: {c_upload_path} ({data['db']['title']})")
        c_metapath = os.path.join(data['meta']['metapath'], 'Contents')  
        if os.path.exists(c_metapath):
            for f in os.listdir(c_metapath):
                _path = os.path.join(c_metapath, f)
                if f == '_combined':
                    for tag, value in TAG.items():
                        tag_path = os.path.join(_path, value[1])
                        if os.path.exists(tag_path):
                            if data['dryrun'] == False:
                                data['meta']['remove'] += SupportFile.size(start_path=tag_path)
                                logger.debug(f"삭제: {tag_path} ({data['db']['title']})")
                                SupportFile.rmtree(tag_path)
                            
                    tmp = os.path.join(_path, 'extras')
                    if os.path.exists(tmp) and len(os.listdir(tmp)) == 0:
                        if data['dryrun'] == False:
                            SupportFile.rmtree(tmp)
                    tmp = os.path.join(_path, 'extras.xml')
                    if os.path.exists(tmp):
                        if os.path.exists(tmp):
                            data['meta']['remove'] += os.path.getsize(tmp)
                            if data['dryrun'] == False:
                                os.remove(tmp)
                else:
                    tmp = SupportFile.size(start_path=_path)
                    if data['dryrun'] == False:
                        data['meta']['remove'] += tmp
                        SupportFile.rmtree(_path)
                    else:
                        if f == '_stored':
                            data['meta']['remove'] += tmp

        # 메타폴더
        for base, folders, files in os.walk(data['meta']['metapath']):
            for f in files:
                if f.endswith('.xml'):
                    continue
                filepath = os.path.join(base, f)
                if os.path.islink(filepath):
                    if os.path.exists(os.path.realpath(filepath)) == False:
                        P.logger.info("링크제거")
                        os.remove(filepath)
                        continue
                
                    tmp = f.split('.')[-1]
                    using = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE user_thumb_url LIKE '%{tmp}' OR user_art_url LIKE '%{tmp}';")
                    
                    if len(using) == 0:
                        if os.path.exists(filepath):
                            data['meta']['remove'] += os.path.getsize(filepath)
                            P.logger.debug(f"안쓰는 파일 삭제 : {filepath}")
                            os.remove(filepath)
                        else:
                            P.logger.error('.................. 파일 없음')
                    else:
                        P.logger.debug(f"파일 사용: {filepath}")
        

        Task.remove_empty_folder(data['meta']['metapath'])




        if data['command'] == 'start2':
            return

        media_ce = con.execute('SELECT user_thumb_url, user_art_url, media_parts.file, media_parts.hash FROM metadata_items, media_items, media_parts WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND metadata_items.id = ?;', (data['db']['id'],))
        media_ce.row_factory = dict_factory
        data['media'] = {'total':0, 'remove':0}

        mediapath = None
        for item in media_ce:
            if item['hash'] == '':
                continue
            mediapath = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost', item['hash'][0], f"{item['hash'][1:]}.bundle")
            if os.path.exists(mediapath) == False:
                continue
            data['media']['total'] += SupportFile.size(start_path=mediapath)
            if item['user_thumb_url'].startswith('media') == False:
                img = os.path.join(mediapath, 'Contents', 'Thumbnails', 'thumb1.jpg')
                if os.path.exists(img):
                    data['media']['remove'] += os.path.getsize(img)
                    if data['dryrun'] == False:
                        P.logger.debug(f"미디어 썸네일 삭제: {img}")
                        os.remove(img)
            if item['user_art_url'].startswith('media') == False:
                img = os.path.join(mediapath, 'Contents', 'Art', 'art1.jpg')
                if os.path.exists(img):
                    data['media']['remove'] += os.path.getsize(img)
                    if data['dryrun'] == False:
                        P.logger.debug(f"미디어 아트 삭제: {img}")
                        os.remove(img)
            else:
                if data['command'] == 'start4':
                    img = os.path.join(mediapath, 'Contents', 'Art', 'art1.jpg')
                    
                    if data['dryrun'] == False:
                        if os.path.exists(img):
                            from gds_tool import SSGDrive
                            discord_url = SSGDrive.upload_from_path(img)
                            if discord_url is not None:
                                P.logger.warning(discord_url)
                                sql = 'UPDATE metadata_items SET '
                                sql += ' user_art_url = "{}" '.format(discord_url)
                                sql += '  WHERE id = {} ;\n'.format(data['db']['id'])
                                ret = PlexDBHandle.execute_query(sql)
                                if ret.find('database is locked') == -1:
                                    data['media']['remove'] += os.path.getsize(img)
                                    os.remove(img)
                        else:
                            P.logger.debug(f"아트 파일 없음. 분석 {data['db']['title']}")
                            PlexWebHandle.analyze_by_id(data['db']['id'])
        if mediapath:
            Task.remove_empty_folder(mediapath)


    @staticmethod
    def xml_analysis(combined_xmlpath, data):
        if not os.path.exists(combined_xmlpath):
            #P.logger.debug(f"Info.xml 없음 {data['db']['title']} : {combined_xmlpath}")
            return
        import xml.etree.ElementTree as ET

        tree = ET.parse(combined_xmlpath)
        root = tree.getroot()
        for tag in TAG:
            found = root.find(TAG[tag][1])
            if found is None:
                continue

            data['info'].setdefault(tag, [])
            for item in found.findall('item'):
                entity = {}
                if 'url' not in item.attrib:
                    continue
                entity['url'] = item.attrib['url']
                if 'preview' in item.attrib:
                    entity['filename'] = item.attrib['preview']
                elif 'media' in item.attrib:
                    entity['filename'] = item.attrib['media']
                entity['provider'] = item.attrib['provider']
                data['info'][tag].append(entity)



    # xml 정보를 가져오고, 중복된 이미지를 지운다
    @staticmethod
    def thumb_process(data, con):
        data['meta'] = {'remove':0}
        if data['db']['metadata_type'] == 1:
            data['meta']['metapath'] = os.path.join(P.ModelSetting.get('base_path_metadata'), 'Movies', data['db']['hash'][0], f"{data['db']['hash'][1:]}.bundle")
            combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'Info.xml')
        elif data['db']['metadata_type'] == 2:
            data['meta']['metapath'] = os.path.join(P.ModelSetting.get('base_path_metadata'), 'TV Shows', data['db']['hash'][0], f"{data['db']['hash'][1:]}.bundle")
            combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'Info.xml')
            
        data['meta']['total'] = SupportFile.size(start_path=data['meta']['metapath'])
        if data['command'] == 'start0':
            return

        # 기본 세팅
        data.setdefault('process', {})
        for tag, value in TAG.items():
            column_url = data['db'][f'user_{value[0]}_url'] or ''
            data['process'][tag] = {
                'db' : column_url,
                'db_type' : column_url.split('://')[0], 
                'url' : '',
                'filename' : column_url.split('/')[-1],
                'location' : '',
            }
            data['info'] = {tag: []}

        if not os.path.exists(combined_xmlpath):
            '''
            2025.04.05 halfaider
            새로운 Plex 기본 에이전트는 Info.xml을 사용하지 않고 DB에 포스터 url을 저장함
            '''
            for key in TAG:
                if TAG[key][2] is None:
                    continue
                process_info = data['process'][key]
                if process_info['db_type'] == 'metadata':
                    tagging_cursor = con.execute(SQL_QUERIES[0], (value[2], data['db']['id'], column_url))
                elif process_info['db_type'] == 'media':
                    tagging_cursor = con.execute(SQL_QUERIES[1], (value[2], data['db']['id']))
                else:
                    continue
                tagging_cursor.row_factory = dict_factory
                tagging_row = tagging_cursor.fetchone()
                if tagging_row and (web_url := (tagging_row.get('text') or '')).startswith('http'):
                    data['info'][key].append({
                        'url': web_url,
                        'filename': tagging_row.get('thumb_url', '').split('/')[-1],
                        'provider': 'tv.plex.agents.movie',
                    })
                    data['process'][key]['url'] = web_url
            return

        Task.xml_analysis(combined_xmlpath, data)

        for tag, value in TAG.items():
            if data['process'][tag]['db']:
                for item in data['info'][tag]:
                    if data['process'][tag]['filename'] == item['filename']:
                        data['process'][tag]['url'] = item['url']
                        break

        #logger.error(d(data['process']))
        # 1단계.
        # _combined 에서 ..stored 
        
        not_remove_filelist = []
        c_metapath = os.path.join(data['meta']['metapath'], 'Contents')
        if os.path.exists(c_metapath):
            for f in os.listdir(c_metapath):
                _path = os.path.join(c_metapath, f)
                # 윈도우는 combined에 바로 데이터가 있어서 무조건 삭제?
                if f == '_stored':
                    tmp = SupportFile.size(start_path=_path)
                    data['meta']['stored'] = tmp
                    if platform.system() == 'Windows':
                        data['meta']['remove'] += tmp
                        if data['dryrun'] == False:
                            SupportFile.rmtree(_path)
                elif f == '_combined':
                    for tag, value in TAG.items():
                        tag_path = os.path.join(_path, value[1])
                        if os.path.exists(tag_path) == False:
                            continue
                        for img_file in os.listdir(tag_path):
                            img_path = os.path.join(tag_path, img_file)
                            if os.path.islink(img_path):
                                if os.path.realpath(img_path).find('_stored') == -1:
                                    # 저장된 파일에 대한 링크가 아니기 삭제
                                    # db에 저장된 url이 stored가 아닌 에이전트 폴더를 가로 가르키는 경우가 있음
                                    #logger.warning(img_file)
                                    if img_file == data['process'][tag]['filename']:
                                        logger.error(data['process'][tag]['filename'])
                                        not_remove_filelist.append(data['process'][tag]['filename'])
                                        continue
                                    if data['dryrun'] == False:# and os.path.exists(img_path) == True:
                                        os.remove(img_path)
                            else: #윈도우
                                if img_file != data['process'][tag]['filename']:
                                    # 저장파일이 아니기 때문에 삭제
                                    data['meta']['remove'] += os.path.getsize(img_path)
                                    if data['dryrun'] == False and os.path.exists(img_path) == True:
                                        os.remove(img_path)
                    
            for f in os.listdir(c_metapath):
                _path = os.path.join(c_metapath, f)
                if f == '_stored' or f == '_combined':
                    continue
                tmp = SupportFile.size(start_path=_path)
                data['meta']['remove'] += tmp
                if data['dryrun'] == False:
                    SupportFile.rmtree(_path)

        if not_remove_filelist:
            logger.error(not_remove_filelist)



    def metafolder_common(bundle_path, data):
        data['remove'] = 0
        for base, folders, files in os.walk(bundle_path):
            for f in files:
                if f.endswith('.xml'):
                    continue
                filepath = os.path.join(base, f)
                if os.path.islink(filepath):
                    if os.path.exists(os.path.realpath(filepath)) == False:
                        P.logger.info("링크제거")
                        os.remove(filepath)
                        continue
                
                    tmp = f.split('.')[-1]
                    using = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE user_thumb_url LIKE '%{tmp}' OR user_art_url LIKE '%{tmp}';")
                    
                    if len(using) == 0:
                        if os.path.exists(filepath):
                            data['remove'] += os.path.getsize(filepath)
                            P.logger.debug(f"안쓰는 파일 삭제 : {filepath}")
                            os.remove(filepath)
                        else:
                            P.logger.error('.................. 파일 없음')
                    else:
                        P.logger.debug(f"파일 사용: {filepath}")
        return data

    def remove_empty_folder(bundle_path):
        while True:
            count = 0
            for base, folders, files in os.walk(bundle_path):
                if not folders and not files:
                    os.removedirs(base)
                    P.logger.debug(f"빈 폴더 삭제: {base} ")
                    count += 1
            if count == 0:
                break


    # 기타 비디오 타입
    def process_agent_none(data, con, cur):
        if data['db']['guid'].startswith('tv.plex.agents.none') == False:
            return
        if data['command'] != 'start4':
            return

        media_ce = con.execute('SELECT user_thumb_url, user_art_url, media_parts.file, media_parts.hash FROM metadata_items, media_items, media_parts WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND metadata_items.id = ?;', (data['db']['id'],))
        media_ce.row_factory = dict_factory
        data['media'] = {'total':0, 'remove':0}

        for item in media_ce:
            if item['hash'] == '':
                continue
            mediapath = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost', item['hash'][0], f"{item['hash'][1:]}.bundle")
            if os.path.exists(mediapath) == False:
                continue
            data['media']['total'] += SupportFile.size(start_path=mediapath)
            count = 0
            if item['user_thumb_url'].startswith('media'):
                img = os.path.join(mediapath, 'Contents', 'Thumbnails', 'thumb3.jpg')
                if os.path.exists(img):
                    from gds_tool import SSGDrive
                    gdrive_url = SSGDrive.upload_from_path(img)
                    if gdrive_url is not None:
                        P.logger.warning(gdrive_url)
                        sql = 'UPDATE metadata_items SET '
                        sql += ' user_thumb_url = "{}" '.format(gdrive_url)
                        sql += '  WHERE id = {} ;\n'.format(data['db']['id'])
                        ret = PlexDBHandle.execute_query(sql)
                        if ret.find('database is locked') == -1:
                            data['media']['remove'] += os.path.getsize(img)
                            os.remove(img)
                            count += 1
            else:
                count += 1
                img = os.path.join(mediapath, 'Contents', 'Thumbnails', 'thumb3.jpg')
                if os.path.exists(img):
                    data['media']['remove'] += os.path.getsize(img)
                    if data['dryrun'] == False:
                        os.remove(img)

            if item['user_art_url'].startswith('media'):
                img = os.path.join(mediapath, 'Contents', 'Art', 'art3.jpg')
                if os.path.exists(img):
                    from gds_tool import SSGDrive
                    gdrive_url = SSGDrive.upload_from_path(img)
                    if gdrive_url is not None:
                        P.logger.warning(gdrive_url)
                        sql = 'UPDATE metadata_items SET '
                        sql += ' user_art_url = "{}" '.format(gdrive_url)
                        sql += '  WHERE id = {} ;\n'.format(data['db']['id'])
                        ret = PlexDBHandle.execute_query(sql)
                        if ret.find('database is locked') == -1:
                            data['media']['remove'] += os.path.getsize(img)
                            os.remove(img)
                            count += 1
            else:
                count += 1
                img = os.path.join(mediapath, 'Contents', 'Thumbnails', 'art3.jpg')
                if os.path.exists(img):
                    data['media']['remove'] += os.path.getsize(img)
                    if data['dryrun'] == False:
                        os.remove(img)

            if count == 2:
                shutil.rmtree(mediapath)
                
