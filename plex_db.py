import platform
import sqlite3

from support import SupportFile, SupportSubprocess, d

from .setup import *


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class PlexDBHandle(object):
    
    @classmethod
    def library_sections(cls, db_file=None, section_type=None):
        try:
            if db_file is None:
                db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()
            if section_type is None:
                ce = con.execute('SELECT * FROM library_sections ORDER BY name, created_at')
            else:
                ce = con.execute('SELECT * FROM library_sections WHERE section_type = ? ORDER BY name, created_at', (section_type,))
            ce.row_factory = dict_factory
            data = ce.fetchall()
            con.close()
            return data
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())

    @classmethod
    def library_section(cls, library_id, db_file=None):
        try:
            library_id = int(library_id)
            if db_file is None:
                db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()
            ce = con.execute('SELECT * FROM library_sections WHERE id = ?', (library_id,))
            ce.row_factory = dict_factory
            data = ce.fetchone()
            con.close()
            return data
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())

    """
    @classmethod
    def execute_query(cls, sql, sql_filepath=None):
        try:
            sql += f"{sql}\ncommit;"
            if sql_filepath is None:
                sql_filepath = os.path.join(path_data, 'tmp', f"{str(time.time()).split('.')[0]}.sql")
            SupportFile.write_file(sql, sql_filepath)
            if platform.system() == 'Windows':
                tmp = sql_filepath.replace('\\', '\\\\')
                cmd = f'"{P.ModelSetting.get("base_bin_sqlite")}" "{P.ModelSetting.get("base_path_db")}" ".read {tmp}"'
                SupportSubprocess.execute_command_return(cmd)
            else:
                ret = SupportSubprocess.execute_command_return([P.ModelSetting.get('base_bin_sqlite'), P.ModelSetting.get('base_path_db'), f".read {sql_filepath}"])
                #logger.warning(ret)
            return True
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        return False   
    """

    @classmethod
    def execute_query(cls, sql, sql_filepath=None):
        try:
            if sql_filepath is None:
                sql_filepath = os.path.join(F.config['path_data'], 'tmp', f"{str(time.time()).split('.')[0]}.sql")
            SupportFile.write_file(sql_filepath, sql)
            if platform.system() == 'Windows':
                sql_filepath = sql_filepath.replace('\\', '\\\\')
            cmd = [P.ModelSetting.get("base_bin_sqlite"), P.ModelSetting.get("base_path_db"), f".read {sql_filepath}"]
            for i in range(10):
                ret = SupportSubprocess.execute_command_return(cmd)
                P.logger.info(ret)
                if ret['log'].find('database is locked') != -1:
                    time.sleep(5)
                else:
                    break
            return ret['log']
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        return False



    @classmethod
    def execute_query_with_db_filepath(cls, sql, db_filepath):
        try:
            sql_filepath = os.path.join(F.config['path_data'], 'tmp', f"{str(time.time()).split('.')[0]}.sql")
            SupportFile.write_file(sql_filepath, sql)
            last_sql_filepath = sql_filepath
            if platform.system() == 'Windows':
                last_sql_filepath = sql_filepath.replace('\\', '\\\\')
            
            cmd = [P.ModelSetting.get('base_bin_sqlite'), db_filepath, f".read {last_sql_filepath}"]
            for i in range(10):
                ret = SupportSubprocess.execute_command_return(cmd)
                if ret['log'].find('database is locked') != -1:
                    time.sleep(5)
                else:
                    break
            return ret
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        return '' 


    @classmethod
    def select(cls, query, db_file=None):
        try:
            if db_file is None:
                db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()
            ce = con.execute(query)
            ce.row_factory = dict_factory
            data = ce.fetchall()
            con.close()
            return data

        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        return   

    
    
    @classmethod
    def select_arg(cls, query, args, db_file=None):
        try:
            if db_file is None:
                db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()
            #logger.error(args)
            if args is None or len(args) == 0:
                ce = con.execute(query)
            else:
                ce = con.execute(query, args)
            ce.row_factory = dict_factory
            data = ce.fetchall()
            con.close()
            return data

        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            pass
        return

        
    @classmethod
    def tool_select(cls, where, db_file=None):
        con = cur = None
        try:
            if db_file is None:
                db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()

            query = """
            SELECT 
                metadata_items.id AS metadata_items_id, 
                metadata_items.library_section_id AS library_section_id, 
                metadata_items.metadata_type AS metadata_type, 
                metadata_items.guid AS guid,
                metadata_items.media_item_count AS media_item_count,
                metadata_items.title AS title,
                metadata_items.year AS year,
                metadata_items.'index' AS metadata_items_index,
                metadata_items.user_thumb_url AS user_thumb_url,
                metadata_items.user_art_url AS user_art_url,
                metadata_items.hash AS metadata_items_hash,
                media_items.id AS media_items_id,
                media_items.section_location_id AS section_location_id,
                media_items.width AS width,
                media_items.height AS height,
                media_items.size AS size,
                media_items.duration AS duration,
                media_items.bitrate AS bitrate,
                media_items.container AS container,
                media_items.video_codec AS video_codec,
                media_items.audio_codec AS audio_codec,
                media_parts.id AS media_parts_id,
                media_parts.directory_id AS media_parts_directory_id,
                media_parts.hash AS media_parts_hash,
                media_parts.file AS file
            FROM metadata_items, media_items, media_parts 
            WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id """
            if where is not None and where != '':
                query = query + ' AND (' + where + ') '
            query += ' LIMIT 100'


            #logger.warning(query)

            ce = con.execute(query)
            ce.row_factory = dict_factory
            data = ce.fetchall()
            cur.close
            con.close()
            cur = con = None
            return {'ret':'success', 'data':data}

        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            return {'ret':'exception', 'log':str(e)}
        finally:
            if cur is not None:
                cur.close()
            if con is not None:
                con.close()   


    @classmethod
    def section_location(cls, db_file=None, library_id=None):
        if library_id == None:
            query = """SELECT library_sections.id as section_id, name, section_type, root_path  FROM library_sections, section_locations WHERE library_sections.id == section_locations.library_section_id ORDER BY library_sections.id"""
        else:
            query = f"""SELECT library_sections.id as section_id, name, section_type, root_path  FROM library_sections, section_locations WHERE library_sections.id == section_locations.library_section_id AND library_sections.id = {library_id} ORDER BY library_sections.id"""
        return cls.select(query, db_file=db_file)


    @classmethod
    def get_section_info_by_filepath(cls, filepath):
        P.logger.warning(filepath)
        for location in cls.section_location():
            #P.logger.info(d(location))
            if location['root_path'] in filepath:
                return location
    
    
    @classmethod
    def get_media_parts(cls, file):
        return PlexDBHandle.select_arg("SELECT id FROM media_parts WHERE file = ?", (file,))
    
    @classmethod
    def get_media_parts_file_like(cls, file):
        sql = "SELECT file FROM media_parts WHERE file LIKE '%" + file + "%'"
        logger.error(sql)
        return PlexDBHandle.select(sql)
        
    
    @classmethod
    def get_info_by_part_id(cls, part_id):
        return PlexDBHandle.select_arg("SELECT * FROM library_sections, metadata_items, media_items, media_parts WHERE library_sections.id=metadata_items.library_section_id AND metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND media_parts.id = ?", (part_id,))


    #SELECT * FROM library_sections, metadata_items, media_items WHERE library_sections.id=metadata_items.library_section_id AND metadata_items.id = media_items.metadata_item_id AND media_items.id = 2088
    
    @classmethod
    def update_show_recent(cls):
        return PlexDBHandle.execute_query("UPDATE metadata_items SET added_at = (SELECT max(added_at) FROM metadata_items mi WHERE mi.parent_id = metadata_items.id OR mi.parent_id IN(SELECT id FROM metadata_items mi2 WHERE mi2.parent_id = metadata_items.id)) WHERE metadata_type = 2;")


    # 폴더에서 영화와 쇼 메타 키를 구한다. 이 키를 가지고 스캔
    @classmethod
    def get_metaid_by_directory(cls, section_id, directory):
        section_info = cls.library_section(section_id)
        #P.logger.error(section_info)
        query = """
            SELECT 
                metadata_items.id AS metadata_items_id, 
				metadata_items.parent_id,
                metadata_items.library_section_id AS library_section_id, 
                metadata_items.metadata_type AS metadata_type, 
                media_items.id AS media_items_id,
                media_parts.id AS media_parts_id,
                media_parts.directory_id AS media_parts_directory_id,
                media_parts.file AS file
            FROM metadata_items, media_items, media_parts 
            WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND metadata_items.library_section_id = """
        query += str(section_id) + " AND file LIKE '" + directory + "%'"
        data = cls.select(query)

        #P.logger.error(data)

        if section_info['section_type'] == 1:
            if len(data) == 1:
                return data[0]['metadata_items_id']
            else:
                P.logger.error(d(data))
                P.logger.error('에러 확인할것')
        elif section_info['section_type'] == 2:
            if len(data) > 0:
                parent_id = data[0]['parent_id']
                query = """
                    SELECT id, parent_id
                    FROM metadata_items 
                    WHERE id = """
                query += str(parent_id)
                data2 = cls.select(query)
                return data2[0]['parent_id']
            else:
                P.logger.error(d(data))
                P.logger.error('에러 확인할것')
    