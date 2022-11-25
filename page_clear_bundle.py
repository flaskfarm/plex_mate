from .setup import *
from .task_clear_bundle import Task


class PageClearBundle(PluginPageBase):
    
    def __init__(self, P, parent):
        super(PageClearBundle, self).__init__(P, parent, name='bundle')
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
            ret = {}
            if command == 'start':
                if self.data['status']['is_working'] == 'run':
                    ret = {'ret':'warning', 'msg':'실행중입니다.'}
                else:
                    tmp = arg1.split('_')
                    self.task_interface(tmp[0], tmp[1], tmp[2], arg2, arg3)
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
    

    #########################################################

    def task_interface(self, *args):
        def func():
            time.sleep(1)
            self.task_interface2(*args)
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()
        return th


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
            self.data['status']['is_working'] = 'exception'
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
                self.data['status'] = result['status']
                del result['status']
                if self.list_max != 0:
                    if len(self.data['list']) == self.list_max:
                        self.data['list'] = []
                result['index'] = len(self.data['list'])
                self.data['list'].append(result)
                self.refresh_data(index=result['index'])
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())