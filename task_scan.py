from support import SupportSubprocess

from .extensions import check_scanning, vfs_forget, vfs_refresh
from .model_scan import ModelScanItem
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *

name = 'scan'
logger = P.logger


class Task:
    scan_queue = None
    scan_thread = None
    filecheck_thread = None
    current_scan_count = 0

    @F.celery.task
    def start():
        ModelScanItem.set_status_incompleted_to_ready()
        for db_item in ModelScanItem.get_list_by_status('FINISH_SCANNING'):
            if db_item.mode not in ['ADD']:
                continue
            db_item.set_status('READY', save=True)
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
        rows: list[dict] = PlexDBHandle.get_media_parts(db_item.target)
        if rows:
            db_item.mediapart_id = rows[0]['id']
            db_item.meta_info = PlexDBHandle.get_info_by_part_id(rows[0]['id'])
        else:
            rows = PlexDBHandle.get_media_streams_file_like(db_item.target)
            P.logger.warning(rows)
            if rows:
                db_item.meta_info = PlexDBHandle.get_info_by_stream_id(rows[0]['id'])
        if rows:
            db_item.set_status('FINISH_ADD_ALREADY_IN_DB', save=True)
            return True
        return False


    def filecheck_thread_function():
        while True:
            items = ModelScanItem.get_list_by_status('READY')
            vfs_rules = P.ModelSetting.get_list('scan_vfs_change_rule')
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

                        if P.ModelSetting.get_bool('scan_use_vfs_refresh') and not os.path.exists(item.target):
                            try:
                                vfs_refresh(item.target)
                                '''
                                rclone = F.PluginManager.get_plugin_instance('rclone')
                                cmd = [rclone.ModelSetting.get('rclone_path'), 'rc', 'vfs/refresh']

                                for rule in vfs_rules:
                                    tmps = rule.split('|')
                                    if len(tmps) != 3 and len(tmps) != 5: continue
                                    cmd += [f"--rc-addr={tmps[2]}", f"_async=false"]
                                    if len(tmps) == 5: cmd += [f"--rc-user={tmps[3]}", f"--rc-pass={tmps[4]}"]
                                    if item.target.startswith(tmps[0]) == False:
                                        continue
                                    remote = item.target.replace(tmps[0], tmps[1]).replace('\\', '/').replace('//', '/')

                                    # 현시점 파일인지, 폴더인지 모름
                                    # 특히나 1회차면?
                                    # 부모를 넣어서 OK를 받자
                                    call_remote = remote.rsplit('/', 1)[0]
                                    is_ok = False
                                    while True:
                                        cmd.append(f'dir={call_remote}')
                                        result = SupportSubprocess.execute_command_return(cmd)
                                        logger.info(' '.join(cmd))
                                        logger.debug(f"vfs/refresh : {result}")
                                        vfs_ret = json.loads(result['log'].replace('\n', ''))
                                        logger.info(vfs_ret['result'][call_remote])

                                        if vfs_ret['result'][call_remote] == 'file does not exist':
                                            # 1회차 일 경우. 더 상위를 한번 호출하면 다음턴에 해결
                                            call_remote = call_remote.rsplit('/', 1)[0]
                                            if call_remote == '':
                                                break
                                            del cmd[-1]
                                        else:
                                            is_ok = True
                                            break
                                    if is_ok:
                                        break
                                '''
                            except Exception as e:
                                logger.error(f"Exception:{str(e)}")
                                logger.error(traceback.format_exc())

                        if os.path.exists(item.target):
                            if os.path.isfile(item.target):
                                item.target_type = 'FILE'
                                item.scan_folder = os.path.dirname(item.target)
                                if Task.__check_media_part_data(item):
                                    continue

                            elif os.path.isdir(item.target):
                                item.target_type = 'FOLDER'
                                item.scan_folder = item.target
                                '''
                                사용자가 "비디오/방송중" 혹은 "영화/제목/가" 처럼 최상위 폴더를 스캔 요청할 경우
                                그만큼 다음 항목의 파일 체크까지 지연되므로 존재하는 경로는 수동으로 vfs/refresh 하도록 유도
                                # recursive=true vfs/refresh
                                if P.ModelSetting.get_bool('scan_use_vfs_refresh'):
                                    try:
                                        cmd[-1] = f'dir={remote}'
                                        cmd.append('recursive=true')
                                        result = SupportSubprocess.execute_command_return(cmd)
                                        logger.info(' '.join(cmd))
                                        logger.debug(f"vfs/refresh2 : {result}")
                                    except Exception as e:
                                        logger.error(f"Exception:{str(e)}")
                                        logger.error(traceback.format_exc())
                                '''

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
                            if os.path.exists(item.target):
                                if os.path.isdir(item.target):
                                    refresh_target = item.target
                                else:
                                    refresh_target = os.path.dirname((item.target))
                                metaid = PlexDBHandle.get_metaid_by_directory(item.section_id, refresh_target)
                                if metaid != None:
                                    PlexWebHandle.refresh_by_id(metaid)
                                    item.set_status('FINISH_REFRESH', save=True)
                                    continue
                                else:
                                    item.set_status('FINISH_NOT_FIND_IN_LIBRARY', save=True)
                            else:
                                item.set_status('NOT_EXIST', save=True)

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
                        if P.ModelSetting.get_bool('scan_use_vfs_refresh'):
                            vfs_forget(item.target)
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
            max_scan_time = P.ModelSetting.get_int('scan_max_scan_time')
            if max_scan_time > 0:
                scannings = ModelScanItem.get_list_by_status('SCANNING')
                check_scanning(scannings, max_scan_time)
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
            if db_item.mode == 'ADD' and Task.__check_media_part_data(db_item):
                pass
            else:
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
                    '''
                    스캔 프로세스가 완료 된 후 대상이 media_part로 등록 되었는지 테스트 후 FINISH_ADD 처리함.
                    만약 info.json 처럼 media_part로 등록되지 못한 경우 테스트를 통과할 수 없음.
                    DB 입력이 지연되면서 아직 등록되지 않았을 수도 있음.
                    SCANNING 항목을 계속 추적하진 않기 때문에 계속 SCANNING 상태로 남아 있게 됨.
                    그럴 경우 동일한 폴더의 다른 파일이 추가되면 스캔되지 않음. (FINISH_ALREADY_IN_QUEUE)
                    새로운 상태 추가
                    FINISH_SCANNING: 스캔은 끝났지만 media_parts 테이블에 파일이 추가됐는지 확인이 안 되는 상태
                    '''
                    if Task.__check_media_part_data(db_item):
                        db_item.set_status('FINISH_ADD', save=True)
                        PlexDBHandle.update_show_recent()
                    else:
                        db_item.set_status('FINISH_SCANNING', save=True)
                    Task.current_scan_count += -1
                # 2024-09-07
                # 이제 bin scanner가 refresh까지 하지 못함. web refresh 하도록 추가
                if db_item.mode == 'ADD':
                    metaid = PlexDBHandle.get_metaid_by_directory(db_item.section_id, db_item.scan_folder)
                    if metaid != None:
                        logger.info(f"스캔: meta resresh {metaid}")
                        PlexWebHandle.refresh_by_id(metaid)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
