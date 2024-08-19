from support import SupportYaml, d
from tool import ToolUtil

from .model_periodic import ModelPeriodicItem
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *
from .extensions import get_scan_targets, vfs_refresh


class Task(object):
    @classmethod
    def get_jobs(cls):
        config = SupportYaml.read_yaml(ToolUtil.make_path(P.ModelSetting.get('base_path_config')))
        data = config.get('라이브러리 주기적 스캔 목록', None)
        if data is None or type(data) != type([]):
            return []
        for idx, item in enumerate(data):
            item['job_id'] = f'{P.package_name}_periodic_{idx}'
            item['설명'] = item.get('설명', f"섹션: {item.get('섹션ID')}" if item.get('섹션ID') else '--')
            item['is_include_scheduler'] = str(F.scheduler.is_include(item['job_id']))
        return data


    @staticmethod
    @F.celery.task()
    def start(idx, mode):
        try:
            yaml = Task.get_jobs()[idx]
            logger.debug(f'작업 정보: {yaml}')

            should_refresh = '새로고침' in yaml
            if should_refresh:
                if yaml['새로고침'] is None:
                    yaml['새로고침'] = {}
                recursive = yaml.get('새로고침').get('하위폴더', False)
                async_ = yaml.get('새로고침').get('비동기', False)
                skip_scan = yaml.get('새로고침').get('스캔무시', False)
            else:
                recursive = False
                async_ = False
                skip_scan = False

            if skip_scan:
                vfs_refresh(yaml.get('폴더', '/'), recursive, async_)
                logger.info(f'작업 종료: {yaml.get("job_id")}')
                return

            if yaml.get('스캔모드') == "웹":
                '''
                섹션ID 정보가 있을 경우:
                    섹션에 추가된 폴더와 작업의 "폴더"를 비교 후 하위 경로를 새로고침
                섹션ID 정보가 없을 경우:
                    모든 섹션에 추가된 폴더와 작업의 "폴더" 중 하위 경로를 새로고침
                폴더 정보가 있을 경우:
                    부분 스캔
                폴더 정보가 없을 경우:
                    전체 스캔

                Plex Dash 앱에서 library_sections 테이블의 scanned_at 컬럼의 정보를 통해 최근 스캔 시간을 표시중
                이 컬럼은 전체 섹션을 스캔(path 파라미터 없이)했을 때만 갱신되는 것으로 보임
                '''
                if not yaml.get('폴더') and not yaml.get('섹션ID'):
                    logger.error(f'스캔 대상을 명시해 주세요: {yaml}')
                    return
                if not yaml.get('폴더') and not should_refresh:
                    PlexWebHandle.section_scan(yaml.get('섹션ID'))
                    logger.debug(f'스캔 전송: section_id={yaml.get("섹션ID")}')
                    return
                targets: dict = get_scan_targets(yaml.get('폴더', '/'), yaml.get('섹션ID'))
                for location, section_id in targets.items():
                    if should_refresh: vfs_refresh(location, recursive, async_)
                    if yaml.get('폴더'):
                        # 폴더 키워드가 있을 경우 부분 스캔
                        PlexWebHandle.path_scan(section_id, location)
                        logger.debug(f'스캔 전송: section_id={section_id} path={location}')
                if not yaml.get('폴더'):
                    # 폴더 키워드가 없을 경우 전체 스캔
                    PlexWebHandle.section_scan(yaml.get('섹션ID'))
                    logger.debug(f'스캔 전송: section_id={yaml.get("섹션ID")}')
                return

            '''
            바이너리 스캔은 섹션 단위를 하나의 프로세스로 스캔하도록 설계되어 있으므로 섹션ID가 필수
            '''
            db_item = ModelPeriodicItem()
            db_item.mode = mode
            db_item.section_id = yaml.get('섹션ID')
            section_data = PlexDBHandle.library_section(yaml.get('섹션ID', -1)) or {}
            db_item.section_title = section_data.get('name', '알 수 없음')
            db_item.section_type = section_data.get('section_type', -1)
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

            if should_refresh:
                targets: dict = get_scan_targets(db_item.folder or '/', db_item.section_id)
                for location, section_id in targets.items():
                    vfs_refresh(location, recursive, async_)

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