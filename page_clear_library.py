from .plex_db import PlexDBHandle
from .setup import *
from .task_clear_movie import Task as TaskMovie
from .task_clear_music import Task as TaskMusic
from .task_clear_show import Task as TaskShow


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
        logger.warning(args)
        library_section = PlexDBHandle.library_section(args[1])
        self.data['list'] = []
        self.data['status']['is_working'] = 'run'
        self.refresh_data()
        P.ModelSetting.set(f'{self.parent.name}_{self.name}_task_stop_flag', 'False')
        try:
            config = P.load_config()
            if library_section['section_type'] == 1:
                func = TaskMovie.start
            elif library_section['section_type'] == 2:
                func = TaskShow.start
            elif library_section['section_type'] == 8:
                func = TaskMusic.start
            try:
                self.list_max = config['웹페이지에 표시할 세부 정보 갯수']
            except:
                self.list_max = 200
            ret = self.start_celery(func, self.receive_from_task, *args)
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
                self.data['status'] = result['status']
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