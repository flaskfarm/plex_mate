import urllib.parse

import requests

from .setup import *

logger = P.logger


class PlexWebHandle(object):
    
    @classmethod
    def system_agents(cls, url=None, token=None):
        if url is None:
                url = P.ModelSetting.get('base_plex_url')
        if token is None:
            token = P.ModelSetting.get('base_token')
        #url = f'{url}/:/prefs?X-Plex-Token={token}'
        url = f'{url}/system/agents?X-Plex-Token={token}'
        logger.warning(url)
        res = requests.get(url, headers={'Accept':'application/json'})
        return res.text



    @classmethod
    def get_sjva_version(cls, url=None, token=None):
        try:
            if url is None:
                url = P.ModelSetting.get('base_plex_url')
            if token is None:
                token = P.ModelSetting.get('base_token')
            url = f'{url}/:/plugins/com.plexapp.plugins.SJVA/function/version?X-Plex-Token={token}'
            page = requests.get(url)
            return page.text
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def get_sjva_agent_version(cls, url, token):
        try:
            if url is None:
                url = P.ModelSetting.get('base_plex_url')
            if token is None:
                token = P.ModelSetting.get('base_token')
            url = f'{url}/:/plugins/com.plexapp.agents.sjva_agent/function/version?X-Plex-Token={token}'
            page = requests.get(url)
            return page.text
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    
    @classmethod
    def refresh(cls, movie_item):
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/metadata/{movie_item['id']}/refresh?X-Plex-Token={P.ModelSetting.get('base_token')}"
            ret = requests.put(url)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    
    @classmethod
    def refresh_by_id(cls, id):
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/metadata/{id}/refresh?X-Plex-Token={P.ModelSetting.get('base_token')}"
            ret = requests.put(url)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    

    @classmethod
    def analyze_by_id(cls, id):
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/metadata/{id}/analyze?X-Plex-Token={P.ModelSetting.get('base_token')}"
            ret = requests.put(url)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def section_scan(cls, library_section_id):
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/sections/{library_section_id}/refresh?X-Plex-Token={P.ModelSetting.get('base_token')}"
            ret = requests.get(url)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    

    @classmethod
    def make_playlist(cls, playlist_title, metadata_id):
        try:
            from .plex_db import PlexDBHandle
            url = f"{P.ModelSetting.get('base_url')}/playlists?"
            data = {
                'type': 'video',
                'title': playlist_title,
                'smart': 0,
                'uri':f"server://{P.ModelSetting.get('base_machine')}/com.plexapp.plugins.library/library/metadata/{metadata_id}",
            }
            url += urllib.parse.urlencode(data)
            ret = requests.post(url, headers={'X-Plex-Token': P.ModelSetting.get('base_token')}, data=data)
            query = f"SELECT id FROM metadata_items WHERE title = '{playlist_title}' AND metadata_type = 15"
            data = PlexDBHandle.select(query)
            return data[-1]['id']
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    
    @classmethod
    def add_playlist(cls, metadata_id, playlist_title=None, playlist_id=None):
        try:
            from .plex_db import PlexDBHandle
            if playlist_id == None:
                query = f"SELECT id FROM metadata_items WHERE title = '{playlist_title}' AND metadata_type = 15"
                data = PlexDBHandle.select(query)
                if len(data) == 0:
                    playlist_id = cls.make_playlist(playlist_title, metadata_id)
                    return playlist_id
                else:
                    playlist_id = data[-1]['id']

            url = f"{P.ModelSetting.get('base_url')}/playlists/{playlist_id}/items?"
            data = {
                'uri':f"server://{P.ModelSetting.get('base_machine')}/com.plexapp.plugins.library/library/metadata/{metadata_id}",
            }
            url += urllib.parse.urlencode(data)
            ret = requests.put(url, headers={'X-Plex-Token': P.ModelSetting.get('base_token')})
            #logger.error(d(ret))
            return playlist_id
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def path_scan(cls, library_section_id, path: str) -> None:
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/sections/{library_section_id}/refresh"
            params = {
                'X-Plex-Token': P.ModelSetting.get('base_token'),
                'path': path,
            }
            response = requests.request('GET', url, params=params)
            if not str(response.status_code)[0] == '2':
                logger.error(f'스캔 전송 실패: {response.text}')
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    
    # 2024.10.10 섹션 모든메타새로고침 
    @classmethod
    def refresh_section_force(cls, section_id):
        try:
            url = f"{P.ModelSetting.get('base_url')}/library/sections/{section_id}/refresh?force=1&X-Plex-Token={P.ModelSetting.get('base_token')}"
            res = requests.get(url)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def manual_refresh(cls, meta_id: int, plugin_instance=None) -> dict:
        if not P.ModelSetting.get_bool('webhook_agent_meta_update'):
            return {'ret': 'warning', 'msg': f'기본 에이전트 TMDb 정보 갱신 설정이 Off 입니다.'}
        try:
            import sqlite3
            from .page_tool_simple import PageToolSimple
            db_path = P.ModelSetting.get('base_path_db')
            if not os.path.exists(db_path):
                return {'ret': 'error', 'msg': f'Plex DB 경로가 존재하지 않습니다: {db_path}'}

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            sql = '''
            WITH RECURSIVE ancestors(id, metadata_type, parent_id) AS (
                SELECT id, metadata_type, parent_id FROM metadata_items WHERE id = ?
                UNION ALL
                SELECT m.id, m.metadata_type, m.parent_id
                FROM metadata_items m
                JOIN ancestors a ON m.id = a.parent_id
            )
            SELECT id
            FROM ancestors
            WHERE metadata_type IN (1, 2)
            ORDER BY parent_id IS NULL DESC, id DESC
            LIMIT 1
            '''

            cursor.execute(sql, (meta_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return {'ret': 'warning', 'msg': '상위 metadata_type 1 또는 2 항목을 찾을 수 없습니다.'}

            root_id = row['id']
            #cls.refresh_by_id(root_id)

            title_lock = P.ModelSetting.get_bool('agent_meta_lock_title')
            title_sort_lock = P.ModelSetting.get_bool('agent_meta_lock_title_sort')
            year_lock = P.ModelSetting.get_bool('agent_meta_lock_year')
            summary_lock = P.ModelSetting.get_bool('agent_meta_lock_summary')

            plugin_instance = F.PluginManager.get_plugin_instance('plex_mate')
            if not hasattr(plugin_instance, 'name'):
                plugin_instance.name = 'plex_mate'
            page_tool = PageToolSimple(P, plugin_instance)

            page_tool.update_by_default_agent_tmdb(
                root_id,
                title_lock=title_lock,
                title_sort_lock=title_sort_lock,
                summary_lock=summary_lock,
                year_lock=year_lock,
            )

            return {'ret': 'success', 'msg': 'TMDB 갱신 완료'}
        
        except Exception as e:
            P.logger.error(traceback.format_exc())
            return {'ret': 'error', 'msg': f'TMDB 갱신 중 오류: {e}'}
