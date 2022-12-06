import platform
import subprocess

from support import SupportSubprocess, d

from .setup import *


class PlexBinaryScanner(object):
    
    # 2022-11-27 스캔은 되나 메타 갱신하지 않는다 plex 1.30 버전인듯
    # 잘못 알았다 도커 브릿지 모
    @classmethod
    def scan_refresh(cls, section_id, folderpath, timeout=None, callback_function=None, callback_id=None, join=False):
        env = os.environ.copy()
        env['PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR'] = os.path.dirname(os.path.dirname(P.ModelSetting.get('base_path_metadata')))
        
        if folderpath is None or folderpath == '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id)]
            process = SupportSubprocess(command, timeout=timeout,  stdout_callback=callback_function, env=env, uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'), call_id=callback_id)
            process.start(join=join)
            
        else:
            command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id), '--directory', folderpath]
            process = SupportSubprocess(command, timeout=timeout,  stdout_callback=callback_function, env=env, uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'), call_id=callback_id)
            process.start(join=join)
            """
            from .plex_db import PlexDBHandle
            metaid = PlexDBHandle.get_metaid_by_directory(section_id, folderpath)
            if metaid != None:
                return cls.meta_refresh_by_id(metaid)
            """
        return process


    @classmethod
    def analyze(cls, section_id, folderpath=None, metadata_item_id=None, timeout=None, db_item=None):
        env = os.environ.copy()
        env['PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR'] = os.path.dirname(os.path.dirname(P.ModelSetting.get('base_path_metadata')))
        
        if folderpath is not None and folderpath != '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id), '--directory', folderpath]
        elif metadata_item_id is not None and metadata_item_id != '':
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id), '--item', metadata_item_id]
        else:
            command = [P.ModelSetting.get("base_bin_scanner"), '--analyze', '--section', str(section_id)]

        process = SupportSubprocess(command, timeout=timeout, env=env, uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'))
        process.start(join=False)
        return process


    @classmethod
    def meta_refresh_by_id(cls, item_id, timeout=None, join=False):
        env = os.environ.copy()
        env['PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR'] = os.path.dirname(os.path.dirname(P.ModelSetting.get('base_path_metadata')))
        
        command = [P.ModelSetting.get("base_bin_scanner"), '--force', '--refresh', '--item', str(item_id)]
        process = SupportSubprocess(command, timeout=timeout, env=env, uid=P.ModelSetting.get_int('base_bin_scanner_uid'), gid=P.ModelSetting.get_int('base_bin_scanner_gid'))
        process.start(join=join)
        return process

    



        

    """
        #su - plex -c "/usr/lib/plexmediaserver/Plex\ Media\ Scanner --section 8 --analyze --item 332875"

    @classmethod
    def scan_refresh_old(cls, section_id, folderpath, timeout=None, db_item=None, scan_item=None):
        def demote(user_uid, user_gid):
            def result():
                os.setgid(user_gid)
                os.setuid(user_uid)
            return result
        shell = False
        env = dict(PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR=f"{os.path.dirname(os.path.dirname(P.ModelSetting.get('base_path_metadata')))}", **os.environ)
        force_log = False
        try:
            if platform.system() == 'Windows':
                if folderpath is None or folderpath == '':
                    command = f'"{P.ModelSetting.get("base_bin_scanner")}" --scan  --refresh --section {section_id}"'
                else:
                    command = f'"{P.ModelSetting.get("base_bin_scanner")}" --scan  --refresh --section {section_id} --directory "{folderpath}"'
                logger.warning(command)
                tmp = []
                if type(command) == type([]):
                    for x in command:
                        if x.find(' ') == -1:
                            tmp.append(x)
                        else:
                            tmp.append(f'"{x}"')
                    command = ' '.join(tmp)
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, shell=shell, env=env, encoding='utf8')
            else:
                if folderpath is None or folderpath == '':
                    command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id)]
                else:
                    command = [P.ModelSetting.get("base_bin_scanner"), '--scan', '--refresh', '--section', str(section_id), '--directory', folderpath]
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, shell=shell, env=env, preexec_fn=demote(P.ModelSetting.get_int('base_bin_scanner_uid'), P.ModelSetting.get_int('base_bin_scanner_gid')), encoding='utf8')
                

            if db_item is not None:
                db_item.process_pid = process.pid
                db_item.start_time = datetime.now()
                db_item.status = "working"
                db_item.save()
            if scan_item is not None:
                scan_item.scan_process_pid = process.pid
                scan_item.save()


            new_ret = {'status':'finish', 'log':None}
            logger.debug(f"PLEX SCANNER COMMAND\n{' '.join(command)}")
            try:
                process_ret = process.wait(timeout=timeout)
                logger.debug(f"process_ret : {process_ret}")

                if db_item is not None:
                    if process_ret == 0:
                        db_item.status = 'finished'
            except:
                import psutil
                process = psutil.Process(process.pid)
                for proc in process.children(recursive=True):
                    proc.kill()
                process.kill()
                if db_item is not None:
                    db_item.status = 'timeout'
                if scan_item is not None:
                    scan_item.status = 'finish_timeout'

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            logger.error('command : %s', command)
        finally:
            if scan_item is not None:
                scan_item.save()


    @classmethod
    def meta_refresh_by_id(cls, item_id, timeout=None):
        def demote(user_uid, user_gid):
            def result():
                os.setgid(user_gid)
                os.setuid(user_uid)
            return result
        shell = False
        env = dict(PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR=f"{os.path.dirname(os.path.dirname(ModelSetting.get('base_path_metadata')))}", **os.environ)
        force_log = False
        try:
            if platform.system() == 'Windows':
                command = f'"{ModelSetting.get("base_bin_scanner")}" --force --refresh --item {item_id}"'
                tmp = []
                if type(command) == type([]):
                    for x in command:
                        if x.find(' ') == -1:
                            tmp.append(x)
                        else:
                            tmp.append(f'"{x}"')
                    command = ' '.join(tmp)
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, shell=shell, env=env, encoding='utf8')
            else:
                command = [ModelSetting.get("base_bin_scanner"), '--force', '--refresh', '--item', str(item_id)]
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, shell=shell, env=env, preexec_fn=demote(ModelSetting.get_int('base_bin_scanner_uid'), ModelSetting.get_int('base_bin_scanner_gid')), encoding='utf8')

            new_ret = {'status':'finish', 'log':None}
            logger.debug(f"PLEX SCANNER COMMAND\n{' '.join(command)}")
            try:
                process_ret = process.wait(timeout=timeout)
                logger.debug(f"process_ret : {process_ret}")
            except:
                import psutil
                process = psutil.Process(process.pid)
                for proc in process.children(recursive=True):
                    proc.kill()
                process.kill()
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            logger.error('command : %s', command)
        finally:
            pass
    
    """           