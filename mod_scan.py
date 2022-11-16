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
            f"{self.name}_db_version": "6",
            f"{self.name}_max_scan_count": "2",
            #f"{self.name}_incompleted_rescan": "False",
            f"{self.name}_max_wait_time": "10",
            f"{self.name}_mode": "bin",
            f"{self.name}_manual_target": "",
            f"{self.name}_filecheck_thread_interval": "60",
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
        
        self.start_celery(Task.start)
        #Task.start()

        
    def migration(self):
        try:
            with F.app.app_context():
                import sqlite3
                db_file = F.app.config['SQLALCHEMY_BINDS'][P.package_name].split('?')[0].replace('sqlite:///', '')
                if P.ModelSetting.get(f'{name}_db_version') == '1':
                    connection = sqlite3.connect(db_file)
                    cursor = connection.cursor()
                    query = f'ALTER TABLE scan_item ADD metadata_type VARCHAR'
                    cursor.execute(query)
                    query = f'ALTER TABLE scan_item ADD mediapart_id VARCHAR'
                    cursor.execute(query)
                    query = f'ALTER TABLE scan_item ADD metadata_item_id VARCHAR'
                    cursor.execute(query)
                    query = f'ALTER TABLE scan_item ADD show_metadata_item_id VARCHAR'
                    cursor.execute(query)
                    query = f'ALTER TABLE scan_item ADD metadata_title VARCHAR'
                    cursor.execute(query)
                    connection.close()
                    P.ModelSetting.set(f'{name}_db_version', '2')
                    db.session.flush()
                if P.ModelSetting.get(f'{name}_db_version') == '2':
                    connection = sqlite3.connect(db_file)
                    cursor = connection.cursor()
                    query = f'ALTER TABLE scan_item ADD metadata_title VARCHAR'
                    cursor.execute(query)
                    connection.close()
                    P.ModelSetting.set(f'{name}_db_version', '3')
                    db.session.flush()
                if P.ModelSetting.get(f'{name}_db_version') == '3':
                    connection = sqlite3.connect(db_file)
                    cursor = connection.cursor()
                    query = f'ALTER TABLE scan_item ADD meta_info VARCHAR'
                    cursor.execute(query)
                    connection.close()
                    P.ModelSetting.set(f'{name}_db_version', '4')
                    db.session.flush()
                if P.ModelSetting.get(f'{name}_db_version') == '4':
                    connection = sqlite3.connect(db_file)
                    cursor = connection.cursor()
                    query = f'ALTER TABLE scan_item ADD section_id VARCHAR'
                    cursor.execute(query)
                    query = f'ALTER TABLE scan_item ADD section_type VARCHAR'
                    cursor.execute(query)
                    connection.close()
                    P.ModelSetting.set(f'{name}_db_version', '5')
                    db.session.flush()
                if P.ModelSetting.get(f'{name}_db_version') == '5':
                    connection = sqlite3.connect(db_file)
                    cursor = connection.cursor()
                    query = f'ALTER TABLE scan_item ADD callback VARCHAR'
                    cursor.execute(query)
                    connection.close()
                    P.ModelSetting.set(f'{name}_db_version', '6')
                    db.session.flush()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
