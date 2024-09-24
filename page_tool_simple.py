import shutil
import threading
import time

from .plex_db import PlexDBHandle
from .setup import *

logger = P.logger


class PageToolSimple(PluginPageBase):
    def __init__(self, P, parent):
        super(PageToolSimple, self).__init__(P, parent, name='simple')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_library_location_source' : '',
            f'{self.parent.name}_{self.name}_library_location_target' : '',
            f'{self.parent.name}_{self.name}_remove_meta_id' : '',
            f'{self.parent.name}_{self.name}_remove_db_by_folder' : '',
            
        }
    
    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'update_show_add':
                query = 'UPDATE metadata_items SET added_at = (SELECT max(added_at) FROM metadata_items mi WHERE mi.parent_id = metadata_items.id OR mi.parent_id IN(SELECT id FROM metadata_items mi2 WHERE mi2.parent_id = metadata_items.id)) WHERE metadata_type = 2;'
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_collection_count':
                query = f"SELECT count(*) AS cnt FROM metadata_items WHERE metadata_type = 18 AND library_section_id = {arg1};"
                result = PlexDBHandle.select(query)
                if result is not None and len(result)>0:
                    ret = {'ret':'success', 'msg':f"{result[0]['cnt']}개의 컬렉션이 있습니다."}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_collection':
                query = f"DELETE FROM metadata_items WHERE metadata_type = 18 AND library_section_id = {arg1};"
                query += f"UPDATE metadata_items SET tags_collection = '' WHERE library_section_id = {arg1};"
                query += f"DELETE FROM tags WHERE id in (SELECT DISTINCT tags.id FROM metadata_items, taggings, tags WHERE  metadata_items.id = taggings.metadata_item_id AND taggings.tag_id=tags.id AND tag_type = 2 AND metadata_items.library_section_id = {arg1});"
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_extra_count':
                query = f"SELECT count(*) AS cnt FROM metadata_items WHERE metadata_type = 12 AND guid LIKE 'sjva://sjva.me%';"
                result = PlexDBHandle.select(query)
                if result is not None and len(result)>0:
                    ret = {'ret':'success', 'msg':f"{result[0]['cnt']}개의 부가영상이 있습니다."}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_extra':
                query = f"DELETE FROM metadata_items WHERE metadata_type = 12 AND guid LIKE 'sjva://sjva.me%';"
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'library_location_source':
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_library_location_source', arg1)

                query = f'SELECT count(*) AS cnt FROM section_locations WHERE root_path LIKE "{arg1}%";'
                result = PlexDBHandle.select(query)
                msg = f"섹션폴더 (section_locations) : {result[0]['cnt']}<br>"

                query = f'SELECT count(*) AS cnt FROM media_parts WHERE file LIKE "{arg1}%";'
                result = PlexDBHandle.select(query)
                msg += f"영상파일 (media_parts) : {result[0]['cnt']}<br>"

                # 윈도우
                tmp = arg1
                if tmp[0] != '/':
                    tmp = '/' + tmp
                tmp = tmp.replace('%', '%25').replace(' ', '%20').replace('\\', '/')
                query = f'SELECT count(*) AS cnt FROM media_streams WHERE url LIKE "file://{tmp}%";'
                result = PlexDBHandle.select(query)
                msg += f"자막 (media_streams) : {result[0]['cnt']}"

                ret = {'ret':'success', 'msg':msg}
            elif command == 'library_location_target':
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_library_location_source', req.form['arg1'])
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_library_location_target', req.form['arg2'])

                # 2024-09-05
                query = "SELECT id, root_path FROM section_locations"
                rows = PlexDBHandle.select(query)
                for idx, row in enumerate(rows):
                    #logger.warning(f"{idx}/{len(rows)} {row}")
                    if arg1.startswith(row['root_path']):
                        logger.error(row['root_path'])
                        tmp1 = arg1.replace(row['root_path'], '').lstrip('/')
                        tmp2 = arg2.replace(row['root_path'], '').lstrip('/')
                        if len(tmp1.split('/')) != len(tmp2.split('/')):
                            break
                        #logger.error(tmp1)
                        #logger.error(tmp2)
                        tmp1 = tmp1.replace("'", "''")
                        tmp2 = tmp2.replace("'", "''")
                        query1 = "SELECT * FROM directories WHERE path = ?"
                        dir_ret = PlexDBHandle.select_arg(query1, (tmp1,))
                        #logger.info(d(dir_ret))
                        if len(dir_ret):
                            query = f"UPDATE directories SET path = '{tmp2}' WHERE path = '{tmp1}';"
                            PlexDBHandle.execute_query(query)
                            break

                query = f'UPDATE section_locations SET root_path = REPLACE(root_path, "{arg1}", "{arg2}");'
                query += f'UPDATE media_parts SET file = REPLACE(file, "{arg1}", "{arg2}");'

                ret = []
                for _ in [arg1, arg2]:
                    tmp = _
                    if tmp[0] != '/':
                        tmp = '/' + tmp
                    tmp = tmp.replace('%', '%25').replace(' ', '%20').replace('\\', '/')
                    ret.append(tmp)

                query += f'UPDATE media_streams SET url = REPLACE(url, "{ret[0]}", "{ret[1]}");'

                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'duplicate_list':
                query = f"select metadata_items.id as meta_id, metadata_items.media_item_count,  media_items.id as media_id, media_parts.id as media_parts_id, media_parts.file from media_items, metadata_items, media_parts, (select media_parts.file as file, min(media_items.id) as media_id,  count(*) as cnt from media_items, metadata_items, media_parts where media_items.metadata_item_id = metadata_items.id and media_parts.media_item_id = media_items.id and metadata_items.media_item_count > 1 and media_parts.file != '' group by media_parts.file having cnt > 1) as ttt where media_items.metadata_item_id = metadata_items.id and media_parts.media_item_id = media_items.id and metadata_items.media_item_count > 1 and media_parts.file != '' and media_parts.file = ttt.file order by meta_id, media_id, media_parts_id;"
                data = PlexDBHandle.select(query)
                ret['modal'] = json.dumps(data, indent=4, ensure_ascii=False)
                ret['title'] = '목록'
            elif command == 'duplicate_remove':
                query = f"select metadata_items.id as meta_id, metadata_items.media_item_count,  media_items.id as media_id, media_parts.id as media_parts_id, media_parts.file from media_items, metadata_items, media_parts, (select media_parts.file as file, min(media_items.id) as media_id,  count(*) as cnt from media_items, metadata_items, media_parts where media_items.metadata_item_id = metadata_items.id and media_parts.media_item_id = media_items.id and metadata_items.media_item_count > 1 and media_parts.file != '' group by media_parts.file having cnt > 1) as ttt where media_items.metadata_item_id = metadata_items.id and media_parts.media_item_id = media_items.id and metadata_items.media_item_count > 1 and media_parts.file != '' and media_parts.file = ttt.file order by meta_id, media_id, media_parts_id;"
                data = PlexDBHandle.select(query)
                prev = None
                filelist = []
                query = ''
                def delete_medie(meta_id, media_id):
                    tmp = f"DELETE FROM media_streams WHERE media_item_id = {media_id};\n"
                    tmp += f"DELETE FROM media_parts WHERE media_item_id = {media_id};\n"
                    tmp += f"DELETE FROM media_items WHERE id = {media_id};\n"
                    tmp += f"UPDATE metadata_items SET media_item_count = (SELECT COUNT(*) FROM media_items WHERE metadata_item_id = {meta_id}) WHERE id = {meta_id};\n"
                    return tmp
                def delete_part(part_id):
                    tmp = f"DELETE FROM media_streams WHERE media_part_id = {part_id};\n"
                    tmp += f"DELETE FROM media_parts WHERE id = {part_id};\n"
                    return tmp
                for idx, current in enumerate(data):
                    try:
                        if prev is None:
                            continue
                        if current['meta_id'] != prev['meta_id'] and current['file'] in filelist:
                            logger.warning(d(current))
                            pass
                        if current['meta_id'] == prev['meta_id'] and current['file'] == prev['file']:
                            if current['media_id'] != prev['media_id']:
                                query += delete_medie(current['meta_id'], current['media_id'])
                            elif current['media_parts_id'] != prev['media_parts_id']:
                                query += delete_part(current['media_parts_id'])

                    finally:     
                        if current['file'] not in filelist:
                            filelist.append(current['file'])
                        prev = current
                if query != '':
                    logger.warning(query)
                    result = PlexDBHandle.execute_query(query)
                    if result != False:
                        ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                    else:
                        ret = {'ret':'warning', 'msg':'실패'}
                else:
                    ret = {'ret':'success', 'msg':'처리할 내용이 없습니다.'}
            elif command == 'equal_file_equal_meta':
                query = f"""select media_parts.file, replace(media_parts.file, rtrim(media_parts.file, replace(media_parts.file, '/', '')), '') AS filename from media_parts, metadata_items, media_items, (SELECT metadata_items.id as id, replace(media_parts.file, rtrim(media_parts.file, replace(media_parts.file, '/', '')), '') AS filename, count(*) AS cnt FROM metadata_items, media_items, media_parts WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND metadata_items.library_section_id = 18 GROUP BY filename HAVING cnt > 1 ORDER BY file) AS tmp where metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND metadata_items.library_section_id = {arg1} and media_parts.file != '' and filename = tmp.filename and metadata_items.id = tmp.id order by file"""
                data = PlexDBHandle.select(query)
                ret['modal'] = json.dumps(data, indent=4, ensure_ascii=False)
                ret['title'] = '목록'
            elif command == 'empty_episode_process':
                section_id = arg1
                query = f"""UPDATE metadata_items as A SET user_thumb_url = (SELECT user_art_url FROM metadata_items WHERE id in (SELECT parent_id FROM metadata_items as B WHERE id in (SELECT parent_id FROM metadata_items WHERE A.id = b.parent_id AND library_section_id = {section_id} AND (user_thumb_url = '' or user_thumb_url LIKE 'media%')))) WHERE library_section_id = {section_id} AND (user_thumb_url = '' or user_thumb_url LIKE 'media%')"""
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_trash':
                section_id = arg1
                query = f"""UPDATE metadata_items SET deleted_at = null WHERE deleted_at is not null AND library_section_id = {section_id};
                UPDATE media_items SET deleted_at = null WHERE deleted_at is not null AND library_section_id = {section_id};
                UPDATE media_parts SET deleted_at = null WHERE deleted_at is not null AND media_item_id in (SELECT id FROM media_items WHERE library_section_id = {section_id});"""
                result = PlexDBHandle.execute_query(query)
                logger.error(result)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'remove_meta_id':
                P.ModelSetting.set('tool_simple_remove_meta_id', arg1)
                ret = self.remove_meta(arg1)
            elif command == 'remove_db_by_folder':
                P.ModelSetting.set('tool_simple_remove_db_by_folder', arg1)
                ret = self.remove_db_by_folder(arg1)
            elif command == 'fix_yamlmusic':
                self.task_interface(self.fix_yamlmusic)
                ret['msg'] = "작업을 시작합니다."
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})

    def remove_meta(self, metaid):
        #ret = PlexDBHandle.section_location()
        DRYRUN = False
        ret = {}
        delete_query = ''
        query = f"""
            SELECT id, metadata_type, hash, title, library_section_id  FROM metadata_items WHERE id = {metaid}
            UNION
            SELECT id, metadata_type, hash, title, library_section_id FROM metadata_items WHERE parent_id = {metaid}
            UNION
            SELECT id, metadata_type, hash, title, library_section_id FROM metadata_items WHERE parent_id = (
                SELECT id FROM metadata_items WHERE parent_id = {metaid}
            )"""

        metdata_items = PlexDBHandle.select(query)
        
        if len(metdata_items) == 0:
            ret['msg'] = "메타가 존재하지 않습니다."
            return ret
        
        metdata_items_ids = [ x['id']  for x in metdata_items ]
        metdata_items_ids_query = [ str(x['id'])  for x in metdata_items ]
        logger.info(f"metadata_items - id : {metdata_items_ids}")
        ret['metdata_items'] = len(metdata_items)
        
        logger.info(f"{metdata_items[0]}")
        library_section_id = metdata_items[0]['library_section_id']
        logger.info(f"{metdata_items[0]['title']} - {metdata_items[0]['hash']}")
        metapath = P.ModelSetting.get('base_path_metadata')
        # 8 아티스트
        # 9 앨범
        if metdata_items[0]['metadata_type'] == 1:
            foldername = "Movies"
        elif metdata_items[0]['metadata_type'] == 2:
            foldername = "TV Shows"
        elif metdata_items[0]['metadata_type'] == 8:
            foldername = "Artists"
        elif metdata_items[0]['metadata_type'] == 9:
            foldername = "Albums"
        else:
            ret['msg'] = f"지원하지 않는 메타 타입입니다. {metdata_items[0]['metadata_type']}"
            return ret
        metapath = os.path.join(metapath, foldername, metdata_items[0]['hash'][0], f"{metdata_items[0]['hash'][1:]}.bundle")
        
        if metapath:
            if os.path.exists(metapath):
                ret['metapath'] = metapath
                logger.info(f"메타패스 EXIST : {metapath}")
                if DRYRUN == False:
                    shutil.rmtree(metapath)
            else:
                logger.info(f"메타패스 NOT EXIST : {metapath} ")
        ret['metapath'] = metapath

        query = f"SELECT id FROM media_items WHERE metadata_item_id in ({','.join(metdata_items_ids_query)})"
        media_items = PlexDBHandle.select(query)
        media_items_ids = [ x['id']  for x in media_items ]
        media_items_ids_query = [ str(x['id'])  for x in media_items ]
        logger.info(f"media_items - id : {media_items_ids}")
        ret['media_items'] = len(media_items)

        query = f"SELECT id, hash, file FROM media_parts WHERE media_item_id in ({','.join(media_items_ids_query)})"
        media_parts = PlexDBHandle.select(query)
        media_parts_ids = [ x['id']  for x in media_parts ]
        media_parts_ids_query = [ str(x['id'])  for x in media_parts ]
        logger.info(f"media_parts - id : {media_parts_ids}")
        ret['media_parts'] = len(media_parts)
        
        if ret['media_parts'] > 0:
            ret['media_folder'] = []
            MEDIAPATH = P.ModelSetting.get('base_path_media')
            for media_part in media_parts:
                mediapath = os.path.join(MEDIAPATH, 'localhost', media_part['hash'][0], f"{media_part['hash'][1:]}.bundle")
                if os.path.exists(mediapath):
                    logger.info(f"미디어패스 EXIST : {mediapath}")
                    ret['media_folder'].append(mediapath)
                    if DRYRUN == False:
                        shutil.rmtree(mediapath)
                else:
                    logger.info(f"미디어패스 NOT EXIST : {mediapath} ")

            media_file = media_parts[0]['file']
            logger.info(media_file)
            folodername = os.path.basename(os.path.dirname(media_file))
            folodername = folodername.replace("'", "''")
            
            delete_query += f"DELETE FROM directories WHERE library_section_id = {library_section_id} AND parent_directory_id in (SELECT id FROM directories WHERE path LIKE '%{folodername}' AND library_section_id = {library_section_id});"
            delete_query += f"DELETE FROM directories WHERE path LIKE '%{folodername}' AND library_section_id = {library_section_id};"

            # media_streams
            delete_query += f"DELETE FROM media_streams WHERE media_part_id in ({','.join(media_parts_ids_query)});"
            delete_query += f"DELETE FROM media_parts WHERE media_item_id in ({','.join(media_items_ids_query)});"
        delete_query += f"DELETE FROM media_items WHERE metadata_item_id in ({','.join(metdata_items_ids_query)});"
        delete_query += f"DELETE FROM tags WHERE id in (SELECT tag_id FROM taggings WHERE metadata_item_id in ({','.join(metdata_items_ids_query)}));"
        delete_query += f"DELETE FROM taggings WHERE metadata_item_id in ({','.join(metdata_items_ids_query)});"
        delete_query += f"DELETE FROM metadata_items WHERE id in ({','.join(metdata_items_ids_query)});"
            
        if DRYRUN == False:
            query_ret = PlexDBHandle.execute_query(delete_query)
            logger.info(query_ret)
        ret['msg'] = "정상 삭제하였습니다."
        return ret


    def fix_yamlmusic(self):
        DRYRUN = False
        UPDATE_QUERY_COUNT = 1000

        prefix = "http://127.0.0.1:32400/:/plugins/com.plexapp.agents.sjva_agent/function/yaml_lyric?"

        query = f"""SELECT metadata_items.id as track_id, metadata_items.parent_id AS album_id, media_streams.id AS stream_id, media_streams.URL as URL
    FROM library_sections, metadata_items, media_items, media_parts, media_streams
    WHERE library_sections.id=metadata_items.library_section_id 
        AND metadata_items.id = media_items.metadata_item_id 
        AND media_items.id = media_parts.media_item_id 
        AND media_streams.media_part_id = media_parts.id
        AND (media_streams.codec = 'lrc' OR media_streams.codec = 'txt')
        AND metadata_items.metadata_type = 10
        AND media_streams.url LIKE "{prefix}%"
        ORDER BY track_id
    """
        #AND metadata_items.id = 210398
        # http://127.0.0.1:32400/:/plugins/com.plexapp.agents.sjva_agent/function/yaml_lyric?track_key=309952&lyric_index=0&album_key=309944&track_code=&disc_index=1&track_index=8
        
        prefix = "http://127.0.0.1:32400/:/plugins/com.plexapp.agents.sjva_agent/function/yaml_lyric?"
        regex = r"^track_key=(?P<track_key>\d+)&lyric_index=(?P<lyric_index>\d+)&album_key=(?P<album_key>\d+)&track_code=&disc_index=(?P<disc_index>\d+)&track_index=(?P<track_index>\d+)$"
        rows = PlexDBHandle.select(query)
        ret = {'가사정보수': len(rows), "정규식불일치":0, "정상정보":0, "수정정보":0}
        logger.info(f"가사정보 총: {ret['가사정보수']}건")
        query = []
        for idx, item in enumerate(rows):
            #logger.debug(item)
            
            match = re.match(regex, item['URL'].replace(prefix,''))
            if match:
                if item['track_id'] == int(match.group('track_key')) and item['album_id'] == int(match.group('album_key')):
                    ret['정상정보'] += 1
                else:
                    ret['수정정보'] += 1
                    #logger.debug(item)
                    newurl = f"{prefix}track_key={item['track_id']}&lyric_index={match.group('lyric_index')}&album_key={item['album_id']}&track_code=&disc_index={match.group('disc_index')}&track_index={match.group('track_index')}"
                    stream_id = item['stream_id']
                    query.append(f'UPDATE media_streams SET url = "{newurl}" WHERE id = {stream_id};')

                    if DRYRUN == False and len(query)>0 and len(query) % UPDATE_QUERY_COUNT == 0:
                        update_result = PlexDBHandle.execute_query(''.join(query))
                        logger.info(f"{idx} 업데이트: {d(update_result)}")
                        query = []
                        #break

            else:
                ret['정규식불일치'] += 1
                logger.debug(d(item))

        if DRYRUN == False and len(query)>0:
            update_result = PlexDBHandle.execute_query(''.join(query))
            logger.info(f"last 업데이트: {d(update_result)}")
            query = []

        logger.info(d(ret))

        ret['msg'] = f"총 {ret['가사정보수']}건 중 정상정보 {ret['정상정보']} 건, 수정정보 {ret['수정정보']}건."
        return ret


    def task_interface(self, mainfunc):
        def func():
            time.sleep(1)
            self.task_interface2(mainfunc)
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()
    
    def task_interface2(self, mainfunc):
        #ret = self.start_celery(mainfunc, None, *())
        ret = mainfunc()
        msg = ret['msg']
        F.socketio.emit("modal", {'title':'DB Tool', 'data' : msg}, namespace='/framework')

    

    def remove_db_by_folder(self, folderpath, delete_grand_parent=True):
        
        section = PlexDBHandle.get_section_info_by_filepath(folderpath)

        if section['section_type'] == 8:
            delete_grand_parent = False
        for base, dirs, files in os.walk(folderpath): 
            for filename in files:
                filepath = os.path.join(base, filename)

                self.remove_db_by_file(filepath, delete_grand_parent=delete_grand_parent)

        tmp = os.path.basename(folderpath)

        
        
        #tmp = tmp.replace('&', '\\&')
        query = f"""DELETE FROM directories WHERE library_section_id = {section['section_id']} and (path LIKE "{tmp}%" or path LIKE "%{tmp}");"""
        query_ret = PlexDBHandle.execute_query(query)

        logger.info(query)

        return {'msg':'삭제하였습니다.'}


    def remove_db_by_file(self, filepath, delete_grand_parent=True):
        #filepath = filepath.replace('&', '\\&')
        query = f"""DELETE FROM media_streams WHERE media_part_id in (SELECT id FROM media_parts WHERE file = "{filepath}");"""
        if delete_grand_parent:
            query += f"""DELETE FROM metadata_items WHERE id in (SELECT parent_id FROM metadata_items WHERE id in (SELECT parent_id FROM metadata_items WHERE id in (SELECT metadata_item_id FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}"))));"""
        query += f"""
DELETE FROM metadata_items WHERE id in (SELECT parent_id FROM metadata_items WHERE id in (SELECT metadata_item_id FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}")));
DELETE FROM metadata_items WHERE id in (SELECT metadata_item_id FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}"));
DELETE FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}");
DELETE FROM media_parts WHERE file = "{filepath}";
DELETE FROM tags WHERE id in (SELECT tag_id FROM taggings WHERE metadata_item_id in (SELECT metadata_item_id FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}")));
DELETE FROM taggings WHERE metadata_item_id in (SELECT metadata_item_id FROM media_items WHERE id in (SELECT media_item_id FROM media_parts WHERE file = "{filepath}"));
"""
        
        query_ret = PlexDBHandle.execute_query(query)
