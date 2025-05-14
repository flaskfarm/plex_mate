import sqlite3
import urllib
from datetime import datetime

from support import SupportFile

from .plex_db import PlexDBHandle, dict_factory
from .setup import *

INSERT_ROWS = 10000

logger = P.logger


class Task(object):

    source_con = source_cur = None
    target_con = target_cur = None
    change_rule = None
    change_rule_extra = None
    SOURCE_SECTION_ID = None
    SOURCE_LOCATIONS = None
    TARGET_SECTION_ID = None
    TARGET_LOCATIONS = None
    config = None
    copy_info = {}
    copy_result = {}

    @staticmethod
    @F.celery.task(bind=True)
    def start(self, *args):
        try:
            start_dt = datetime.now()
            Task.celery_instance = self
            Task.config = P.load_config()
            Task.change_rule = [P.ModelSetting.get('copy2_copy_path_source_root_path'), P.ModelSetting.get('copy2_copy_path_target_root_path')]
            Task.file_change_rule = [P.ModelSetting.get('copy2_copy_path_source_root_path').replace(' ', '%20'), P.ModelSetting.get('copy2_copy_path_target_root_path').replace(' ', '%20')]

            Task.source_con = sqlite3.connect(P.ModelSetting.get('copy2_copy_path_source_db'))
            Task.source_cur = Task.source_con.cursor()
            Task.target_con = sqlite3.connect(P.ModelSetting.get('base_path_db'))
            Task.target_cur = Task.target_con.cursor()

            func_list = [
                Task.STEP1_library_sections,
                Task.STEP2_section_locations,
                Task.STEP3_directories,
                Task.STEP4_metadata_items,
                Task.STEP5_media_items,
                Task.STEP6_media_parts,
                Task.STEP7_media_streams,
                Task.STEP8_tags,
                Task.STEP9_taggings,
            ]
            
            for func in func_list:
                func()
                if P.ModelSetting.get_bool('copy2_status_task_stop_flag'): return 'stop'
                
            end_dt = datetime.now()
            
            Task.message("")
            Task.message(f"종료: {end_dt-start_dt}")
            logger.info(d(Task.copy_info))
            logger.info(d(Task.copy_result))
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
        finally:
            if Task.source_cur is not None:
                Task.source_cur.close()
            if Task.source_con is not None:
                Task.source_con.close()
            if Task.target_cur is not None:
                Task.target_cur.close()
            if Task.target_con is not None:
                Task.target_con.close()
            return "wait"

    def 유틸_경로변환(source_path):
        if Task.change_rule[1] == '':
            return source_path
        target_path = source_path.replace(Task.change_rule[0], Task.change_rule[1])
        if Task.change_rule[1][0] != '/': #windows
            target_path = target_path.replace('/', '\\')
        return target_path
    

    def get_id_value(conn, table, kind):
        query = f"SELECT {kind}(id) as ret FROM {table};"
        ce = conn.execute(query)
        ce.row_factory = dict_factory
        data = ce.fetchall()
        if data[0]['ret'] == None:
            return 0
        return data[0]['ret']



    def STEP1_library_sections():
        Task.message(f"STEP 1/9 : library_sections")
        ce = Task.source_con.execute('SELECT * FROM library_sections')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        insert_col = ''
        insert_value = ''
        if P.ModelSetting.get_bool('copy2_copy_section_id_user'):
            val = P.ModelSetting.get_int('copy2_copy_section_id')
            rows = PlexDBHandle.select(f"SELECT * FROM library_sections WHERE id = {val}")
            if len(rows) != 0:
                Task.message(f"에러: {val} 섹션 ID가 이미 있습니다.")
                raise Exception(f'')
            insert_col += "'id',"
            insert_value += f"{val},"
        for key, value in data[0].items():
            if key in ['id']:
                continue
            if value is None:
                continue
            insert_col += f"'{key}',"
            if type(value) == type(''):
                value = value.replace('"', '""')
                insert_value += f'"{value}",'
            else:
                insert_value += f"{value},"
            if key == 'section_type':
                Task.copy_info['section_type'] = value
        insert_col = insert_col.rstrip(',')
        insert_value = insert_value.rstrip(',')
        query = f"INSERT INTO library_sections ({insert_col}) VALUES ({insert_value});SELECT max(id) FROM library_sections;" 
        ret = PlexDBHandle.execute_query(query)
        if P.ModelSetting.get_bool('copy2_copy_section_id_user'):
            Task.copy_info['library_sections_id'] = int(P.ModelSetting.get_int('copy2_copy_section_id'))
        else:
            if ret != '':
                Task.copy_info['library_sections_id'] = int(ret)
        Task.message(f"--- 섹션 ID: {Task.copy_info['library_sections_id']}")
        Task.target_con.commit()


    def STEP2_section_locations():
        TABLE = "section_locations"
        Task.message("")
        Task.message(f"STEP 2/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'library_section_id':
                    value = Task.copy_info['library_sections_id']
                elif key == 'root_path':
                    value = Task.유틸_경로변환(value)
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});" 

        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 2: {ret}')
        logger.info(f"INSERT 2 {TABLE}") 
        #Task.target_con.commit()
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP3_directories():
        TABLE = "directories"
        Task.message("")
        Task.message(f"STEP 3/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            if row['deleted_at'] != None:
                continue
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'parent_directory_id' and value != None:
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'library_section_id':
                    value = Task.copy_info['library_sections_id']
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 3: {ret}')
                #logger.info(f"INSERT 3 {TABLE}: {count}")
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 3: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")

    def STEP4_metadata_items():
        TABLE = "metadata_items"
        Task.message("")
        Task.message(f"STEP 4/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            if row['deleted_at'] != None:
                continue
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'parent_id' and value != None:
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'library_section_id':
                    value = Task.copy_info['library_sections_id']
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 4: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 4: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP5_media_items():
        TABLE = "media_items"
        Task.message("")
        Task.message(f"STEP 5/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            if row['deleted_at'] != None:
                continue
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'library_section_id':
                    value = Task.copy_info['library_sections_id']
                elif key == 'section_location_id' and value != None:
                    value = value - Task.copy_info[f'diff_section_locations']
                elif key == 'metadata_item_id' and value != None:
                    value = value - Task.copy_info[f'diff_metadata_items']
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 5: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 5: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP6_media_parts():
        TABLE = "media_parts"
        Task.message("")
        Task.message(f"STEP 6/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            if row['deleted_at'] != None:
                continue
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'media_item_id' and value != None:
                    value = value - Task.copy_info[f'diff_media_items']
                elif key == 'directory_id' and value != None:
                    value = value - Task.copy_info[f'diff_directories']
                elif key == 'file':
                    value = Task.유틸_경로변환(value)
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 6: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 6: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP7_media_streams():
        TABLE = "media_streams"
        Task.message("")
        Task.message(f"STEP 7/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'media_item_id' and value != None:
                    value = value - Task.copy_info[f'diff_media_items']
                elif key == 'media_part_id' and value != None:
                    value = value - Task.copy_info[f'diff_media_parts']
                elif key == 'url':
                    if value != '' and value.startswith('file'):
                        value = value.replace(Task.file_change_rule[0], Task.file_change_rule[1])
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 7: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 7: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP8_tags():
        TABLE = "tags"
        Task.message("")
        Task.message(f"STEP 8/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'metadata_item_id' and value != None:
                    value = value - Task.copy_info[f'diff_metadata_items']
                elif key == 'parent_id' and value != None:
                    value = value - Task.copy_info[f'diff_{TABLE}']
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 8: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 8: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")


    def STEP9_taggings():
        TABLE = "taggings"
        Task.message("")
        Task.message(f"STEP 9/9 : {TABLE}")
        min_source = Task.get_id_value(Task.source_con, TABLE, 'min')
        max_target = Task.get_id_value(Task.target_con, TABLE, 'max')
        Task.copy_info[f'diff_{TABLE}'] = min_source - (max_target + 1)

        query = ''
        ce = Task.source_con.execute(f'SELECT * FROM {TABLE} ORDER BY id')
        ce.row_factory = dict_factory
        data = ce.fetchall()
        logger.info(f"{TABLE} rows = {len(data)}")
        count = 0
        Task.message(f" --- 소스: {len(data)} 개")
        for row in data:
            insert_col = ''
            insert_value = ''
            for key, value in row.items():
                if key == 'id':
                    value = value - Task.copy_info[f'diff_{TABLE}']
                elif key == 'metadata_item_id' and value != None:
                    value = value - Task.copy_info[f'diff_metadata_items']
                elif key == 'tag_id' and value != None:
                    value = value - Task.copy_info[f'diff_tags']
                if value is None:
                    continue
                insert_col += f"'{key}',"
                if type(value) == type(''):
                    value = value.replace('"', '""')
                    insert_value += f'"{value}",'
                else:
                    insert_value += f"{value},"
            insert_col = insert_col.rstrip(',')
            insert_value = insert_value.rstrip(',')
            query += f"INSERT INTO {TABLE} ({insert_col}) VALUES ({insert_value});"
            count += 1
            if count % INSERT_ROWS == 0:
                ret = PlexDBHandle.execute_query(query)
                if ret:
                    logger.warning(f'Step 9: {ret}')
                Task.message(f" --- 추가: {count} / {len(data)}")
                query = ""
        ret = PlexDBHandle.execute_query(query)
        if ret:
            logger.warning(f'Step 9: {ret}')
        Task.copy_result[TABLE] = len(data)
        Task.message(f" --- 추가: {Task.copy_result[TABLE]} / {len(data)}")



    def message(msg):
        logger.debug(msg)
        if F.config['use_celery']:
            Task.celery_instance.update_state(state='PROGRESS', meta=msg)
        else:
            Task.celery_instance.receive_from_task(msg, celery=False)








