import threading

from .model_scan import ModelScanItem
from .setup import *
from .task_scan import Task
from .extensions import check_timeover, BrowserPage, TrashPage, vfs_refresh
from .plex_web import PlexWebHandle

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
            f"{self.name}_use_web_request": "False",
            f"{self.name}_web_sections": "",
            f"{self.name}_use_vfs_refresh": "False",
            f"{self.name}_vfs_change_rule": "/mnt/gds2/GDRIVE|/GDRIVE|172.17.0.1:5275\n/mnt/mydrive|/sample/172.17.0.1:5524",
            f"{self.name}_max_scan_time": "60",
            f"{self.name}_timeover_reset_range": "0~0",
            f"{self.name}_refresh_after_scanning": "True",
        }
        self.web_list_model = ModelScanItem
        self.set_page_list([BrowserPage, TrashPage])


    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'manual':
            P.ModelSetting.set(f"{self.name}_manual_target", arg2)
            ModelScanItem(arg2, mode=arg1).save()
            ret['msg'] = "추가하였습니다."
        elif command == 'check_timeover':
            overs = P.get_module('scan').web_list_model.get_list_by_status('FINISH_TIMEOVER')
            check_timeover(overs, arg1)
            ret['msg'] = '실행했습니다.'
        elif command == 'retry_scan':
            ModelScanItem.get_by_id(arg1).set_status('READY', save=True)
            ret['msg'] = 'READY로 변경합니다.'
        return jsonify(ret)


    def process_api(self, sub, req):
        ret = {'ret':'success'}
        if sub == 'do_scan':
            target = req.form['target']
            target_section_id = req.form.get('target_section_id') or 0
            mode = req.form.get('mode') or 'ADD'
            callback_id = req.form.get('callback_id')
            callback_url = req.form.get('callback_url')
            scanner = req.form.get('scanner')
            if scanner == 'web':
                th = threading.Thread(target=PlexWebHandle.path_scan, args=(target_section_id, target))
                th.daemon = True
                th.start()
                ret['msg'] = f'{target_section_id=} {scanner=} {target=}'
            else:
                #P.logger.warning(d(req.form))
                ModelScanItem(
                    target,
                    mode = mode,
                    target_section_id = target_section_id,
                    callback_id = callback_id,
                    callback_url = callback_url,
                ).save()
                ret['msg'] = f'{mode=} {target=}'
        elif sub == 'manual_refresh':
            meta_id = req.form.get('metadata_item_id')
            if not meta_id:
                return jsonify({'ret': 'fail', 'msg': 'id 가 존재하지 않습니다.'})
            ret = {'ret':'success', 'msg': f'{meta_id} 수신 성공'}
            PlexWebHandle.manual_refresh(meta_id, plugin_instance=self)
        elif sub == 'vfs_refresh':
            target = req.form.get('target')
            recursive = (req.form.get('recursive') == 'true') or False
            async_ = (req.form.get('async') == 'true') or False
            th = threading.Thread(target=vfs_refresh, args=(target, recursive, async_))
            th.daemon = True
            th.start()
            ret['msg'] = f'{recursive=} async={async_} {target=}'
        else:
            return {'ret':'fail', 'msg':'Bad request'}, 400
        return jsonify(ret)


    def plugin_load(self):
        def func():
            self.start_celery(Task.start)
        thread = threading.Thread(target=func, args=())
        thread.daemon = True
        thread.start()
