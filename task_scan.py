from uuid import uuid4

from .setup import *
from .extensions import check_scanning, vfs_forget, vfs_refresh
from .model_scan import ModelScanItem
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .shyni_backend import ShyniBackend

name = 'scan'
logger = P.logger


class Task:
    scan_queue = None
    scan_thread = None
    filecheck_thread = None
    current_scan_count = 0
    scan_count_lock = threading.Lock()
    counted_scan_ids = set()

    @staticmethod
    def _start_scan(scan_id):
        scan_id = str(scan_id)
        with Task.scan_count_lock:
            if scan_id not in Task.counted_scan_ids:
                Task.counted_scan_ids.add(scan_id)
                Task.current_scan_count += 1

    @staticmethod
    def _finish_scan(scan_id):
        scan_id = str(scan_id)
        with Task.scan_count_lock:
            if scan_id in Task.counted_scan_ids:
                Task.counted_scan_ids.remove(scan_id)
                Task.current_scan_count = max(Task.current_scan_count - 1, 0)

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
        rows: list[dict] = PlexDBHandle.get_media_parts(db_item.target)
        if rows:
            db_item.mediapart_id = rows[0]['id']
            db_item.meta_info = PlexDBHandle.get_info_by_part_id(rows[0]['id'])
        elif not os.path.isdir(db_item.target):
            rows = PlexDBHandle.get_media_streams_file_like(db_item.target)
            if rows:
                db_item.meta_info = PlexDBHandle.get_info_by_stream_id(rows[0]['id'])
        if rows:
            db_item.set_status('FINISH_ADD_ALREADY_IN_DB', save=True)
            return True
        return False


    def filecheck_thread_function():
        while True:
            try:
                items = ModelScanItem.get_list_by_status('READY')
                #logger.info(f"filecheck_thread_function : {len(items)}")
                for item in items:
                    try:
                        if item.mode == 'ADD':
                            item.filecheck_count += 1
                            # 샤이니 대상 분기(F절) — FF 마운트의 파일 존재/Plex 준비와 무관하게
                            # 즉시 요청. 파일이 안 보이면 샤이니 서버가 자체적으로 부모 폴더를
                            # non-recursive refresh 하며 대기한다(mode=add + wait).
                            ShyniBackend.request_scan(item)
                            if not P.ModelSetting.get_bool('scan_plex_use'):
                                ShyniBackend.finalize_plex_off(item)
                                continue
                            if item.section_id == None:
                                section_info = PlexDBHandle.get_section_info_by_filepath(item.target)
                                if section_info != None:
                                    item.section_id = section_info['section_id']
                                    item.section_type = section_info['section_type']
                                else:
                                    item.set_status('FINISH_NOT_FIND_LIBRARY', save=True)
                                    continue

                            if P.ModelSetting.get_bool('scan_use_vfs_refresh'):
                                try:
                                    vfs_refresh(item.target)
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

                                for _, queued_scan_folder, queued_mode in ModelScanItem.queue_list:
                                    if queued_scan_folder == item.scan_folder and queued_mode == item.mode:
                                        item.set_status("FINISH_ALREADY_IN_QUEUE")
                                        break
                                else:
                                    item.set_status("ENQUEUE_ADD_FIND")
                                    item.init_for_queue()
                                    Task.scan_queue.put(item)

                            else:
                                max_wait_time = P.ModelSetting.get_int("scan_max_wait_time")
                                if max_wait_time is None:
                                    max_wait_time = 10
                                if item.created_time + timedelta(minutes=max_wait_time) < datetime.now():
                                    item.set_status("FINISH_TIMEOVER")
                        elif item.mode == 'REFRESH':
                            item.filecheck_count += 1
                            # 샤이니 대상 refresh — Plex 처리와 독립, 존재 게이트 없이 요청
                            ShyniBackend.request_refresh(item)
                            if not P.ModelSetting.get_bool('scan_plex_use'):
                                ShyniBackend.finalize_plex_off(item)
                                continue
                            if item.section_id == None:
                                section_info = PlexDBHandle.get_section_info_by_filepath(item.target)
                                if section_info != None:
                                    item.section_id = section_info['section_id']
                                    item.section_type = section_info['section_type']
                                else:
                                    item.set_status('FINISH_NOT_FIND_LIBRARY', save=True)
                                    continue
                            if P.ModelSetting.get_bool('scan_use_vfs_refresh'):
                                vfs_refresh(item.target)
                            if os.path.exists(item.target):
                                if os.path.isdir(item.target):
                                    refresh_target = item.target
                                else:
                                    refresh_target = os.path.dirname((item.target))
                                metaid = PlexDBHandle.get_metaid_by_directory(item.section_id, refresh_target)
                                if metaid != None:
                                    PlexWebHandle.refresh_by_id(metaid)
                                    if item.target.endswith('show.yaml'):
                                        logger.info(f"[REFRESH] show.yaml 감지 → manual_refresh(meta_id={metaid})")
                                        PlexWebHandle.manual_refresh(metaid)
                                    item.set_status('FINISH_REFRESH', save=True)
                                    continue
                                else:
                                    item.set_status('FINISH_NOT_FIND_IN_LIBRARY', save=True)
                            else:
                                item.set_status('NOT_EXIST', save=True)

                        elif item.mode in ['REMOVE_FILE', 'REMOVE_FOLDER']:
                            item.filecheck_count += 1
                            # 샤이니 대상 분기 — 삭제도 서버별 독립 작업(F-4)
                            ShyniBackend.request_scan(item)
                            if not P.ModelSetting.get_bool('scan_plex_use'):
                                ShyniBackend.finalize_plex_off(item)
                                continue
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
                            '''
                            REMOVE 모드에서 파일/폴더 존재 여부를 판단할 경우 대량의 파일을 하나씩 REMOVE 처리해야 함.
                            부모 폴더만 스캔해도 되도록 존재 여부를 판단하지 않게 수정.
                            '''
                            #if os.path.exists(item.target) == False:
                            if item.mode == 'REMOVE_FOLDER':
                                item.scan_folder = item.target
                            else:
                                if item.target.startswith('/'):
                                    item.scan_folder = item.target.rsplit('/', 1)[0]
                                else:
                                    item.scan_folder = item.target.rsplit('\\', 1)[0]
                            for _, queued_scan_folder, queued_mode in ModelScanItem.queue_list:
                                if queued_scan_folder == item.scan_folder and queued_mode == item.mode:
                                    item.set_status("FINISH_ALREADY_IN_QUEUE")
                                    break
                            else:
                                item.set_status("ENQUEUE_REMOVE")
                                item.init_for_queue()
                                Task.scan_queue.put(item)
                        else:
                            logger.error(f"지원하지 않는 스캔 모드: item={item.id} mode={item.mode}")
                            item.set_status('FINISH_INVALID_MODE')
                    except Exception as e:
                        logger.error(f"Exception:{str(e)}")
                        logger.error(traceback.format_exc())
                    finally:
                        item.save()
                max_scan_time = P.ModelSetting.get_int('scan_max_scan_time')
                if max_scan_time is None:
                    max_scan_time = 60
                if max_scan_time > 0:
                    scannings = ModelScanItem.get_list_by_status('SCANNING')
                    check_scanning(scannings, max_scan_time)
                # 샤이니 대상 job 상태 확정(F-4) — 주기당 1회 폴링
                ShyniBackend.poll_running()
                #P.logger.warning("파일체크 대기")
                filecheck_thread_interval = P.ModelSetting.get_int(f"{name}_filecheck_thread_interval")
                if filecheck_thread_interval is None:
                    filecheck_thread_interval = 60
                else:
                    filecheck_thread_interval = max(filecheck_thread_interval, 1)
                for i in range(filecheck_thread_interval):
                    time.sleep(1)
                    #print(i)
                #time.sleep(60)
            except Exception:
                logger.exception("파일 체크 쓰레드 오류")
                time.sleep(1)


    def scan_thread_function():
        while True:
            try:
                while True:
                    max_scan_count = P.ModelSetting.get_int(f"{name}_max_scan_count")
                    max_scan_count = 1 if max_scan_count is None else max(max_scan_count, 1)
                    if Task.current_scan_count < max_scan_count:
                        break
                    # 스캔 카운터의 정상 여부 확인
                    #logger.debug(f"최대 스캔 수 도달: {Task.current_scan_count} / {max_scan_count}")
                    time.sleep(5)
                db_item = Task.scan_queue.get()
                try:
                    if db_item is None or db_item.flag_cancel:
                        continue
                    Task.process_item_add_on_queue(db_item)
                finally:
                    Task.scan_queue.task_done()
            except Exception as e:
                logger.exception("스캔 큐 쓰레드 오류")
                time.sleep(1)


    def get_int_list(key):
        raw = P.ModelSetting.get(key) or ''
        items = []
        for line in raw.strip().splitlines():
            for part in line.split(','):
                part = part.strip()
                if part.isdigit():
                    items.append(int(part))
        return items

    def process_item_add_on_queue(db_item:ModelScanItem):
        callback_id = f"pm_scan_{uuid4().hex}_{db_item.id}"
        try:
            if db_item.mode == 'ADD' and Task.__check_media_part_data(db_item):
                return
            Task._start_scan(callback_id)
            use_web_request = P.ModelSetting.get_bool('scan_use_web_request')
            scan_web_sections = Task.get_int_list('scan_web_sections')
            if use_web_request and db_item.section_id and (not scan_web_sections or int(db_item.section_id) in scan_web_sections):
                threading.Thread(
                    target=Task.handle_web_scan,
                    args=(db_item,),
                    kwargs={'callback_id': callback_id},
                ).start()
            else:
                PlexBinaryScanner.scan_refresh(db_item.section_id, db_item.scan_folder, callback_function=Task.subprcoess_callback_function, callback_id=callback_id)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            Task.subprcoess_callback_function(callback_id, "ERROR", str(e))


    def handle_web_scan(db_item, max_wait=300, interval=30, callback_id=None):
        callback_id = callback_id or f"pm_scan_{uuid4().hex}_{db_item.id}"
        try:
            Task.subprcoess_callback_function(callback_id, "START", "Web scan started")
            web_target = db_item.scan_folder
            section_type = db_item.section_type or None
            if section_type and str(section_type) == "2":
                try:
                    escaped_folder = db_item.scan_folder.replace("'", "''")
                    query = f"""SELECT root_path FROM section_locations WHERE '{escaped_folder}' LIKE root_path || '%' ORDER BY LENGTH(root_path) DESC LIMIT 1;"""
                    result = PlexDBHandle.select(query)
                    root_path = result[0]['root_path'] if result else None
                    if root_path and os.path.normpath(db_item.scan_folder) != os.path.normpath(root_path):
                        rel_path = os.path.relpath(db_item.scan_folder, root_path)
                        parts = rel_path.split(os.sep)
                        show_name = parts[0]
                        web_target = os.path.join(root_path, show_name)
                        P.logger.debug(f"[handle_web_scan] Adjusted web_target: {web_target}")
                except Exception:
                    logger.exception("웹 스캔 경로 조정 오류")
            PlexWebHandle.path_scan(db_item.section_id, web_target)

            # 웹 스캔은 ADD 모드만 고려되어 있음. REMOVE/REFRESH 모드 구현 필요
            waited = 0
            while waited < max_wait:
                if Task.__check_media_part_data(db_item):
                    Task.subprcoess_callback_function(callback_id, "END", "Web scan completed (media found)", web=True)
                    return
                time.sleep(interval)
                waited += interval

            Task.subprcoess_callback_function(callback_id, "END", "Web scan timeout - media not found", web=False)
        except Exception as e:
            logger.exception("웹 스캔 오류")
            Task.subprcoess_callback_function(callback_id, "ERROR", str(e))

    def subprcoess_callback_function(call_id, mode, log, web=False):
        logger.debug(f"[{mode}] [{log}]")
        try:
            db_item = ModelScanItem.get_by_id(call_id.split('_')[-1])
            if mode == 'START':
                db_item.set_status('SCANNING', save=True)
            elif mode == 'END':
                if db_item.target_type == 'FOLDER':
                    db_item.set_status('FINISH_ADD_FOLDER', save=True)
                    PlexDBHandle.update_show_recent()
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
                    if web:
                        db_item.set_status('FINISH_ADD', save=True)
                        PlexDBHandle.update_show_recent()
                    elif Task.__check_media_part_data(db_item):
                        db_item.set_status('FINISH_ADD', save=True)
                        PlexDBHandle.update_show_recent()
                    else:
                        db_item.set_status('FINISH_SCANNING', save=True)
                # 2024-09-07
                # 이제 bin scanner가 refresh까지 하지 못함. web refresh 하도록 추가
                query = """
                    WITH TargetItem AS (
                        SELECT
                            CASE
                                WHEN m.metadata_type = 4 THEN (SELECT parent.parent_id FROM metadata_items AS parent WHERE parent.id = m.parent_id)
                                WHEN m.metadata_type = 3 THEN m.parent_id
                                ELSE m.id
                            END AS meta_id
                        FROM media_parts AS mp
                        JOIN media_items AS mi ON mp.media_item_id = mi.id
                        JOIN metadata_items AS m ON mi.metadata_item_id = m.id
                        WHERE m.library_section_id = ? AND mp.file LIKE ?
                        LIMIT 1
                    )
                    SELECT
                        m2.id,
                        m2.title,
                        m2.year,
                        m2.library_section_id,
                        ls.agent, 
                        m2.metadata_type,
                        m2.guid
                    FROM TargetItem AS ti
                    JOIN metadata_items AS m2 ON ti.meta_id = m2.id 
                    JOIN library_sections AS ls ON m2.library_section_id = ls.id;
                """
                if db_item.mode == 'ADD':
                    rows = PlexDBHandle.select_arg(query, (db_item.section_id, f"%{db_item.scan_folder}%"))
                    if rows:
                        logger.debug(f"{db_item.id}: {rows[0]}")
                        meta_agent = rows[0].get('agent') or ''
                        meta_id = rows[0].get('id') or 0
                        """
                        2026-03-24 halfaider
                        플렉스 기본 에이전트는 항상 업데이트 요청, 그 외는 scan_refresh_after_scanning 설정을 따름
                        """
                        if meta_id and (meta_agent.startswith("tv.plex.agents") or P.ModelSetting.get_bool('scan_refresh_after_scanning')):
                            logger.info(f"스캔: meta refresh {meta_id}")
                            PlexWebHandle.refresh_by_id(meta_id)
            elif mode == "ERROR":
                # 스캔이 정상 종료되지 않은 경우 다음 재실행시 스캔 되도록 FINISH_SCANNING 상태로 바꿈
                logger.error(f'스캔이 정상 처리되지 않았습니다: {db_item.mode} "{db_item.target}"')
                db_item.set_status('FINISH_SCANNING', save=True)
            else:
                # mode = LOG
                pass
        except Exception:
            logger.exception(call_id)
        finally:
            match mode:
                case 'END' | 'ERROR':
                    Task._finish_scan(call_id)
