import sqlite3

from support import SupportFile, d

from .plex_db import PlexDBHandle, dict_factory
from .setup import *


class Task(object):

    @staticmethod
    @celery.task(bind=True)
    def start(self, command, section_id, dryrun):
        config = P.load_config()
        dryrun = True if dryrun == 'true'  else False

        db_file = P.ModelSetting.get('base_path_db')
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        query = config.get('파일정리 음악 쿼리', 'SELECT * FROM metadata_items WHERE metadata_type = 8 AND library_section_id = ? ORDER BY title')
        ce = con.execute(query, (section_id,))
        ce.row_factory = dict_factory
        fetch = ce.fetchall()
        status = {'is_working':'run', 'total_size':0, 'remove_size':0, 'count':len(fetch), 'current':0}

        for artist in fetch:
            try:
                if P.ModelSetting.get_bool('clear_music_task_stop_flag'):
                    return 'stop'
                time.sleep(0.05)
                status['current'] += 1
                data = {'mode':'artist', 'status':status, 'command':command, 'section_id':section_id, 'dryrun':dryrun, 'process':{}, 'file_count':0, 'remove_count':0}
                data['db'] = artist

                Task.artist_process(data, con, cur)
            
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
                logger.error(artist['title'])
        logger.warning(f"종료")
        return 'wait'




    @staticmethod
    def artist_process(data, con, cur):

        data['meta'] = {'remove':0}
        data['meta']['metapath'] = os.path.join(P.ModelSetting.get('base_path_metadata'), 'Artists', data['db']['hash'][0], f"{data['db']['hash'][1:]}.bundle")

        data['meta']['total'] = SupportFile.size(start_path=data['meta']['metapath'])
        if data['command'] == 'start0':
            return
        combined_xmlpath = os.path.join(data['meta']['metapath'], 'Contents', '_combined', 'Info.xml')
        if os.path.exists(combined_xmlpath) == False:
            return 
        data['use_filepath'] = []
        data['remove_filepath'] = []
        data['albums'] = {}
        ret = Task.xml_analysis(combined_xmlpath, data)
        if ret == False:
            logger.warning(f"{data['db']['title']} 아티스트 분석 실패")
            return
        
        # 2022-05-11 앨범은 인덱스 모두 1임.
        # 트랙은 순서대로 있음
        #album_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 9 and parent_id = ? ORDER BY "index"', (data['db']['id'],))
        album_cs = con.execute('SELECT * FROM metadata_items WHERE metadata_type = 9 and parent_id = ?', (data['db']['id'],))
        album_cs.row_factory = dict_factory
        data['albums'] = []
        for album in album_cs.fetchall():
            album_data = {'db':album, 'use_filepath':[], 'remove_filepath':[]}
            album_data['meta'] = {'remove':0}
            album_data['meta']['metapath'] = os.path.join(P.ModelSetting.get('base_path_metadata'), 'Albums', album_data['db']['hash'][0], f"{album_data['db']['hash'][1:]}.bundle")
            data['meta']['total'] += SupportFile.size(start_path=album_data['meta']['metapath'])
            
            combined_xmlpath = os.path.join(album_data['meta']['metapath'], 'Contents', '_combined', 'Info.xml')

            ret = Task.xml_analysis(combined_xmlpath, album_data)
            if ret == False:
                logger.warning(combined_xmlpath)
                logger.warning(f"{album_data['db']['title']} 앨범 분석 실패")
            else:
                data['albums'].append(album_data)

        query = ""

        if data['command'] == 'start2':
            # 쇼 http로 
            sql = 'UPDATE metadata_items SET '
            if data['process']['poster']['url'] != '':
                sql += ' user_thumb_url = "{}", '.format(data['process']['poster']['url'])
                try: data['use_filepath'].remove(data['process']['poster']['localpath'])
                except: pass
                try: data['use_filepath'].remove(data['process']['poster']['realpath'])
                except: pass
            if data['process']['art']['url'] != '':
                sql += ' user_art_url = "{}", '.format(data['process']['art']['url'])
                try: data['use_filepath'].remove(data['process']['art']['localpath'])
                except: pass
                try: data['use_filepath'].remove(data['process']['art']['realpath'])
                except: pass
                
            if sql != 'UPDATE metadata_items SET ':
                sql = sql.strip().rstrip(',')
                sql += '  WHERE id = {} ;\n'.format(data['db']['id'])
                query += sql

            for album in data['albums']:
                if 'process' not in album:
                    continue
                sql = 'UPDATE metadata_items SET '
                # localmedia 로 생성된 파일은 url이 셋된다.
                #if album['process']['poster']['url'] != '':
                # 2022-05-11 태그로 생성된 앨범은 디스코드에 올리고 셋
                if album['process']['poster']['url'] != '' and album['process']['poster']['url'].startswith('http') == False:
                    if 'localpath' in album['process']['poster'] and album['process']['poster']['localpath'] != '':
                        localpath = album['process']['poster']['localpath']
                        if localpath[0] != '/':
                            localpath = localpath.replace('/', '\\')
                        if os.path.exists(localpath):
                            if data['dryrun'] == False:
                                from gds_tool import SSGDrive
                                discord_url = SSGDrive.upload_from_path(localpath)
                                if discord_url is not None:
                                    album['process']['poster']['url'] = discord_url
                                    logger.warning(discord_url)

                if album['process']['poster']['url'].startswith('http'):
                    sql += ' user_thumb_url = "{}", '.format(album['process']['poster']['url'])
                    try: data['use_filepath'].remove(album['process']['poster']['localpath'])
                    except: pass
                    try: data['use_filepath'].remove(album['process']['poster']['realpath'])
                    except: pass

                if album['process']['art']['url'] != '':
                    sql += ' user_art_url = "{}", '.format(album['process']['art']['url'])
                    try: data['use_filepath'].remove(album['process']['art']['localpath'])
                    except: pass
                    try: data['use_filepath'].remove(album['process']['art']['realpath'])
                    except: pass
                if sql != 'UPDATE metadata_items SET ':
                    sql = sql.strip().rstrip(',')
                    sql += '  WHERE id = {} ;\n'.format(album['db']['id'])
                    query += sql

        if query != '' and data['dryrun'] == False:
            PlexDBHandle.execute_query(query)

        for base, folders, files in os.walk(data['meta']['metapath']):
            for f in files:
                data['file_count'] += 1
                filepath = os.path.join(base, f)
                if filepath not in data['use_filepath']:
                    if os.path.islink(filepath) and os.path.exists(filepath) == False:
                        os.remove(filepath)
                    elif os.path.exists(filepath):
                        data['remove_count'] += 1
                        if filepath not in data['remove_filepath']:
                            data['remove_filepath'].append(filepath)
                        if os.path.islink(filepath) == False:
                            data['meta']['remove'] += os.path.getsize(filepath)
                        if data['dryrun'] == False:
                            os.remove(filepath)
        
        for album in data['albums']:
            for base, folders, files in os.walk(album['meta']['metapath']):
                for f in files:
                    data['file_count'] += 1
                    filepath = os.path.join(base, f)
                    if filepath not in album['use_filepath']:
                        if os.path.islink(filepath) and os.path.exists(filepath) == False:
                            os.remove(filepath)
                        elif os.path.exists(filepath):
                            data['remove_count'] += 1
                            if filepath not in album['remove_filepath']:
                                data['remove_filepath'].append(filepath)
                            if os.path.islink(filepath) == False:
                                data['meta']['remove'] += os.path.getsize(filepath)
                            if data['dryrun'] == False:
                                os.remove(filepath)
                    else:
                        data['use_filepath'].append(filepath)
        for base, folders, files in os.walk(data['meta']['metapath']):
            if not folders and not files:
                os.removedirs(base)
        for album in data['albums']:
            for base, folders, files in os.walk(album['meta']['metapath']):
                if not folders and not files:
                    os.removedirs(base)


    @staticmethod
    def xml_analysis(combined_xmlpath, data):
        import xml.etree.ElementTree as ET
        if os.path.exists(combined_xmlpath) == False:
            return False
        if combined_xmlpath not in data['use_filepath']:
            data['use_filepath'].append(combined_xmlpath)

        tree = ET.parse(combined_xmlpath)
        root = tree.getroot()
        data['xml_info'] = {}
        # 추출할 정보 
        tags = {
            'poster' : ['thumb', 'posters'],
            'art' : ['art', 'art']
        }

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

        data['process'] = {}
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
                if data['process'][tag]['db'] != '':
                    data['process'][tag]['db_type'] = data['process'][tag]['db'].split('://')[0]
                    if data['process'][tag]['db_type'] != 'metadata':
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
                                if filepath not in data['use_filepath']:
                                    data['use_filepath'].append(filepath)
                                
                                if os.path.islink(filepath):
                                    data['process'][tag]['islink'] = True
                                    data['process'][tag]['realpath'] = os.path.realpath(filepath)
                                    if data['process'][tag]['realpath'] not in data['use_filepath']:
                                        data['use_filepath'].append(data['process'][tag]['realpath'])
                                else:
                                    data['process'][tag]['islink'] = False
                            break
        return True
