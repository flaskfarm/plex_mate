from .plex_db import PlexDBHandle
from .setup import *
from .task_clear_movie import Task as TaskMovie
from .task_clear_music import Task as TaskMusic
from .task_clear_show import Task as TaskShow

logger = P.logger


class PageClearLibraryBase(PluginPageBase):
    
    def __init__(self, P, parent, name):
        super(PageClearLibraryBase, self).__init__(P, parent, name=name)
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_task_stop_flag' : 'False',
        }
        self.data = {
            'list' : [],
            'status' : {'is_working':'wait'}
        }
        default_route_socketio_page(self)


    def process_menu(self, req):
        arg = P.ModelSetting.to_dict()
        if self.name == 'movie':
            arg['library_list'] = PlexDBHandle.library_sections(section_type=1)
        elif self.name == 'show':
            arg['library_list'] = PlexDBHandle.library_sections(section_type=2)
        elif self.name == 'music':
            arg['library_list'] = PlexDBHandle.library_sections(section_type=8) 
        return render_template(f'{P.package_name}_{self.parent.name}_{self.name}.html', arg=arg)
        

    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {}
            if command.startswith('start'):
                if self.data['status']['is_working'] == 'run':
                    ret = {'ret':'warning', 'msg':'실행중입니다.'}
                else:
                    if arg3 is not None:
                        self.task_interface(command, arg1, arg2, arg3)
                    else:
                        self.task_interface(command, arg1, arg2)
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
        command = args[0]
        library_section = PlexDBHandle.library_section(args[1])
        self.data['list'] = []
        self.data['status']['is_working'] = 'run'
        self.current_seq_info = None
        self.refresh_data()
        P.ModelSetting.set(f'{self.parent.name}_{self.name}_task_stop_flag', 'False')
        try:
            config = P.load_config()
            if library_section['section_type'] == 1:
                func = TaskMovie.start
                all_steps = ['start1', 'start2', 'start3']
                step_names = {'start1': '1단계', 'start2': '2단계', 'start3': '3단계'}
            elif library_section['section_type'] == 2:
                func = TaskShow.start
                all_steps = ['start1', 'start21', 'start22', 'start3']
                step_names = {'start1': '1단계', 'start21': '2-1단계', 'start22': '2-2단계', 'start3': '3단계'}
            elif library_section['section_type'] == 8:
                func = TaskMusic.start
                all_steps = ['start1', 'start2', 'start3']
                step_names = {'start1': '1단계', 'start2': '2단계', 'start3': '3단계'}
            else:
                all_steps = [command]
                step_names = {command: command}

            try:
                self.list_max = config['웹페이지에 표시할 세부 정보 갯수']
            except:
                self.list_max = 200

            if command == 'start_all':
                steps_to_run = all_steps
            else:
                steps_to_run = [command]

            total_steps = len(steps_to_run)
            for idx, cur_cmd in enumerate(steps_to_run):
                if P.ModelSetting.get_bool(f'{self.parent.name}_{self.name}_task_stop_flag'):
                    logger.warning(f"순차 실행 중 사용자에 의해 중지 플래그 감지: {cur_cmd}")
                    self.data['status']['is_working'] = 'stop'
                    break

                step_title = step_names.get(cur_cmd, cur_cmd)
                if command == 'start_all':
                    logger.info(f"[순차 실행 {idx+1}/{total_steps}단계: {step_title}] 시작: {cur_cmd}")
                    self.current_seq_info = {'idx': idx, 'total': total_steps, 'name': step_title}
                    self.data['status']['seq_step'] = f'{idx+1}/{total_steps}단계: {step_title}'
                else:
                    self.current_seq_info = None
                    self.data['status'].pop('seq_step', None)

                if idx > 0:
                    self.data['list'] = []
                self.data['status']['is_working'] = 'run'
                self.refresh_data()

                step_args = (cur_cmd,) + args[1:]
                ret = self.start_celery(func, self.receive_from_task, *step_args)
                logger.info(f"{cur_cmd} 완료 결과: {ret}")

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
            self.data['status']['is_working'] = 'wait'
        finally:
            self.current_seq_info = None
            self.data['status'].pop('seq_step', None)
            import datetime
            now_str = datetime.datetime.now().strftime('%m/%d %H:%M:%S')
            sec_title = library_section.get('name', f"ID:{args[1]}") if library_section else f"ID:{args[1]}"
            self.data['status']['last_work'] = {
                'section_name': sec_title,
                'step_name': '1~3단계 전체 순차' if command == 'start_all' else step_names.get(command, command),
                'time': now_str,
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
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
    


class PageClearLibraryShow(PageClearLibraryBase):
    def __init__(self, P, parent):
        super(PageClearLibraryShow, self).__init__(P, parent, 'show')

class PageClearLibraryMovie(PageClearLibraryBase):
    def __init__(self, P, parent):
        super(PageClearLibraryMovie, self).__init__(P, parent, 'movie')

class PageClearLibraryMusic(PageClearLibraryBase):
    def __init__(self, P, parent):
        super(PageClearLibraryMusic, self).__init__(P, parent, 'music')