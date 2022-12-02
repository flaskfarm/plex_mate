from .model_scan import ModelScanItem
from .setup import *
from .task_scan import Task

name = 'scan'
class ModuleScan(PluginModuleBase):
    scan_queue = None
    scan_thread = None
    file_exist_thread = None
    current_scan_count = 0

    def __init__(self, P):
        super(ModuleScan, self).__init__(P, name=name, first_menu='setting')
        self.db_default = {
            f"sacn_item_last_list_option": "",
            f"{self.name}_db_version": "1",
            f"{self.name}_max_scan_count": "2",
            #f"{self.name}_incompleted_rescan": "False",
            f"{self.name}_max_wait_time": "10",
            f"{self.name}_mode": "bin",
            f"{self.name}_manual_target": "",
            f"{self.name}_filecheck_thread_interval": "60",
            f"{self.name}_db_delete_day": "30",
            f"{self.name}_db_auto_delete": "True",
        }
        self.web_list_model = ModelScanItem
        

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'manual':
            P.ModelSetting.set(f"{self.name}_manual_target", arg2)
            if arg1 == 'add':
                ModelScanItem(arg2).save()
            elif arg1 == 'remove':
                ModelScanItem(arg2, target_mode="REMOVE").save()
            ret['msg'] = "추가하였습니다."
        return jsonify(ret)
    
    
    def process_api(self, sub, req):
        ret = {'ret':'success'}
        if sub == 'do_scan':
            #P.logger.warning(d(req.form))
            ModelScanItem(
                req.form['target'],
                mode = req.form.get('mode', 'ADD'),
                target_section_id = req.form.get('target_section_id', '0'),
                callback_id = req.form.get('callback_id'),
                callback_url = req.form.get('callback_url'),
            ).save()

        return jsonify(ret)


    def plugin_load(self):
        def func():
            self.start_celery(Task.start)
        thread = threading.Thread(target=func, args=())
        thread.daemon = True
        thread.start()
        
        #Task.start()

        
    
