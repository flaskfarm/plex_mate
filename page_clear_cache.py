from .setup import *


class PageClearCache(PluginPageBase):
    def __init__(self, P, parent):
        super(PageClearCache, self).__init__(P, parent, name='cache')
        self.db_default = {
            f'{self.parent.name}_{self.name}_auto_start' : 'False',
            f'{self.parent.name}_{self.name}_interval' : '0 5 * * *',
            f'{self.parent.name}_{self.name}_max_size' : '20',
        }
        self.scheduler_desc = 'Plex PhotoTranscoder 삭제 스케쥴링'

    def process_menu(self, req):
        arg = P.ModelSetting.to_dict()
        arg['is_include'] = F.scheduler.is_include(self.get_scheduler_name())
        arg['is_running'] = F.scheduler.is_running(self.get_scheduler_name())
        return render_template(f'{P.package_name}_{self.parent.name}_{self.name}.html', arg=arg)


    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {}
            if command == 'cache_size':
                self.get_module('base').task_interface('size', (P.ModelSetting.get('base_path_phototranscoder'),))
                ret = {'ret':'success', 'msg':'명령을 전달하였습니다. 잠시 후 결과 알림을 확인하세요.'}
            elif command == 'cache_clear':
                self.get_module('base').task_interface('clear', (P.ModelSetting.get('base_path_phototranscoder'),))
                ret = {'ret':'success', 'msg':'명령을 전달하였습니다. 잠시 후 결과 알림을 확인하세요.'}
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})

    def scheduler_function(self):
        logger.error('scheduler_function')
        def func():
            time.sleep(1)
            max_size = P.ModelSetting.get_int(f'{self.parent.name}_{self.name}_max_size')
            do_clear = False
            if max_size == 0:
                do_clear = True
            else:
                ret = self.get_module('base').task_interface2('size_ret', (P.ModelSetting.get('base_path_phototranscoder'),))
                if ret['size'] > max_size * 1024 * 1024 * 1024:
                    do_clear = True
                else:
                    logger.debug(f"삭제패스 - 현재 캐시 크기 : {ret['sizeh']}")
            if do_clear:
                ret = self.get_module('base').task_interface2('clear_ret', (P.ModelSetting.get('base_path_phototranscoder'),))
                logger.debug(f"캐시 삭제 완료 : {ret['size']}")
        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()

