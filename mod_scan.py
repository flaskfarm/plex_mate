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
            f"{self.name}_plex_use": "True",
            f"{self.name}_shyni_use": "False",
            f"{self.name}_shyni_path_rule": "",
        }
        self.web_list_model = ModelScanItem
        self.set_page_list([BrowserPage, TrashPage])

    def migration(self):
        # scan_item에 샤이니 대상 상태 컬럼 보장 — 실제 컬럼 존재로 판단(멱등).
        # binds URL 문자열 파싱 금지(웹훅 migration에서 상대경로 오해석 전례).
        try:
            from sqlalchemy import inspect, text
            with F.app.app_context():
                engine = F.db.engines[P.package_name] if hasattr(F.db, 'engines') else F.db.get_engine(F.app, bind=P.package_name)
                insp = inspect(engine)
                if 'scan_item' in insp.get_table_names():
                    cols = [c['name'] for c in insp.get_columns('scan_item')]
                    with engine.begin() as conn:
                        if 'shyni_status' not in cols:
                            conn.execute(text('ALTER TABLE scan_item ADD shyni_status VARCHAR'))
                        if 'shyni_job_id' not in cols:
                            conn.execute(text('ALTER TABLE scan_item ADD shyni_job_id VARCHAR'))
                    if 'shyni_status' not in cols:
                        P.logger.info('[Scan] migration: scan_item.shyni_status/shyni_job_id 컬럼 추가')
        except Exception as e:
            P.logger.error(f'[Scan] migration 오류: {e}')


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
                PlexWebHandle.path_scan(target_section_id, target)
                ret.update({
                    'target_section_id': target_section_id,
                    'scanner': scanner,
                    'target': target,
                })
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
            result = vfs_refresh(target, recursive, async_)
            ret.update(result)
            ret.update({
                'recursive': recursive,
                'async': async_,
                'target': target,
            })
        else:
            return {'ret':'fail', 'msg':'Bad request'}, 400
        return jsonify(ret)


    def plugin_load(self):
        def func():
            self.start_celery(Task.start)
        thread = threading.Thread(target=func, args=())
        thread.daemon = True
        thread.start()


    def setting_save_after(self, changes: list) -> None:
        '''override'''
        super().setting_save_after(changes)
        for page in self.page_list:
            page.setting_save_after(changes)
