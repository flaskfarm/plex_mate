from .model_scan import ModelScanItem
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *

name = 'scan'

class Task:
    scan_queue = None
    scan_thread = None
    filecheck_thread = None
    current_scan_count = 0

    @F.celery.task
    def start():
        ModelScanItem.set_status_incompleted_to_ready()
        if Task.scan_queue is None:
            Task.scan_queue = queue.Queue()
        if Task.scan_thread is None:
            Task.scan_thread = threading.Thread(target=Task.scan_thread_function, args=())
            Task.scan_thread.daemon = True  
            Task.scan_thread.start()
        if Task.filecheck_thread == None:
            Task.filecheck_thread = threading.Thread(target=Task.filecheck_thread_function, args=())
            Task.filecheck_thread.daemon = True  
            Task.filecheck_thread.start()
            P.logger.info("PLEX SCAN 대기")
            Task.scan_thread.join()
 

    def __check_media_part_data(db_item):
        media_part_data = PlexDBHandle.get_media_parts(db_item.target)

        if len(media_part_data) == 1:
            db_item.mediapart_id = media_part_data[0]['id']
            db_item.meta_info = PlexDBHandle.get_info_by_part_id(media_part_data[0]['id'])
            db_item.set_status('FINISH_ADD_ALREADY_IN_DB', save=True)
            return True
        return False
        
        
    def filecheck_thread_function():
        while True:
            items = ModelScanItem.get_list_by_status('READY')
            #logger.info(f"filecheck_thread_function : {len(items)}")
            for item in items:
                try:
                    if item.mode == 'ADD':
                        item.filecheck_count += 1
                        now = datetime.now()
                        if item.section_id == None:
                            section_info = PlexDBHandle.get_section_info_by_filepath(item.target)
                            if section_info != None:
                                item.section_id = section_info['section_id']
                                item.section_type = section_info['section_type']
                            else:
                                item.set_status('FINISH_NOT_FIND_LIBRARY', save=True)
                                continue
                        if os.path.exists(item.target):
                            if os.path.isfile(item.target):
                                item.target_type = 'FILE'
                                item.scan_folder = os.path.dirname(item.target)

                                if Task.__check_media_part_data(item):
                                    continue

                            elif os.path.isdir(item.target):
                                item.target_type = 'FOLDER'
                                item.scan_folder = item.target
                            
                            for queue_item in ModelScanItem.queue_list:
                                if queue_item.scan_folder == item.scan_folder and queue_item.mode == item.mode:
                                    item.set_status("FINISH_ALREADY_IN_QUEUE")
                                    break
                            else:
                                item.set_status("ENQUEUE_ADD_FIND")
                                item.init_for_queue()
                                Task.scan_queue.put(item)

                        else:
                            if item.created_time + timedelta(minutes=P.ModelSetting.get_int("scan_max_wait_time")) < now:
                                item.set_status("FINISH_TIMEOVER")
                    elif item.mode == 'REFRESH':
                        item.filecheck_count += 1
                        now = datetime.now()
                        if item.section_id == None:
                            section_info = PlexDBHandle.get_section_info_by_filepath(item.target)
                            if section_info != None:
                                item.section_id = section_info['section_id']
                                item.section_type = section_info['section_type']
                            else:
                                item.set_status('FINISH_NOT_FIND_LIBRARY', save=True)
                                continue
                            
                            metaid = PlexDBHandle.get_metaid_by_directory(item.section_id, item.target)
                            if metaid != None:
                                PlexWebHandle.refresh_by_id(metaid)
                                item.set_status('FINISH_REFRESH', save=True)
                                continue
                    elif item.mode in ['REMOVE_FILE', 'REMOVE_FOLDER']:
                        item.filecheck_count += 1
                        now = datetime.now()
                        if item.section_id == None:
                            section_info = PlexDBHandle.get_section_info_by_filepath(item.target)
                            if section_info != None:
                                item.section_id = section_info['section_id']
                                item.section_type = section_info['section_type']
                            else:
                                item.set_status('FINISH_NOT_FIND_LIBRARY', save=True)
                                continue
                        if os.path.exists(item.target) == False:
                            if item.mode == 'REMOVE_FOLDER':
                                item.scan_folder = item.target
                            else:
                                if item.target.startswith('/'):
                                    item.scan_folder = item.target.rsplit('/', 1)[0]
                                else:
                                    item.scan_folder = item.target.rsplit('\\', 1)[0]
                            item.set_status("ENQUEUE_REMOVE")
                            item.init_for_queue()
                            Task.scan_queue.put(item)
                        else:
                            if item.created_time + timedelta(minutes=P.ModelSetting.get_int("scan_max_wait_time")) < now:
                                item.set_status("FINISH_TIMEOVER")
                except Exception as e: 
                    logger.error(f"Exception:{str(e)}")
                    logger.error(traceback.format_exc())
                finally:
                    item.save()
            #P.logger.warning("파일체크 대기")
            for i in range(P.ModelSetting.get_int(f"{name}_filecheck_thread_interval")):
                time.sleep(1)
                #print(i)
            #time.sleep(60)

    def scan_thread_function():
        while True:
            try:
                while True:
                    if Task.current_scan_count < P.ModelSetting.get_int(f"{name}_max_scan_count"):
                        break
                    time.sleep(5)
                db_item = Task.scan_queue.get()
                if db_item.flag_cancel:
                    Task.scan_queue.task_done() 
                    continue
                if db_item is None:
                    Task.scan_queue.task_done() 
                    continue
                
                Task.process_item_add_on_queue(db_item)
                Task.scan_queue.task_done() 
            except Exception as e: 
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())

    """
    def __incompleted_rescan():
        failed_list = ModelScanItem.get_incompleted()
        P.logger.error(len(failed_list))
        for item in failed_list:
            item.init_for_queue()
            Task.scan_queue.put(item)
        return len(failed_list)
    """


    def process_item_add_on_queue(db_item:ModelScanItem):
        try:
            if db_item.mode == 'ADD':
                if Task.__check_media_part_data(db_item):
                    return
            Task.current_scan_count += 1
            PlexBinaryScanner.scan_refresh(db_item.section_id, db_item.scan_folder, callback_function=Task.subprcoess_callback_function, callback_id=f"pm_scan_{db_item.id}")
        except Exception as e:    
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    def subprcoess_callback_function(call_id, mode, log):
        logger.debug(f"[{mode}] [{log}]")
        try:
            db_item = ModelScanItem.get_by_id(call_id.split('_')[-1])
            if mode == 'START':
                db_item.set_status('SCANNING', save=True)
            elif mode == 'END':
                if db_item.target_type == 'FOLDER':
                    db_item.set_status('FINISH_ADD_FOLDER', save=True)
                    PlexDBHandle.update_show_recent()
                    Task.current_scan_count += -1
                else:
                    if Task.__check_media_part_data(db_item):
                        db_item.set_status('FINISH_ADD', save=True)
                        PlexDBHandle.update_show_recent()
                    Task.current_scan_count += -1
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
 
 