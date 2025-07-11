import platform
import subprocess

from support import SupportSubprocess, d

from .setup import *


class PlexBinaryScanner(object):
    @classmethod
    def get_env(cls):
        env = os.environ.copy()
        env['PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR'] = os.path.dirname(os.path.dirname(P.ModelSetting.get('base_path_metadata')))
        env['LD_LIBRARY_PATH'] = P.ModelSetting.get('base_path_program')
        return env
    
    # 2022-11-27 스캔은 되나 메타 갱신하지 않는다 plex 1.30 버전인듯
    # 잘못 알았다 도커 브릿지 모
    @classmethod
    def scan_refresh(cls, section_id, folderpath, timeout=None, callback_function=None, callback_id=None, join=False):
        if folderpath is None or folderpath == '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id)]
            process = SupportSubprocess(command, timeout=timeout,  stdout_callback=callback_function, env=cls.get_env(), uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'), call_id=callback_id)
            process.start(join=join)
            
        else:
            command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id), '--directory', folderpath]
            process = SupportSubprocess(command, timeout=timeout,  stdout_callback=callback_function, env=cls.get_env(), uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'), call_id=callback_id)
            process.start(join=join)
        return process


    @classmethod
    def analyze(cls, section_id, folderpath=None, metadata_item_id=None, timeout=None, db_item=None, join=False):
        if folderpath is not None and folderpath != '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id), '--directory', folderpath]
        elif metadata_item_id is not None and metadata_item_id != '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id), '--item', metadata_item_id]
        else:
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id)]

        process = SupportSubprocess(command, timeout=timeout, env=cls.get_env(), uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'))
        process.start(join=join)
        return process


    @classmethod
    def meta_refresh_by_id(cls, item_id, timeout=None, join=False):
        command = [P.ModelSetting.get("base_bin_scanner"), '--force', '--refresh', '--item', str(item_id)]
        process = SupportSubprocess(command, timeout=timeout, env=cls.get_env(), uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'))
        process.start(join=join)
        return process
