import platform
from xml.parsers.expat import ExpatError

import requests
import xmltodict
from support import SupportFile, SupportSubprocess, SupportYaml, d

from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *
from .task_base import Task


class ModuleBase(PluginModuleBase):
    
    def __init__(self, P):
        super(ModuleBase, self).__init__(P, name='base', first_menu='setting')
        self.db_default = {
            f'{self.name}_db_version' : '1',
            f'{self.name}_path_program' : '',
            f'{self.name}_path_data' : '',
            f'{self.name}_bin_scanner' : '',
            f'{self.name}_bin_sqlite' : '',
            f'{self.name}_path_db' : '',
            f'{self.name}_path_metadata' : '',
            f'{self.name}_path_media' : '',
            f'{self.name}_path_phototranscoder' : '',
            f'{self.name}_token' : '',
            f'{self.name}_url' : 'http://localhost:32400',
            f'{self.name}_backup_location_mode' : 'True',
            f'{self.name}_backup_location_manual' : '',
            f'{self.name}_path_config' : "{PATH_DATA}" + os.sep + "db" + os.sep + f'{P.package_name}_config.yaml',
            f'{self.name}_bin_scanner_uid' : '0',
            f'{self.name}_bin_scanner_gid' : '0',
            f'{self.name}_machine' : '',
            f'{self.name}_agent_auto_update' : 'False',
        }


    def plugin_load(self):
        config_path = ToolUtil.make_path(P.ModelSetting.get(f'{self.name}_path_config'))
        config_source_filepath = os.path.join(os.path.dirname(__file__), 'files', os.path.basename(config_path))        
        try:
            config = P.load_config()
        except FileNotFoundError:
            shutil.copyfile(config_source_filepath, config_path)
            config = P.load_config()
        if os.path.exists(config_path):
            #logger.warning(d(config))
            if '파일정리 영화 쿼리' not in config:
                SupportYaml.copy_section(config_source_filepath, config_path, '파일정리')
            if '라이브러리 복사 영화 쿼리' not in config:
                SupportYaml.copy_section(config_source_filepath, config_path, '라이브러리 복사')
            if '라이브러리 주기적 스캔 목록' not in config:
                SupportYaml.copy_section(config_source_filepath, config_path, '라이브러리 주기적 스캔')
        if P.ModelSetting.get_bool(f'{self.name}_agent_auto_update'):
            self.task_interface('agent_update', ('SjvaAgent',False))
         

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['path_app'] = F.config['path_app'].replace('\\', '/')
        arg[f'{self.name}_path_config'] = ToolUtil.make_path(P.ModelSetting.get(f'{self.name}_path_config'))
        try:
            return render_template(f'{P.package_name}_{self.name}_{sub}.html', arg=arg)
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            return render_template('sample.html', title=f"{P.package_name}/{self.name}/{sub}")

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'plex_folder_test':
        
            program_path = arg1
            data_path = arg2
            if os.path.exists(program_path) == False:
                ret = {'ret':'warning', 'msg':'데이터 폴더가 없습니다.'}
            elif os.path.exists(data_path) == False:
                ret = {'ret':'warning', 'msg':'프로그램 폴더가 없습니다.'}
            else:
                ret['data'] = {}
                ret['data']['bin_scanner'] = os.path.join(program_path, 'Plex Media Scanner')
                ret['data']['bin_sqlite'] = os.path.join(program_path, 'Plex SQLite')
                ret['data']['path_db'] = os.path.join(data_path, 'Plug-in Support', 'Databases', 'com.plexapp.plugins.library.db')
                ret['data']['path_metadata'] = os.path.join(data_path, 'Metadata')
                ret['data']['path_media'] = os.path.join(data_path, 'Media')
                ret['data']['path_phototranscoder'] = os.path.join(data_path, 'Cache', 'PhotoTranscoder')
                
                if platform.system() == 'Windows':
                    ret['data']['bin_scanner'] += '.exe'
                    ret['data']['bin_sqlite'] += '.exe'
                    ret['data']['token'] = P.ModelSetting.get(f'{self.name}_token')
                else:
                    xml_string = SupportFile.read_file(os.path.join(data_path, 'Preferences.xml'))
                    result = xmltodict.parse(xml_string)
                    prefs = json.loads(json.dumps(result))
                    logger.warning(d(prefs))
                    ret['data']['token'] = prefs['Preferences']['@PlexOnlineToken']
                    ret['data']['machine'] = prefs['Preferences']['@ProcessedMachineIdentifier']

                for key, value in ret['data'].items():
                    if key not in ['token', 'machine']:
                        if os.path.exists(value) == False:
                            ret = {'ret':'warning', 'msg':'올바른 경로가 아닙니다.<br>' + value}
                            return jsonify(ret)
                ret['ret'] = 'success'
                ret['msg'] = '설정을 저장하세요.'
        elif command == 'size':
            self.task_interface('size', (arg1,))
            ret = {'ret':'success', 'msg':'명령을 전달하였습니다. 잠시 후 결과 알림을 확인하세요.'}
        elif command == 'execute':
            if arg1 == 'scanner':
                data = SupportSubprocess.execute_command_return([arg2])
                data = data['log'].replace('\n', '<br>').lstrip('"').rstrip('"')
                ret['title'] = 'Scanner Help'
                ret['modal'] = data
            elif arg1 == 'sqlite':
                data = []
                data.append(f"SQLite 버전")
                data.append(f" - {SupportSubprocess.execute_command_return([req.form['arg2'], '-version'])['log']}")
                data.append("")
                data.append(f"Plex Media Server 버전")
                data.append(f" - {SupportSubprocess.execute_command_return([req.form['arg2'], '--version'])['log']}")
                data = '<br>'.join(data)
                ret['title'] = 'SQLite Version'
                ret['modal'] = data
        elif command == 'backup':
            if arg1 == 'plex_db':
                self.task_interface('backup', (arg2,))
                ret = {'ret':'success', 'msg':'명령을 전달하였습니다. 잠시 후 결과 알림을 확인하세요.'}
        elif command == 'db':
            if arg1 == 'library_sections':
                data = PlexDBHandle.library_sections(arg2)
                ret['title'] = '라이브러리 섹션 정보'
                ret['modal'] = json.dumps(data, indent=4, ensure_ascii=False)
        elif command == 'clear':
            path = arg1
            self.task_interface('clear', (path,))
            ret = {'ret':'success', 'msg':'명령을 전달하였습니다. 잠시 후 결과 알림을 확인하세요.'}
        elif command == 'system_agents':
            data = PlexWebHandle.system_agents(url=arg1, token=arg2)            
            try: data = xmltodict.parse(data)
            except ExpatError: data = json.loads(data)
            ret['title'] = 'System'
            ret['modal'] = json.dumps(data, indent=4, ensure_ascii=False)
        elif command == 'version':
            url = arg1
            token = arg2
            msg = f"SjvaAgent : {PlexWebHandle.get_sjva_agent_version(url=url, token=token)}<br>"
            regex = re.compile("VERSION\s=\s'(?P<version>.*?)'")
            text = requests.get('https://raw.githubusercontent.com/soju6jan/SjvaAgent.bundle/main/Contents/Code/version.py').text
            match = regex.search(text)
            if match:
                msg += u'<br>SjvaAgent (최신) : ' + match.group('version')
            return jsonify({'title':'Agent', 'modal':msg})
        elif command == 'agent_update':
            self.task_interface('agent_update', ('SjvaAgent',True))
        return jsonify(ret)      











    def task_interface(self, command, *args):
        def func():
            time.sleep(1)
            self.task_interface2(command, *args)
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()


    def task_interface2(self, command, *args):
        if command == 'size' or command == 'size_ret':
            func = Task.get_size
        elif command == 'backup':
            func = Task.backup
        elif command == 'clear' or command == 'clear_ret':
            func = Task.clear
        elif command == 'agent_update':
            func = Task.agent_update
        
        ret = self.start_celery(func, None, *args)

        if command == 'size':
            modal_data = {
                'title' : 'Size',
                'data' : f"경로 : {ret['target']}\n크기 : {ret['sizeh']}",
            }
            logger.debug(d(modal_data))
            F.socketio.emit("modal", modal_data, namespace='/framework', broadcast=True)    
        elif command == 'size_ret':
            return ret
        elif command == 'backup':
            if ret['ret'] == 'success':
                noti_data = {'type':'info', 'msg' : f"경로 : {ret['target']}<br>복사하였습니다."}
            else:
                noti_data = {'type':'danger', 'msg' : f"백업에 실패하였습니다.<br>{ret['log']}"}
            F.socketio.emit("notify", noti_data, namespace='/framework', broadcast=True)    
        elif command == 'clear':
            noti_data = {'type':'info', 'msg' : f"경로 : {ret['target']}<br>크기 : {ret['sizeh']}"}
            F.socketio.emit("notify", noti_data, namespace='/framework', broadcast=True) 
        elif command == 'clear_ret':
            return ret
        elif command == 'agent_update':
            if args[0][1]:
                modal_data = {
                    'title' : 'Agent Update Result',
                    'data' : d(ret),
                }
                #P.logger.error(ret)
                F.socketio.emit("modal", modal_data, namespace='/framework', broadcast=True)    



