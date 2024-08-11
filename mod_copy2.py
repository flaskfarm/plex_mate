from .plex_db import PlexDBHandle
from .setup import *
from .task_copy2 import Task


class ModuleCopy2(PluginModuleBase):
    def __init__(self, P):
        super(ModuleCopy2, self).__init__(P, name='copy2', first_menu='copy')
        self.set_page_list([PageCopy2Copy, PageCopy2Status])
        

class PageCopy2Copy(PluginPageBase):
    
    def __init__(self, P, parent):
        super(PageCopy2Copy, self).__init__(P, parent, name='copy')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_path_source_db' : '',
            f'{self.parent.name}_{self.name}_source_section_id' : '',
            f'{self.parent.name}_{self.name}_path_source_root_path' : '',
            f'{self.parent.name}_{self.name}_path_target_root_path' : '',
            f'{self.parent.name}_{self.name}_task_stop_flag' : 'False',
        }
        self.data = {
            'list' : [],
            'status' : {'is_working':'wait'}
        }
        default_route_socketio_page(self)


    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'source_section':
                data = PlexDBHandle.library_sections(db_file=arg1)
                ret['json'] = data
                ret['title'] = '소스 섹션'
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_path_source_db', arg1)
            elif command == 'target_section_id':
                data = PlexDBHandle.library_sections()
                ret['json'] = data
                ret['title'] = 'Plex Section'
            elif command == 'target_section_location_id':
                data = PlexDBHandle.select_arg('SELECT * FROM section_locations WHERE library_section_id = ?', (arg1,))
                ret['json'] = data
                ret['title'] = 'Plex Section Location'
            elif command == 'select_source_locations':
                data = PlexDBHandle.select('SELECT * FROM section_locations', db_file=arg1)
                ret['json'] = data
                ret['title'] = '소스 Section Locations'
            elif command == 'select_target_locations':
                data = PlexDBHandle.select('SELECT * FROM section_locations')
                ret['json'] = data
                ret['title'] = '타겟 Section Locations'
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})



class PageCopy2Status(PluginPageBase):
    
    def __init__(self, P, parent):
        super(PageCopy2Status, self).__init__(P, parent, name='status')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_task_stop_flag' : 'False',
        }
        self.data = {
            'list' : [],
            'status' : {'is_working':'wait'}
        }
        self.list_max = 300
        default_route_socketio_page(self)


    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'start':
                if P.ModelSetting.get(f'{self.parent.name}_{self.name}_path_source_db') == '' or P.ModelSetting.get(f'{self.parent.name}_{self.name}_path_source_section_id') == '' or P.ModelSetting.get(f'{self.parent.name}_{self.name}_path_source_root_path') == '' or P.ModelSetting.get(f'{self.parent.name}_{self.name}_path_target_root_path'):
                    ret = {'ret':'warning', 'msg':'설정을 저장 후 시작하세요.'}
                else:
                    if self.data['status']['is_working'] == 'run':
                        ret = {'ret':'warning', 'msg':'실행중입니다.'}
                    else:
                        self.task_interface(command)
                        ret = {'ret':'success', 'msg':'작업을 시작합니다.'}
            elif command == 'stop':
                if self.data['status']['is_working'] == 'run':
                    P.ModelSetting.set(f'{self.parent.name}_{self.name}_task_stop_flag', 'True')
                    ret = {'ret':'success', 'msg':'잠시 후 중지됩니다.'}
                else:
                    ret = {'ret':'warning', 'msg':'대기중입니다.'}
            elif command == 'refresh':
                self.refresh_data()
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})
    

    def task_interface(self, *args):
        def func():
            time.sleep(1)
            self.task_interface2(*args)
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()


    def task_interface2(self, *args):
        self.data['list'] = []
        self.data['status']['is_working'] = 'run'
        self.refresh_data()
        P.ModelSetting.set(f'{self.parent.name}_{self.name}_task_stop_flag', 'False')
        try:
            ret = self.start_celery(Task.start, self.receive_from_task, *args)
            self.data['status']['is_working'] = ret
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            self.data['status']['is_working'] = 'wait'
        self.refresh_data()


    def refresh_data(self, index=-1):
        if index == -1:
            self.socketio_callback('refresh_all', self.data)
        else:
            self.socketio_callback('refresh_one', {'one' : self.data['list'][index], 'status' : self.data['status']})
        

    def receive_from_task(self, arg, celery=True):
        try:
            result = None
            if celery:
                if arg['status'] == 'PROGRESS':
                    result = arg['result']
            else:
                result = arg
            if result is not None:
                self.data['list'].append(result)
                self.refresh_data()
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
