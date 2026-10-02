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
        logger.info(f"시작: {args}")
        location, meta_type, folder, dryrun, mode = args
        self.data['list'] = []
        self.data['status']['is_working'] = 'run'
        self.current_seq_info = None
        self.refresh_data()
        P.ModelSetting.set(f'{self.parent.name}_{self.name}_task_stop_flag', 'False')
        
        try:
            if mode == 'step_all':
                steps_to_run = ['step1', 'step2', 'step3']
                step_names = {'step1': '1단계', 'step2': '2단계', 'step3': '3단계'}
            else:
                steps_to_run = [mode]
                step_names = {mode: mode}

            total_steps = len(steps_to_run)
            for idx, cur_mode in enumerate(steps_to_run):
                if P.ModelSetting.get_bool(f'{self.parent.name}_{self.name}_task_stop_flag'):
                    logger.warning(f"번들 순차 실행 중 사용자에 의해 중지 플래그 감지: {cur_mode}")
                    self.data['status']['is_working'] = 'stop'
                    break

                step_title = step_names.get(cur_mode, cur_mode)
                if mode == 'step_all':
                    logger.info(f"[번들 순차 실행 {idx+1}/{total_steps}단계: {step_title}] 시작")
                    self.current_seq_info = {'idx': idx, 'total': total_steps, 'name': step_title}
                    self.data['status']['seq_step'] = f'{idx+1}/{total_steps}단계: {step_title}'
                else:
                    self.current_seq_info = None
                    self.data['status'].pop('seq_step', None)

                if idx > 0:
                    self.data['list'] = []
                self.data['status']['is_working'] = 'run'
                self.refresh_data()

                step_args = (location, meta_type, folder, dryrun, cur_mode)
                ret = self.start_celery(Task.start, self.receive_from_task, *step_args)
                logger.info(f"{cur_mode} 완료 결과: {ret}")

                if ret == 'stop' or P.ModelSetting.get_bool(f'{self.parent.name}_{self.name}_task_stop_flag'):
                    self.data['status']['is_working'] = 'stop'
                    break

                if idx + 1 < total_steps:
                    time.sleep(2)

            if self.data['status']['is_working'] != 'stop':
                self.data['status']['is_working'] = 'wait'
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            self.data['status']['is_working'] = 'exception'
        finally:
            self.current_seq_info = None
            self.data['status'].pop('seq_step', None)
            import datetime
            now_str = datetime.datetime.now().strftime('%m/%d %H:%M:%S')
            target_str = f"{location}" + (f" ({meta_type})" if location == 'Metadata' else "") + f" [{folder}]"
            self.data['status']['last_work'] = {
                'section_name': target_str,
                'step_name': '1~3단계 전체 순차' if mode == 'step_all' else step_names.get(mode, mode),
                'time': now_str,
                'remove_count': self.data['status'].get('remove_count', 0),
                'remove_size': self.data['status'].get('remove_size', 0)
            }
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
                if getattr(self, 'current_seq_info', None):
                    info = self.current_seq_info
                    self.data['status']['seq_step'] = f"{info['idx']+1}/{info['total']}단계: {info['name']}"
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