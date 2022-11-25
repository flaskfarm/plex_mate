from support import SupportFile, SupportOSCommand

from .setup import *


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
        ret = SupportFile.rmtree(args[0])
        os.makedirs(args[0], exist_ok=True)
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

        P.logger.error(ret['recent_version'])

        agent_path = os.path.join(P.ModelSetting.get('base_path_data'), 'Plug-ins')
        version_path = os.path.join(agent_path, 'SjvaAgent.bundle', 'Contents', 'Code', 'version.py')
        if os.path.exists(version_path):
            text = SupportFile.read_file(version_path)
            match = regex.search(text)

            if match:
                ret['local_version'] = match.group('version')
                if ret['local_version'] != ret['recent_version']:
                    ret['need_update'] = True
        else:
            ret['need_update'] = True

        ret['need_update'] = True
        #if ret['need_update'] == True:
        #    SupportFile.rmtree(agent_path)




        return ret