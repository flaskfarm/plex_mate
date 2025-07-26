import shutil
import threading
import time
import unicodedata
from support import SupportString, SupportYaml
from .plex_db import PlexDBHandle
import tmdbsimple as tmdb
from .setup import *
from datetime import datetime, timezone, timedelta
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
            f'{self.parent.name}_{self.name}_title_sort_types' : '1, 2, 8, 9',
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
            elif command == 'default_agent_meta_update':
                metadata_item_id = arg1
                try:
                    row = PlexDBHandle.select_arg(
                        "SELECT metadata_type FROM metadata_items WHERE id = ?",
                        (metadata_item_id,)
                    )
                    if not row:
                        ret['ret'] = 'fail'
                        ret['msg'] = f"metadata_item_id {metadata_item_id} 이 존재하지 않습니다."
                    elif row[0]['metadata_type'] not in (1, 2):
                        ret['ret'] = 'fail'
                        ret['msg'] = f"metadata_item_id {metadata_item_id} 의 metadata_type이 1(movie) 또는 2(show)가 아닙니다."
                    else:
                        result = self.update_by_default_agent_tmdb(metadata_item_id)
                        ret.update(result)
                except Exception as e:
                    logger.error(f"[MetaUpdate] 수동 메타 업데이트 중 예외: {e}")
                    ret['ret'] = 'fail'
                    ret['msg'] = f"예외 발생: {e}"
            elif command == 'tool_simple_title_sort':
                try:
                    section_id = int(arg1)
                except Exception:
                    msg = f'섹션 ID가 잘못되었습니다: {arg1}'
                    P.logger.exception(msg)
                    ret['ret'] = 'fail'
                    ret['msg'] = msg
                    return jsonify(ret)
                try:
                    type_strings = arg3.split(',')
                except Exception:
                    type_strings = P.ModelSetting.get(f'tool_simple_title_sort_types').split(',')
                types = []
                for metadata_type in type_strings:
                    try:
                        types.append(int(metadata_type))
                    except Exception:
                        P.logger.warning(f"메타 타입이 잘못되었습니다: {metadata_type=}")
                P.ModelSetting.set(f'tool_simple_title_sort_types', ','.join((str(x) for x in types)))
                if not types:
                    P.logger.warning(f"지정된 메타 타입이 없어 모든 메타 타입을 대상으로 조회합니다.")
                sortings = self.get_title_sortings(section_id, metadata_types=types)
                if not sortings:
                    ret['msg'] = "정리할 데이터가 없습니다."
                    return jsonify(ret)
                try:
                    is_preview = arg2.lower() == 'true'
                except Exception:
                    is_preview = True
                if is_preview:
                    modal_items = []
                    for sorting in sortings:
                        modal_items.append(f"{sorting[0]}: [{sorting[3][0]}][{sorting[2][0] if sorting[2] else ''}]{sorting[1]}")
                    ret['modal'] = json.dumps(modal_items, indent=4, ensure_ascii=False)
                    ret['title'] = '제목 색인 정리'
                else:
                    batch_size = 100
                    for i in range(0, len(sortings), batch_size):
                        batch_queries = []
                        for sorting in sortings[i:i + batch_size]:
                            batch_queries.append(f"UPDATE metadata_items SET title_sort = '" + sorting[3].replace("'", "''") + f"' WHERE id = {sorting[0]}")
                        PlexDBHandle.execute_query(';'.join(batch_queries))
                    ret['msg'] = "정리를 완료했습니다."
            elif command == 'tool_simple_movie_type_to_personal':
                section_id = arg1
                query = f"""SELECT agent FROM library_sections WHERE id = {section_id};"""
                data = PlexDBHandle.select(query)
                logger.error(data)
                if data[0]['agent'] == 'tv.plex.agents.none':
                    ret = {'ret':'warning', 'msg':'이미 기타미디어 타입입니다.'}
                    return jsonify(ret)

                query = f"""UPDATE metadata_items SET user_banner_url = user_thumb_url WHERE library_section_id = {section_id};
                UPDATE metadata_items SET user_thumb_url = user_art_url WHERE library_section_id = {section_id};
                UPDATE library_sections SET user_thumb_url = agent, user_art_url = scanner WHERE id = {section_id};
                UPDATE library_sections SET agent = "tv.plex.agents.none", scanner = "Plex Video Files" WHERE id = {section_id};
                """
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            elif command == 'tool_simple_movie_type_to_movie':
                section_id = arg1
                query = f"""SELECT agent FROM library_sections WHERE id = {section_id};"""
                data = PlexDBHandle.select(query)
                logger.error(data)
                if data[0]['agent'] != 'tv.plex.agents.none':
                    ret = {'ret':'warning', 'msg':'이미 영화 타입입니다.'}
                    return jsonify(ret)

                query = f"""UPDATE metadata_items SET user_thumb_url = user_banner_url WHERE library_section_id = {section_id};
                UPDATE metadata_items SET user_banner_url = '' WHERE library_section_id = {section_id};
                UPDATE library_sections SET agent = user_thumb_url, scanner = user_art_url WHERE id = {section_id};
                UPDATE library_sections SET user_thumb_url = '', user_art_url = '' WHERE id = {section_id};
                """
                result = PlexDBHandle.execute_query(query)
                if result != False:
                    ret = {'ret':'success', 'msg':'정상적으로 처리되었습니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'실패'}
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})

    def get_tmdb_season_info(self, tmdb_id, season_number):

        if not hasattr(self, 'tmdb_season_cache'):
            self.tmdb_season_cache = {}

        if tmdb_id not in self.tmdb_season_cache:
            self.tmdb_season_cache[tmdb_id] = {}

        api_key = P.ModelSetting.get('tmdb_api_key')
        if not api_key:
            logger.warning("TMDb API 키가 설정되어 있지 않습니다.")
            return None
        tmdb.API_KEY = api_key

        if season_number not in self.tmdb_season_cache[tmdb_id]:
            try:
                season_data = tmdb.TV_Seasons(tmdb_id, season_number).info(language='ko')
                self.tmdb_season_cache[tmdb_id][season_number] = season_data
            except Exception as e:
                logger.debug(f"TMDB 시즌 정보 가져오기 실패: tmdb_id={tmdb_id}, season={season_number}, error={e}")
                self.tmdb_season_cache[tmdb_id][season_number] = None

        return self.tmdb_season_cache[tmdb_id][season_number]

    def tmdb_info(self, tmdb_code, is_show):

        api_key = P.ModelSetting.get('tmdb_api_key')
        if not api_key:
            logger.warning("TMDb API 키가 설정되어 있지 않습니다.")
            return None
        tmdb.API_KEY = api_key
        try:
            tmdb_info = tmdb.TV(tmdb_code).info(language='ko') if is_show else tmdb.Movies(tmdb_code).info(language='ko')
            return tmdb_info
        except Exception as e:
            logger.debug(f"TMDB 정보 가져오기 실패: {e}")
            return None

    def parse_season_folder(self, name: str):
        match = re.search(
            r'^(Season|시즌)\s(?P<force_season_num>\d{1,8})((\s|\.)?(?P<season_title>.*?))?$',
            name.strip(),
            re.IGNORECASE
        )
        if match:
            return {
                'season_folder': name.strip(),
                'force_season_num': int(match.group('force_season_num')),
                'season_title': match.group('season_title') or None
            }
        return {'season_folder': name.strip()}  

    def extract_url(self, value):

        if isinstance(value, str):
            return value
        elif isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first
            elif isinstance(first, dict) and 'url' in first:
                return first['url']
        return None

    def get_yaml_metadata(self, row, yaml_data):
        mtype = row.get('metadata_type')
        index = row.get('metadata_index')
        season_index = row.get('season_index')

        result = {
            'title': None,
            'summary': None,
            'originally_available_at': None,
            'poster': None,
            'thumb': None,
            'art': None
        }

        if not yaml_data:
            return result

        if mtype in [1, 2]:
            posters = yaml_data.get('posters')
            result['title'] = yaml_data.get('title')
            result['summary'] = yaml_data.get('summary')
            result['originally_available_at'] = yaml_data.get('originally_available_at')
            result['poster'] = self.extract_url(posters)
            result['art'] = yaml_data.get('art')

        elif mtype == 3:
            season = next((s for s in yaml_data.get('seasons', []) if s.get('index') == index), None)
            if season:
                season_posters = season.get('posters')
                result['title'] = season.get('title')
                result['summary'] = season.get('summary')
                result['originally_available_at'] = season.get('originally_available_at')
                result['poster'] = self.extract_url(season_posters)
                result['art'] = season.get('art')

        elif mtype == 4:
            season = next((s for s in yaml_data.get('seasons', []) if s.get('index') == season_index), None)
            if season:
                episode = next((e for e in season.get('episodes', []) if e.get('index') == index), None)
                if episode:
                    result['title'] = episode.get('title')
                    result['summary'] = episode.get('summary')
                    result['originally_available_at'] = episode.get('originally_available_at')
                    result['thumbs'] = episode.get('thumbs')

        return result
    
    def enrich_rows(self, rows: list[dict]) -> list[dict]:

        first_episode = next((r for r in rows if r['metadata_type'] == 4 and r.get('file_path')), None)
        normalized = [dict(r) for r in rows]

        for row in normalized:
            mtype = row['metadata_type']
            file_path = row.get('file_path')

            if mtype == 1 and file_path:
                row['yaml_path'] = os.path.join(os.path.dirname(file_path), 'movie.yaml')

            elif mtype == 2 and first_episode:
                rel_path = os.path.relpath(first_episode['file_path'], first_episode['section_root'])
                parts = rel_path.split(os.sep)
                if len(parts) >= 1:
                    show_name = parts[0]
                    row['section_root'] = first_episode['section_root']
                    row['yaml_path'] = os.path.join(first_episode['section_root'], show_name, 'show.yaml')

            elif mtype == 3:
                row_id = row.get('id')
                ep = next((r for r in rows if r.get('metadata_type') == 4 and r.get('file_path') and r.get('parent_id') == row_id), None)
                if ep:
                    season_folder = os.path.basename(os.path.dirname(ep['file_path']))
                    row['section_root'] = ep['section_root']
                    row.update(self.parse_season_folder(season_folder))

            elif mtype == 4:
                parent_id = row.get('parent_id')
                season_row = next((sr for sr in normalized if sr['metadata_type'] == 3 and sr['id'] == parent_id), None)
                if season_row and 'metadata_index' in season_row:
                    row['season_index'] = season_row.get('metadata_index') or season_row.get('index')

        lookup = {
            (r.get('season_index'), r.get('index')): r
            for r in normalized if r['metadata_type'] == 4
        }

        for row in normalized:
            if row['metadata_type'] == 3:
                mi = row.get('metadata_index')
                if mi and mi >= 100:
                    base_row = next(
                        (s for s in normalized
                        if s['metadata_type'] == 3 and s.get('metadata_index') == mi % 100),
                        None
                    )
                    if base_row:
                        row['base_row'] = base_row

            elif row['metadata_type'] == 4:
                si = row.get('season_index')
                ei = row.get('index')
                if si and si >= 100:
                    row['base_row'] = lookup.get((si % 100, ei))


        normalized.sort(key=lambda r: (
            r['metadata_type'],
            r.get('season_index', 0),
            r.get('index', 0),
            r['id']
        ))

        return normalized

    def update_by_default_agent_tmdb(self, metadata_item_id, title_lock=False, title_sort_lock=False, summary_lock=False, year_lock=False):
        query = """
        WITH RECURSIVE descendants(
            id, metadata_type, parent_id, title, title_sort,
            summary, year, originally_available_at, user_fields, changed_at,
            guid, duration, user_thumb_url, user_art_url, tmdb_id, library_section_id,
            "index", original_title, content_rating, tags_director, tags_writer, tags_star, audience_rating
        ) AS (
            SELECT 
                mdi.id, mdi.metadata_type, mdi.parent_id,
                mdi.title, mdi.title_sort, mdi.summary, mdi.year,
                datetime(mdi.originally_available_at, 'unixepoch'),
                mdi.user_fields, mdi.changed_at,
                mdi.guid, mdi.duration, mdi.user_thumb_url, mdi.user_art_url,
                REPLACE(t.tag, 'tmdb://', ''),
                mdi.library_section_id,
                mdi."index",
                mdi.original_title, mdi.content_rating, mdi.tags_director, mdi.tags_writer, mdi.tags_star, mdi.audience_rating
            FROM metadata_items mdi
            JOIN taggings tg ON tg.metadata_item_id = mdi.id
            JOIN tags t ON t.id = tg.tag_id
            WHERE t.tag_type = 314
            AND t.tag LIKE 'tmdb://%'
            AND mdi.id = ?

            UNION ALL

            SELECT 
                m.id, m.metadata_type, m.parent_id,
                m.title, m.title_sort, m.summary, m.year,
                datetime(m.originally_available_at, 'unixepoch'),
                m.user_fields, m.changed_at,
                m.guid, m.duration, m.user_thumb_url, m.user_art_url,
                NULL,  -- tmdb_id는 NULL
                m.library_section_id,
                m."index",
                m.original_title, m.content_rating, m.tags_director, m.tags_writer, m.tags_star, m.audience_rating
            FROM metadata_items m
            JOIN descendants d ON m.parent_id = d.id
        )

        SELECT 
            d.*, 
            d."index" AS metadata_index,
            mp.file AS file_path,
            sl.root_path AS section_root
        FROM descendants d
        LEFT JOIN media_items mi ON mi.metadata_item_id = d.id
        LEFT JOIN media_parts mp ON mp.media_item_id = mi.id
        LEFT JOIN section_locations sl 
        ON d.library_section_id = sl.library_section_id
        AND mp.file LIKE sl.root_path || '%'
        ORDER BY d.metadata_type ASC, d.id ASC;
        """
        retry_interval = 30  
        max_attempts = 10

        for attempt in range(1, max_attempts + 1):
            data = PlexDBHandle.select_arg(query, (int(metadata_item_id),))
            if data:
                break
            if attempt < max_attempts:
                logger.warning(f"[MetaUpdate] metadata_item_id {metadata_item_id} 데이터가 없음. {retry_interval}초 후 재시도... (시도 {attempt}/{max_attempts})")
                time.sleep(retry_interval)
            else:
                logger.error(f"[MetaUpdate] metadata_item_id {metadata_item_id} 데이터 조회 실패 (최대 재시도 초과)")
                return {'ret': 'fail', 'msg': f'{retry_interval * max_attempts}초간 대기했지만 metadata_id={metadata_item_id} 데이터가 조회되지 않았습니다.'}

        if not data[0]['guid'].startswith('plex://'):

            return {'ret': 'success', 'msg': '기본 에이전트가 아닙니다.'}

        updated_data = self.enrich_rows(data)

        yaml_data = None
        tmdb_data = None

        show_row = next((r for r in updated_data if r['metadata_type'] in [1, 2]), None)
        if show_row and os.path.exists(show_row.get('yaml_path', '')):
            yaml_data = SupportYaml.read_yaml(show_row['yaml_path'])
        
        if show_row and show_row.get('tmdb_id'):
            is_show = show_row['metadata_type'] == 2
            tmdb_data = self.tmdb_info(show_row['tmdb_id'], is_show)
            if not tmdb_data:
                return {'ret': 'fail', 'msg': 'TMDb 데이터 가져오기 실패'}
        
        updated_count = 0

        for row in updated_data:

            update_fields, updated_fields, locked_codes, msg_parts = [], [], [], []
            mtype = row['metadata_type']
            updated = False
            yaml_tdata = None

            db_year = int(row['year']) if row['year'] else None
            yaml_tdata = self.get_yaml_metadata(row, yaml_data) if yaml_data else {}

            new_title = None
            db_title = row['title']
            if tmdb_data and mtype in [1, 2]:
                tmdb_date = None
                tmdb_date = tmdb_data.get('release_date') or tmdb_data.get('first_air_date')
                tmdb_year = int(tmdb_date[:4]) if tmdb_date else None
                if tmdb_year and int(tmdb_year) != 1900 and (not db_year or db_year != tmdb_year):
                    timestamp = int(datetime.strptime(tmdb_date, '%Y-%m-%d').timestamp())
                    update_fields.append(f"originally_available_at = {timestamp}")
                    update_fields.append(f"year = {tmdb_year}")
                    updated_fields.extend(['originally_available_at', 'year'])
                    msg_parts.append(f"연도 갱신: {db_year} -> {tmdb_year}")

                new_title = (yaml_tdata.get('title') or tmdb_data.get('title') or tmdb_data.get('name') or '').strip()
            elif mtype == 3:
                new_title = row.get('season_title') or ''
            elif yaml_tdata and mtype == 4:  
                new_title = (yaml_tdata.get('title') or '').strip()
            if new_title and db_title != new_title:
                safe_title = new_title.replace("'", "''")
                update_fields.append(f"title = '{safe_title}'")
                updated_fields.append('title')
                msg_parts.append(f"제목 변경: {db_title} -> {new_title}")
                if title_sort_lock:
                    first_char = new_title.lstrip()[0]
                    if first_char.isalnum() and not 44032 <= ord(first_char) <= 55203:
                        pass
                    else:
                        title_sort_cleaned = "".join([word for word in re.split(r'\W', new_title) if word])
                        if not title_sort_cleaned:
                            title_sort_cleaned = new_title
                        title_sort_normalized = unicodedata.normalize("NFKD", title_sort_cleaned)
                        safe_title_sort = title_sort_normalized.replace("'", "''")

                        if row['title_sort'] != title_sort_normalized:
                            update_fields.append(f"title_sort = '{safe_title_sort}'")
                            updated_fields.append('title_sort')
                            logger.debug(f"title_sort 업데이트: '{row['title_sort']}' -> '{safe_title_sort}'")
                else:
                    if row['title_sort'] != new_title:
                        update_fields.append(f"title_sort = '{safe_title}'")
                        updated_fields.append('title_sort')

            db_summary = row['summary']
            tmdb_summary = tmdb_data.get('overview') if tmdb_data else None
            
            safe_summary = None
            if mtype in [1, 2]:
                new_summary = (yaml_tdata.get('summary') or tmdb_summary)
                if new_summary and not SupportString.is_include_hangul(db_summary) and SupportString.is_include_hangul(new_summary) :
                    if new_summary and isinstance(new_summary, str):
                        safe_summary = new_summary.replace("'", "''")
            elif mtype == 3:
                yaml_summary = yaml_tdata.get('summary') if yaml_tdata else None
                base_row = row.get('base_row')
                base_summary = base_row.get('summary') if base_row else None
                new_summary = yaml_summary or base_summary
                if new_summary and isinstance(new_summary, str) and new_summary != db_summary:
                    safe_summary = new_summary.replace("'", "''")
            elif mtype == 4:
                if yaml_tdata:
                    new_summary = yaml_tdata.get('summary')
                    if new_summary and isinstance(new_summary, str):
                        db_summary_clean = re.sub(r'\s+', ' ', db_summary.strip() if db_summary else '')
                        new_summary_clean = re.sub(r'\s+', ' ', new_summary.strip())
                        if new_summary_clean != db_summary_clean:
                            safe_summary = new_summary.replace("'", "''")
            if safe_summary :
                update_fields.append(f"summary = '{safe_summary}'")
                updated_fields.append('summary')
                msg_parts.append("요약(한글) 갱신")

            if mtype == 3 and 'base_row' in row:
                for field in ['guid', 'year', 'updated_at', 'extra_data']:
                    base_val = row['base_row'].get(field)
                    current_val = row.get(field)

                    if field == 'year':
                        if current_val != base_val:
                            update_fields.append(f"{field} = {base_val}")
                            updated_fields.append(field)
                        continue

                    elif field == 'updated_at':
                        if isinstance(base_val, datetime):
                            base_val_str = base_val.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            base_val_str = str(base_val) if base_val is not None else None

                        if base_val_str:
                            try:
                                dt = datetime.strptime(base_val_str, '%Y-%m-%d %H:%M:%S')
                                dt_plus = dt + timedelta(seconds=1)
                                updated_str = dt_plus.strftime('%Y-%m-%d %H:%M:%S')
                                if current_val != updated_str:
                                    update_fields.append(f"{field} = '{updated_str}'")
                                    updated_fields.append(field)
                            except Exception as e:
                                logger.warning(f"updated_at 파싱 실패: {base_val_str} → {e}")
                        continue

                    elif isinstance(base_val, str):
                        escaped_val = base_val.replace("'", "''")
                        if current_val != base_val:
                            update_fields.append(f"{field} = '{escaped_val}'")
                            updated_fields.append(field)
                        continue

                    if current_val != base_val:
                        update_fields.append(f"{field} = '{base_val}'" if base_val is not None else f"{field} = NULL")
                        updated_fields.append(field)


            elif mtype == 4 and 'base_row' in row and row['base_row'] :
                for field in ['guid', 'title', 'title_sort', 'summary', 'original_title', 'duration', 'content_rating', 'tags_director', 'tags_writer', 'tags_star', 'originally_available_at', 'audience_rating']:
                    base_val = row['base_row'].get(field)
                    current_val = row.get(field)
                    if field in ['title', 'title_sort', 'summary'] :
                        if field in updated_fields or current_val:
                            continue

                    if field == 'originally_available_at':

                        if isinstance(base_val, str):
                            try:
                                date_str = base_val[:10]
                                dt_utc = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                                base_val_ts = int(dt_utc.timestamp())
                            except Exception as e:
                                logger.warning(f"날짜 파싱 실패: {base_val} → {e}")
                                base_val_ts = None
                        else:
                            base_val_ts = base_val

                        if isinstance(current_val, str):
                            try:
                                dt_utc = datetime.strptime(current_val, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                                current_val_ts = int(dt_utc.timestamp())
                            except:
                                current_val_ts = None
                        else:
                            current_val_ts = current_val

                        if current_val_ts != base_val_ts:
                            logger.debug(current_val_ts)
                            logger.debug(base_val_ts)
                            val = base_val_ts
                            update_fields.append(f"{field} = '{val}'" if val is not None else f"{field} = NULL")
                            updated_fields.append(field)
                    else:
                        if current_val != base_val:
                            val = base_val.replace("'", "''") if isinstance(base_val, str) else base_val
                            update_fields.append(f"{field} = '{val}'" if val is not None else f"{field} = NULL")
                            updated_fields.append(field)

            new_url = None
            tmdb_url = None
            if mtype in [1, 2]:
                image_fields = [
                ('poster', 'poster_path', 'user_thumb_url'),
                ('art', 'backdrop_path', 'user_art_url'),
                ]
                for kind, path_key, db_field in image_fields:
                    current = row.get(db_field, '')
                    if current and not current.startswith('media://'):
                        continue
                    if tmdb_data.get(path_key):
                        tmdb_url = f"https://image.tmdb.org/t/p/original{tmdb_data[path_key]}"
                        new_url = (yaml_tdata.get(kind) or tmdb_url)
                    if new_url:
                        safe_img_url = new_url.replace("'", "''")
                        update_fields.append(f"{db_field} = '{safe_img_url}'")
                        updated = True
            elif mtype == 3:
                poster_url = (yaml_tdata.get('poster') if yaml_tdata else None) \
                    or (row.get('base_row') or {}).get('user_thumb_url')
                if poster_url and row.get('user_thumb_url') != poster_url:
                    safe_poster_url = poster_url.replace("'", "''")
                    update_fields.append(f"user_thumb_url = '{safe_poster_url}'")
                    updated_fields.append('user_thumb_url')
                    updated = True

            elif mtype == 4:
                base_row = row.get('base_row')
                user_thumb_url = row.get('user_thumb_url')
                thumb_url = yaml_tdata.get('thumbs') or (base_row and base_row.get('user_thumb_url'))

                if thumb_url and not re.match(r'^(metadata|https?)://', thumb_url):
                    thumb_url = None

                if not yaml_tdata.get('thumbs') and not thumb_url and not re.match(r'^(metadata|https?)://', user_thumb_url or '') and show_row and show_row.get('tmdb_id'):
                    tmdb_id = show_row['tmdb_id']
                    season_index = int(row.get('season_index', 0)) % 100
                    episode_index = row.get('index')

                    tmdb_season = self.get_tmdb_season_info(tmdb_id, season_index)
                    if tmdb_season and 'episodes' in tmdb_season:
                        for ep in tmdb_season['episodes']:
                            if ep.get('episode_number') == episode_index:
                                still_path = ep.get('still_path')
                                if still_path:
                                    thumb_url = f"https://image.tmdb.org/t/p/original{still_path}"
                                    break

                if thumb_url and thumb_url != user_thumb_url:
                    safe_thumb_url = thumb_url.replace("'", "''")
                    update_fields.append(f"user_thumb_url = '{safe_thumb_url}'")
                    updated_fields.append('user_thumb_url')
                    updated = True

            if title_lock and 'title' in updated_fields:
                locked_codes.append(1)
            if mtype in [1, 2, 4] and title_sort_lock and 'title_sort' in updated_fields:
                locked_codes.append(2)
            if summary_lock and 'summary' in updated_fields:
                locked_codes.append(7)  
            if mtype in [1, 2] and year_lock and 'originally_available_at' in updated_fields:
                locked_codes.append(13)
                locked_codes.append(14)   

            if locked_codes:

                current_user_fields = row.get('user_fields') or ''
                match = re.search(r'lockedFields=([\d|]+)', current_user_fields)
                existing = set(map(int, match.group(1).split('|'))) if match else set()
                merged = sorted(existing.union(locked_codes))
                locked_str = 'lockedFields=' + '|'.join(map(str, merged))
                if 'lockedFields=' in current_user_fields:
                    user_fields_new = re.sub(r'lockedFields=[\d|]*', locked_str, current_user_fields)
                else:
                    user_fields_new = f"{current_user_fields}||{locked_str}" if current_user_fields else locked_str

                update_fields.append(f"user_fields = '{user_fields_new}'")
                updated = True

            if updated:
                update_fields.append(f"updated_at = {int(datetime.strptime(row['updated_at'], '%Y-%m-%d %H:%M:%S').timestamp()) + 1}" if row.get('updated_at') else f"updated_at = {int(time.time())}")
                update_fields.append(f"changed_at = {int(row['changed_at']) + 1 if row.get('changed_at') is not None else 1}")

            if update_fields:
                update_sql = f"UPDATE metadata_items SET {', '.join(update_fields)} WHERE id = {row['id']};"
                logger.debug(f"[TMDB 업데이트] {update_sql}")
                result = PlexDBHandle.execute_query(update_sql)
                if result is False:
                    return {'ret': 'fail', 'msg': 'DB 업데이트 실패'}
                updated_count += 1

        if updated_count > 0:
            return {'ret': 'success', 'msg': f'{updated_count}개 항목 업데이트'}
        else:
            return {'ret': 'success', 'msg': '변경할 항목이 없습니다.'}

    def get_title_sortings(self, section_id: int, metadata_types: list = None) -> list[tuple[int, str, str, str]]:
        query = f"SELECT id, title, title_sort, metadata_type FROM metadata_items WHERE library_section_id = ?"
        args = (section_id,)
        if metadata_types:
            query += f" AND metadata_type IN ({','.join(['?'] * len(metadata_types))})"
            args += (*metadata_types,)
        rows: list[dict] | None = PlexDBHandle.select_arg(query, args)
        if not rows:
            logger.warning(f"데이터를 가져오지 못 했습니다: {section_id=} {metadata_types=}")
            return []
        sortings = []
        for row in rows:
            if not row.get('title'):
                continue
            first_char = row['title_sort'][0] if row.get('title_sort') else row.get('title')[0]
            if first_char.isalnum() and not 44032 <= ord(first_char) <= 55203:
                continue
            new_title_sort = "".join([word for word in re.split(r'\W', row['title']) if word])
            if not new_title_sort:
                logger.warning(f"색인용 문자가 없습니다: '{row['title']}'")
                new_title_sort = row['title']
            new_title_sort = unicodedata.normalize('NFKD', new_title_sort)
            logger.debug(f"{row['id']}: [{new_title_sort[0]}][{first_char}]{row['title']}")
            if new_title_sort != row['title_sort']:
                sortings.append((row['id'], row['title'], row['title_sort'], new_title_sort))
        return sortings

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
