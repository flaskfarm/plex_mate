import shutil

from tool import ToolUtil

from .plex_db import PlexDBHandle
from .setup import *


class PageCopyMake(PluginPageBase):
    def __init__(self, P, parent):
        super(PageCopyMake, self).__init__(P, parent, name='make')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_path_create' : '{PATH_DATA}' + os.sep + P.package_name,
            f'{self.parent.name}_{self.name}_section_id' : '',
        }
    
    def process_menu(self, req):
        arg = P.ModelSetting.to_dict()
        arg['library_list'] = PlexDBHandle.library_sections()
        arg[f'{self.parent.name}_{self.name}_path_create'] = ToolUtil.make_path(P.ModelSetting.get(f'{self.parent.name}_{self.name}_path_create'))
        return render_template(f'{P.package_name}_{self.parent.name}_{self.name}.html', arg=arg)


    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command.startswith('start'):
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_path_create', arg1)
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_section_id', arg2)
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_include_info_xml', 'True' if (arg3=='true') else 'False')
                self.task_interface()
                ret['msg'] = f"작업을 시작합니다.<br>완료시 팝업 창이 나타납니다."
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})
    


    #########################################################
    def task_interface(self):
        def func():
            time.sleep(1)
            self.task_interface2()
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()

    def task_interface2(self):
        func = self.start
        ret = self.start_celery(func, None, *())
        msg = f"{ret}<br>파일 생성을 완료하였습니다."
        F.socketio.emit("modal", {'title':'DB 생성 완료', 'data' : msg}, namespace='/framework', to='all')


    @staticmethod
    @F.celery.task
    def start():
        try:
            db_folderpath = ToolUtil.make_path(P.ModelSetting.get('copy_make_path_create'))
            os.makedirs(db_folderpath, exist_ok=True)
            section_id = P.ModelSetting.get(f'copy_make_section_id')
            section = PlexDBHandle.library_section(section_id)

            tmp = PlexDBHandle.select(f"SELECT count(*) as cnt FROM metadata_items WHERE metadata_type = {section['section_type']} AND library_section_id = {section['id']}")
            count = tmp[0]['cnt']

            P.logger.error(tmp)

            db_path = P.ModelSetting.get(f'base_path_db')
            if os.path.exists(db_path):
                basename = os.path.basename(db_path)
                tmp = os.path.splitext(basename)
                newfilename = f"{section['name']}_{count}_{datetime.now().strftime('%Y%m%d_%H%M')}{tmp[1]}"
                newpath = os.path.join(db_folderpath, newfilename)
                shutil.copy(db_path, newpath)
            logger.debug(f"파일 : {newpath}")
            
            logger.warning("쿼리 실행 시작")
            query = '''
DROP TABLE metadata_relations;
DROP TABLE accounts;
DROP TABLE activities;
DROP TABLE blobs;
DROP TABLE cloudsync_files;
DROP TABLE devices;
DROP TABLE external_metadata_items;
DROP TABLE external_metadata_sources;
DROP TABLE fts4_metadata_titles;
DROP TABLE fts4_tag_titles;
DROP TABLE fts4_metadata_titles_icu;
DROP TABLE fts4_tag_titles_icu;
DROP TABLE hub_templates;
DROP TABLE locations;
DROP TABLE hub_templates;
DROP TABLE library_section_permissions;
DROP TABLE library_timeline_entries;
DROP TABLE locatables;
DROP TABLE location_places;
DROP TABLE media_grabs;
DROP TABLE media_item_settings;
DROP TABLE media_metadata_mappings;
DROP TABLE media_part_settings;
DROP TABLE media_provider_resources;
DROP TABLE media_stream_settings;
DROP TABLE media_subscriptions;
DROP TABLE metadata_item_accounts;
DROP TABLE metadata_item_clusterings;
DROP TABLE metadata_item_clusters;
DROP TABLE metadata_item_settings;
DROP TABLE metadata_item_views;
DROP TABLE metadata_subscription_desired_items;
DROP TABLE play_queue_generators;
DROP TABLE play_queue_items;
DROP TABLE play_queues;
DROP TABLE plugin_permissions;
DROP TABLE plugin_prefixes;
DROP TABLE plugins;
DROP TABLE preferences;
DROP TABLE remote_id_translation;
DROP TABLE schema_migrations;
DROP TABLE spellfix_metadata_titles;
DROP TABLE spellfix_tag_titles;
DROP TABLE sqlite_sequence;
DROP TABLE sqlite_stat1;
DROP TABLE statistics_bandwidth;
DROP TABLE statistics_media;
DROP TABLE statistics_resources;
DROP TABLE stream_types;
DROP TABLE sync_schema_versions;
DROP TABLE synced_ancestor_items;
DROP TABLE synced_library_sections;
DROP TABLE synced_metadata_items;
DROP TABLE synced_play_queue_generators;
DROP TABLE synchronization_files;
DROP TABLE versioned_metadata_items;
DROP TABLE view_settings;
DROP TABLE custom_channels;
DROP TABLE metadata_agent_providers;
DROP TABLE metadata_item_setting_markers;
DROP INDEX index_directories_on_deleted_at;
DROP INDEX index_directories_on_parent_directory_id;
DROP INDEX index_directories_on_path;
DROP INDEX index_media_items_on_begins_at;
DROP INDEX index_media_items_on_channel_id;
DROP INDEX index_media_items_on_channel_id_and_begins_at;
DROP INDEX index_media_items_on_deleted_at;
DROP INDEX index_media_items_on_ends_at;
DROP INDEX index_media_items_on_library_section_id;
DROP INDEX index_media_items_on_media_analysis_version;
DROP INDEX index_media_items_on_metadata_item_id;
DROP INDEX index_media_parts_on_deleted_at;
DROP INDEX index_media_parts_on_directory_id;
DROP INDEX index_media_parts_on_file;
DROP INDEX index_media_parts_on_hash;
DROP INDEX index_media_parts_on_media_item_id;
DROP INDEX index_media_parts_on_size;
DROP INDEX index_media_streams_on_language;
DROP INDEX index_media_streams_on_media_item_id;
DROP INDEX index_media_streams_on_media_part_id;
DROP INDEX index_metadata_items_on_absolute_index;
DROP INDEX index_metadata_items_on_added_at;
DROP INDEX index_metadata_items_on_changed_at;
DROP INDEX index_metadata_items_on_created_at;
DROP INDEX index_metadata_items_on_deleted_at;
DROP INDEX index_metadata_items_on_guid;
DROP INDEX index_metadata_items_on_hash;
DROP INDEX index_metadata_items_on_index;
DROP INDEX index_metadata_items_on_library_section_id;
DROP INDEX index_metadata_items_on_library_section_id_and_metadata_type_and_added_at;
DROP INDEX index_metadata_items_on_metadata_type;
DROP INDEX index_metadata_items_on_original_title;
DROP INDEX index_metadata_items_on_originally_available_at;
DROP INDEX index_metadata_items_on_parent_id;
DROP INDEX index_metadata_items_on_remote;
DROP INDEX index_metadata_items_on_resources_changed_at;
DROP INDEX index_metadata_items_on_title;
DROP INDEX index_metadata_items_on_title_sort;
DROP INDEX index_title_sort_icu;
DROP INDEX index_library_sections_on_changed_at;
DROP INDEX index_library_sections_on_name;
DROP INDEX index_library_sections_on_name_sort;
DROP INDEX index_taggings_on_metadata_item_id;
DROP INDEX index_taggings_on_tag_id;
DROP INDEX index_tags_on_key;
DROP INDEX index_tags_on_parent_id;
DROP INDEX index_tags_on_tag;
DROP INDEX index_tags_on_tag_type;
DROP INDEX index_tags_on_tag_type_and_tag;
DROP INDEX index_metadata_agent_providers_on_identifier;
DROP INDEX index_metadata_agent_providers_on_online;
DROP INDEX index_metadata_agent_providers_on_uri;
DROP INDEX index_metadata_item_setting_markers_on_metadata_item_setting_id;
DROP INDEX index_metadata_item_setting_markers_on_updated_at;
DROP INDEX index_metadata_items_on_edition_title;
DROP INDEX index_metadata_agent_providers_on_identifier;
DROP INDEX index_metadata_items_on_slug;
DROP TRIGGER fts4_metadata_titles_after_insert_icu;
DROP TRIGGER fts4_metadata_titles_after_update_icu;
DROP TRIGGER fts4_metadata_titles_before_delete_icu;
DROP TRIGGER fts4_metadata_titles_before_update_icu;
DROP TRIGGER fts4_tag_titles_after_insert_icu;
DROP TRIGGER fts4_tag_titles_after_update_icu;
DROP TRIGGER fts4_tag_titles_before_delete_icu;
DROP TRIGGER fts4_tag_titles_before_update_icu;
VACUUM;
'''
            PlexDBHandle.execute_query_with_db_filepath(query, newpath)
            query = f'''
DELETE FROM library_sections WHERE id is null OR id != {section_id};
'''
            if section['section_type'] == 1:
                query += f'''
DELETE FROM metadata_items WHERE not (library_section_id = {section_id} AND metadata_type = 1);'''
            elif section['section_type'] == 2:
                query += f'''
DELETE FROM metadata_items WHERE not (library_section_id = {section_id} AND metadata_type BETWEEN 2 AND 4);'''
            elif section['section_type'] == 8:
                query += f'''
DELETE FROM metadata_items WHERE not (library_section_id = {section_id} AND metadata_type BETWEEN 8 AND 10);'''
            query += f'''
DELETE FROM metadata_items WHERE parent_id is not null and parent_id not in (SELECT id FROM metadata_items WHERE library_section_id = {section_id});            
DELETE FROM section_locations WHERE library_section_id is null OR library_section_id != {section_id};
DELETE FROM directories WHERE library_section_id is null OR library_section_id != {section_id};
DELETE FROM media_items WHERE library_section_id is null OR library_section_id != {section_id};
DELETE FROM media_items WHERE metadata_item_id is not null and metadata_item_id not in (SELECT id FROM metadata_items WHERE library_section_id = {section_id});            
DELETE FROM media_items WHERE section_location_id not in (SELECT id FROM section_locations WHERE library_section_id = {section_id});            
DELETE FROM media_parts WHERE media_item_id is null OR media_item_id not in (SELECT id FROM media_items WHERE library_section_id = {section_id});
DELETE FROM media_parts WHERE directory_id is null OR directory_id not in (SELECT id FROM directories WHERE library_section_id = {section_id});
DELETE FROM media_streams WHERE media_item_id is null OR media_item_id not in (SELECT id FROM media_items WHERE library_section_id = {section_id});
DELETE FROM media_streams WHERE media_part_id not in (SELECT id FROM media_parts);
DELETE FROM taggings WHERE metadata_item_id not in (SELECT id FROM metadata_items);
DELETE FROM tags WHERE id not in (SELECT tag_id FROM taggings GROUP BY tag_id);
DELETE FROM taggings WHERE tag_id not in (SELECT id FROM tags);
VACUUM; 
            '''
            
            PlexDBHandle.execute_query_with_db_filepath(query, newpath)


            logger.warning("쿼리 실행 끝")
            if os.path.exists(newpath):
                try:
                    os.remove(newpath.replace('.db', '.db-shm'))
                    os.remove(newpath.replace('.db', '.db-wal'))
                except:
                    pass
            
            DBChangeOrder(newpath).start()
            return newpath
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        return

import sqlite3

from .plex_db import PlexDBHandle, dict_factory

INSERT_ROWS = 1000

class DBChangeOrder:
    table_list = [
        "library_sections",
        "section_locations",
        "directories",
        "metadata_items",
        "media_items",
        "media_parts",
        "media_streams",
        "tags",
        "taggings",
    ]

    def __init__(self, db_path):
        self.src_path = db_path
        self.tar_path = None
        self.idmap = {}
        self.current = {}
        for table in self.table_list:
            self.idmap[table] = {}
            self.current[table] = 0
    
    def start(self):
        try:
            empty_path = os.path.join(os.path.dirname(__file__), 'files', 'empty.db')
            self.tar_path = os.path.join(F.config['path_data'], 'tmp', 'empty.db')
            shutil.copy(empty_path, self.tar_path)

            self.source_con = sqlite3.connect(self.src_path)
            self.target_con = sqlite3.connect(self.tar_path)
            
            for table in self.table_list:
                ce = self.source_con.execute(f'SELECT * FROM {table} ORDER BY id')
                ce.row_factory = dict_factory
                data = ce.fetchall()
                logger.info(f"{table} rows = {len(data)}")
                count = 0
                query = ''
                after = []
                forlist = [data, after]
                for idx, _list in enumerate(forlist):
                    for row in _list:
                        rowcontinue = False
                        insert_col = ''
                        insert_value = ''
                        for key, value in row.items():
                            if key == 'id':
                                #logger.info(f"{key} {value}")
                                self.current[table] += 1
                                self.idmap[table][value] = self.current[table]
                                value = self.current[table]
                            elif key == 'library_section_id':
                                value = self.idmap['library_sections'][value]
                            elif key == 'parent_directory_id' and value != None:
                                if idx == 0 and value not in self.idmap['directories']:
                                    after.append(row)
                                    rowcontinue = True
                                    break
                                value = self.idmap['directories'][value] 
                            elif table == 'metadata_items' and key == 'parent_id' and value != None:
                                if idx == 0 and value not in self.idmap['metadata_items']:
                                    after.append(row)
                                    rowcontinue = True
                                    break
                                # 스캔이 잘못되어 있는 경우
                                #if idx == 1 and value not in self.idmap['metadata_items']:
                                #    rowcontinue = True
                                #    break
                                value = self.idmap['metadata_items'][value]
                            elif table == 'tags' and key == 'parent_id' and value != None:
                                value = self.idmap['tags'][value]
                            elif key == 'metadata_item_id' and value != None:
                                value = self.idmap['metadata_items'][value] 
                            elif key == 'section_location_id' and value != None:
                                value = self.idmap['section_locations'][value] 
                            elif key == 'media_item_id' and value != None:
                                value = self.idmap['media_items'][value] 
                            elif key == 'directory_id' and value != None:
                                value = self.idmap['directories'][value] 
                            elif key == 'media_part_id' and value != None:
                                value = self.idmap['media_parts'][value] 
                            elif key == 'tag_id' and value != None:
                                if value not in self.idmap['tags']:
                                    rowcontinue = True
                                    break
                                value = self.idmap['tags'][value] 
                            if value is None:
                                continue
                            insert_col += f"'{key}',"
                            if type(value) == type(''):
                                value = value.replace('"', '""')
                                insert_value += f'"{value}",'
                            else:
                                insert_value += f"{value},"
                        if rowcontinue:
                            continue
                        insert_col = insert_col.rstrip(',')
                        insert_value = insert_value.rstrip(',')
                        query = f"INSERT INTO {table} ({insert_col}) VALUES ({insert_value});"

                        self.target_con.execute(query)

                        count += 1

                        if count % 1000 == 0:
                            #PlexDBHandle.execute_query_with_db_filepath(query, self.tar_path)     
                            logger.info(f"INSERT {table}: {count} / {len(data)}")    
                            query = ""
                    
                self.target_con.commit()
            self.source_con.close()
            self.target_con.close()
            if os.path.exists(self.src_path):
                try:
                    os.remove(self.src_path.replace('.db', '.db-shm'))
                    os.remove(self.src_path.replace('.db', '.db-wal'))
                    os.remove(self.src_path)
                except:
                    pass
            shutil.move(self.tar_path, self.src_path)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            try:
                logger.error(d(row))
            except: pass
        finally:
            try:
                self.source_con.close()
                self.target_con.close()
            except:
                pass
            if os.path.exists(self.src_path):
                try:
                    os.remove(self.src_path.replace('.db', '.db-shm'))
                    os.remove(self.src_path.replace('.db', '.db-wal'))
                    os.remove(self.src_path)
                except:
                    pass