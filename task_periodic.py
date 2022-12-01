from support import SupportYaml, d
from tool import ToolUtil

from .model_periodic import ModelPeriodicItem
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .setup import *


class Task(object):
    @classmethod
    def get_jobs(cls):
        config = SupportYaml.read_yaml(ToolUtil.make_path(P.ModelSetting.get('base_path_config')))
        data = config.get('라이브러리 주기적 스캔 목록', None)
        if data is None or type(data) != type([]):
            return []
        for idx, item in enumerate(data):
            item['job_id'] = f'{P.package_name}_periodic_{idx}'
            item['설명'] = item.get('설명', f"섹션: {item['섹션ID']}")
            item['is_include_scheduler'] = str(F.scheduler.is_include(item['job_id']))
        return data

    
    @staticmethod
    @F.celery.task()
    def start(idx, mode):
        try:
            yaml = Task.get_jobs()[idx]

            db_item = ModelPeriodicItem()
            db_item.mode = mode
            db_item.section_id = yaml['섹션ID']
            section_data = PlexDBHandle.library_section(db_item.section_id)
            db_item.section_title = section_data['name']
            db_item.section_type = section_data['section_type']
            db_item.folder = yaml.get('폴더', None)

            query = f"""
            SELECT COUNT(media_parts.id) as cnt, MAX(media_parts.id) as max_part_id
            FROM metadata_items, media_items, media_parts 
            WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND media_parts.file != '' AND metadata_items.library_section_id = ?"""


            tmp = PlexDBHandle.select_arg(query, (db_item.section_id,))[0]
            #logger.error(f"시작 : {tmp}")
            db_item.part_before_max = tmp['max_part_id']
            db_item.part_before_count = tmp['cnt']

            timeout = yaml.get("최대실행시간", None)
            if timeout is not None:
                timeout = int(timeout)*60 
            
            db_item.start_time = datetime.now()
            db_item.status = "working"
            db_item.save()
 
            #process = PlexBinaryScanner.scan_refresh(db_item.section_id, db_item.folder, timeout=timeout, join=False, callback_function=Task.subprcoess_callback_function, callback_id=f"pm_periodic_{db_item.id}")
            process = PlexBinaryScanner.scan_refresh(db_item.section_id, db_item.folder, timeout=timeout, join=False)
            count = 0
            while True:
                count += 1
                time.sleep(0.1)
                if process.process != None:
                    db_item.process_pid = process.process.pid 
                    break
                if count > 600:
                    break

            db_item.process_pid = process.process.pid
            db_item.save()
            process.thread.join()
            db_item.status = "finished"
            db_item.finish_time = datetime.now()
            delta = db_item.finish_time - db_item.start_time
            db_item.duration = delta.seconds
            
            tmp = PlexDBHandle.select_arg(query, (db_item.section_id,))[0]
            #logger.error(f"종료 : {tmp}")
            db_item.part_after_max = tmp['max_part_id']
            db_item.part_after_count = tmp['cnt']
            db_item.part_append_count = db_item.part_after_count - db_item.part_before_count

            query = f"""
            SELECT media_parts.file as filepath, metadata_items.id as metadata_items_id
            FROM metadata_items, media_items, media_parts 
            WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND media_parts.file != '' AND metadata_items.library_section_id = ? AND media_parts.id > ? ORDER BY media_parts.id ASC"""
            tmp = PlexDBHandle.select_arg(query, (db_item.section_id, db_item.part_before_max))
            append_files = []
            for t in tmp:
                append_files.append(f"{t['metadata_items_id']}|{t['filepath']}")

            db_item.append_files = '\n'.join(append_files)
            db_item.save()

            if section_data['section_type'] == 2 and db_item.part_append_count > 0:
                PlexDBHandle.update_show_recent()

        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())


    def subprcoess_callback_function(call_id, mode, log):
        logger.error(f"[{mode}] [{log}]")
        try:
            
            if mode == 'START':
                db_item = ModelPeriodicItem.get_by_id(call_id.split('_')[-1])
                db_item.start_time = datetime.now()
                db_item.status = "working"
                db_item.save()
            
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())