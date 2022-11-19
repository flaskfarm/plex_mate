import requests

from .setup import *


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