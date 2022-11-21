from framework import app, path_app_root
from support import d

from .model_periodic import ModelPeriodicItem
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *
from .task_periodic import Task

#########################################################

class ModulePeriodic(PluginModuleBase):
    

    def __init__(self, P):
        super(ModulePeriodic, self).__init__(P, name='periodic', first_menu='list')
        self.db_default = {
            f'{self.name}_db_version' : '1',
            f'{self.name}_last_list_option' : '',
        }
        self.web_list_model = ModelPeriodicItem

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        try:
            arg['base_path_config'] = ToolUtil.make_path(P.ModelSetting.get('base_path_config'))
            arg['library_list'] = PlexDBHandle.library_sections()
            return render_template(f'{P.package_name}_{self.name}_{sub}.html', arg=arg)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return render_template('sample.html', title=f"{P.package_name}/{self.name}/{sub}")

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'task_sched':
            idx = int(arg1)
            flag = (arg2 == 'true')
            job_id = f'{self.P.package_name}_periodic_{arg1}'
            if flag and F.scheduler.is_include(job_id):
                ret['msg'] = '이미 스케쥴러에 등록되어 있습니다.'
            elif flag and F.scheduler.is_include(job_id) == False:
                result = self.sched_add(idx)
            elif flag == False and F.scheduler.is_include(job_id):
                result = F.scheduler.remove_job(job_id)
                ret['msg'] = '스케쥴링 취소'
            elif flag == False and F.scheduler.is_include(job_id) == False:
                ret['msg'] = '등록되어 있지 않습니다.'
        elif command == 'get_tasks':
            section_list = PlexDBHandle.library_sections()
            #logger.debug(d(section_list))
            tasks = self.get_jobs()
            for idx, task in enumerate(tasks):
                for section in section_list:
                    if str(task['섹션ID']) ==  str(section['id']):
                        task['section_title'] = section['name']
                        break
            ret = {'data' : tasks}
        elif command == 'all_sched_add':
            tasks = self.get_jobs()
            for idx, item in enumerate(tasks):
                if item.get('스케쥴링', '등록') == '등록':
                    self.sched_add(idx, item=item)
            ret['msg'] = 'Success'
        elif command == 'all_sched_remove':
            tasks = self.get_jobs()
            for idx, item in enumerate(tasks):
                if F.scheduler.is_include(item['job_id']):
                    F.scheduler.remove_job(item['job_id'])
            ret['msg'] = 'Success'
        elif command == 'task_execute':
            result = self.one_execute(int(arg1))
            ret['data'] = result
        elif command == 'kill':
            ret = self.kill(arg1)
        elif command == 'remove_no_append_data':
            ret = ModelPeriodicItem.remove_no_append_data()
        return jsonify(ret)


    def plugin_load(self):
        ModelPeriodicItem.set_terminated()
        self.start()


    #########################################################

    def sched_add(self, idx, item=None):
        try:
            if item is None:
                item = self.get_jobs()[idx]
            if F.scheduler.is_include(item['job_id']):
                logger.debug(f"{item['섹션ID']} include scheduler!")
                return
            job = Job(self.P.package_name, item['job_id'], item['주기'], self.job_function, item['설명'], args=(idx,))
            F.scheduler.add_job_instance(job)
            return True
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())   
        return False


    def kill(self, db_item_id):
        import psutil
        try:
            db_item = ModelPeriodicItem.get_by_id(db_item_id)
            logger.debug(d(db_item.as_dict()))
            if db_item is not None:
                
                process = psutil.Process(int(db_item.process_pid))
                logger.debug(process)
                logger.debug(process.name())
                if process.name().find('Plex Media Scanner') != -1:
                    for proc in process.children(recursive=True):
                        proc.kill()
                    process.kill()
                    db_item.status = 'user_stop'
                    db_item.save()
                    ret = {'ret':'success', 'msg':'정상적으로 중지하였습니다.'}
                else:
                    ret = {'ret':'success', 'msg':'Plex Media Scanner 파일이 아닙니다.'}
        except psutil.NoSuchProcess:
            ret = {'ret':'danger', 'msg':'실행중인 프로세스가 아닙니다.'}
            if db_item is not None:
                db_item.status = 'terminated'
                db_item.save()
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            ret = {'ret':'danger', 'msg':str(e)} 
        return ret




    def start(self):
        #logger.error("START")
        data = self.get_jobs()

        for idx, item in enumerate(data):
            if item.get('스케쥴링', '등록') == '등록':
                self.sched_add(idx, item=item)
                 

    @classmethod
    def get_jobs(cls):
        return Task.get_jobs()


    def job_function(self, idx):
        logger.warning(f"job_function IDX : {idx}")
        data = self.get_jobs()[idx]
        if data.get('스캔모드', None) == '웹':
            PlexWebHandle.section_scan(data['섹션ID'])
            logger.debug(f"스캔모드 : 웹 실행")
            logger.debug(data)
            return
        
        self.start_celery(Task.start, None, *(idx,'scheduler'))
        #Task.start(idx)
        #if app.config['config']['use_celery']:
        #    result = Task.start.apply_async((idx,'scheduler'))
        #    ret = result.get()
        #else:
        #    ret = Task.start(idx, 'scheduler')
        #    #ret = func(self, *args)

    def one_execute(self, idx):
        try:
            job_id = f'{P.package_name}_periodic_{idx}'
            if F.scheduler.is_include(job_id):
                if F.scheduler.is_running(job_id):
                    ret = 'is_running'
                else:
                    F.scheduler.execute_job(job_id)
                    ret = 'scheduler'
            else:
                def func():
                    time.sleep(2)
                    self.job_function(idx)
                t = threading.Thread(target=func, args=())
                t.daemon = True
                t.start()
                ret = 'thread'
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret = 'fail'
        return ret