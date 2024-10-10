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