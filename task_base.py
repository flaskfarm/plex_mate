import urllib.parse

from support import SupportFile, SupportOSCommand, SupportSubprocess

from .setup import *

logger = P.logger


class Task(object):
    
    @staticmethod
    @celery.task()
    def get_size(args):
        logger.warning(args)
        ret = SupportOSCommand.get_size(args[0])
        #logger.warning(ret)
        return ret

    @staticmethod
    @celery.task()
    def backup(args):
        try:
            logger.warning(args)
            db_path = args[0]
            if os.path.exists(db_path):
                dirname = os.path.dirname(db_path)
                basename = os.path.basename(db_path)
                tmp = os.path.splitext(basename)
                newfilename = f"{tmp[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{tmp[1]}"
                if P.ModelSetting.get_bool('base_backup_location_mode'):
                    newpath = os.path.join(dirname, newfilename)
                else:
                    newpath = os.path.join(P.ModelSetting.get('base_backup_location_manual'), newfilename)
                shutil.copy(db_path, newpath)
                ret = {'ret':'success', 'target':newpath}
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            ret = {'ret':'fail', 'log':str(e)}
        return ret
         
    @staticmethod
    @celery.task()
    def clear(args):
        if os.path.basename(os.path.normpath(args[0])) == 'PhotoTranscoder':
            for root, dirs, files in os.walk(args[0], topdown=False):
                try:
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
                except:
                    logger.error(traceback.format_exc())
        else:
            ret = SupportFile.rmtree(args[0])
            os.makedirs(args[0], exist_ok=True)
        # 범주
        if P.ModelSetting.get_bool('clear_cache_retrieve_category'):
            Task.retrieve_category()
        return Task.get_size(args)


    @staticmethod
    @celery.task()
    def agent_update(args):
        ret = {'recent_version':None, 'local_version':None, 'need_update':False}
        # 버전
        regex = re.compile("VERSION\s=\s'(?P<version>.*?)'")
        text = requests.get('https://raw.githubusercontent.com/soju6jan/SjvaAgent.bundle/main/Contents/Code/version.py').text
        match = regex.search(text)
        if match:
            ret['recent_version'] = match.group('version')
        if ret['recent_version'] == None:
            return "접속실패"
        all_agent_path = os.path.join(P.ModelSetting.get('base_path_data'), 'Plug-ins')
        sjva_agent_path = os.path.join(all_agent_path, 'SjvaAgent.bundle')
        version_path = os.path.join(sjva_agent_path, 'Contents', 'Code', 'version.py')
        if os.path.exists(version_path):
            text = SupportFile.read_file(version_path)
            match = regex.search(text)
            if match:
                ret['local_version'] = match.group('version')
                if ret['local_version'] != ret['recent_version']:
                    ret['need_update'] = True
        else:
            ret['need_update'] = True

        #ret['need_update'] = True
        ret['flag_clone'] = False
        if ret['need_update'] == False:
            ret['log'] = "최신 버전"
            return ret

        git_path = os.path.join(sjva_agent_path, '.git')
        if os.path.exists(sjva_agent_path):
            if os.path.exists(git_path):
                command = ['git', '-C', sjva_agent_path, 'reset', '--hard', 'HEAD']
                result = SupportSubprocess.execute_command_return(command)
                F.logger.debug(d(result))
                command = ['git', '-C', sjva_agent_path, 'pull']
                result = SupportSubprocess.execute_command_return(command)
                F.logger.debug(d(result))
                ret['git_update'] = True
            else:
                result = SupportFile.rmtree(sjva_agent_path)
                P.logger.error(result)
                if result == False:
                    ret['log'] = "플러그인 폴더 삭제 필요"
                    return ret
                else:
                    ret['flag_clone'] = True
        else:
            ret['flag_clone'] = True
                
        if ret['flag_clone']:
            command = ['git', '-C', all_agent_path, 'clone', 'https://github.com/soju6jan/SjvaAgent.bundle' + '.git', '--depth', '1']
            log = SupportSubprocess.execute_command_return(command, log=True)
            F.logger.debug(log)

        for folder in ['dummy_agent', 'standalone_agent']:
            dummy = os.path.join(sjva_agent_path, folder)
            for name in os.listdir(dummy):
                source_path = os.path.join(dummy, name)
                if os.path.isdir(source_path) == False:
                    continue
                target_path = os.path.join(all_agent_path, name)
                SupportFile.rmtree(target_path)
                shutil.move(source_path, all_agent_path)


        for base, dirs, files in os.walk(os.path.join(sjva_agent_path, 'Scanners')):
            for name in files:
                source_path = os.path.join(base, name)
                #P.logger.error(base)
                target_folder = base.replace(os.sep+'Plug-ins'+os.sep+'SjvaAgent.bundle', '')
                #P.logger.error(target_folder)
                if os.path.exists(os.path.join(target_folder, name)):
                    os.remove(os.path.join(target_folder, name))
                os.makedirs(target_folder, exist_ok=True)
                shutil.move(source_path, target_folder)
        ret['log'] = '정상 완료'
        return ret

    @classmethod
    @celery.task()
    def retrieve_category(args) -> None:
        logger.debug(f'START retrieve_category()')
        params = {
            'includeCollections': 1,
            'includeExternalMedia': 1,
            'includeAdvanced': 1,
            'includeMeta': 1,
            'X-Plex-Features': 'external-media%2Cindirect-media%2Chub-style-list',
            'X-Plex-Model': 'bundled',
            'X-Plex-Container-Start': 0,
            'X-Plex-Container-Size': 500,
            'X-Plex-Text-Format': 'plain',
            'X-Plex-Language': 'ko',
            'X-Plex-Token': P.ModelSetting.get('base_token'),
        }
        headers = {
            'Accept': 'application/json',
        }
        try:
            sections = (section['id'] for section in P.PlexDBHandle.library_sections() if section['section_type'] in [1, 2])
        except:
            logger.error(traceback.format_exc())
            return
        for section in sections:
            url = urllib.parse.urljoin(P.ModelSetting.get('base_url'), f'/library/sections/{section}/categories')
            try:
                data = requests.request('GET', url, headers=headers, params=params).json()
            except:
                logger.error(traceback.format_exc())
                logger.error(f'{section=}')
                continue
            directory = data.get('MediaContainer', {}).get('Directory')
            if not directory:
                continue
            for dir in directory:
                url_photo = urllib.parse.urljoin(P.ModelSetting.get('base_url'), dir['thumb'])
                params = {
                    'X-Plex-Token': P.ModelSetting.get('base_token')
                }
                try:
                    requests.request('GET', url_photo, params=params)
                except:
                    logger.error(traceback.format_exc())
                    logger.error(dir)
        logger.debug(f'END retrieve_category()')
