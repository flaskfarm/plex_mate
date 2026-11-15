import fnmatch
import os
import re
import shutil
import sqlite3
import time
import traceback
import urllib.parse
from datetime import datetime

from . import fs_probe
from .extensions import vfs_refresh
from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle, dict_factory
from .plex_web import PlexWebHandle
from .setup import *

subtitle_exts  = ['*.srt', '*.smi', '*.ass', '*.ssa']
SUBTITLE_EXTS  = r'|'.join([fnmatch.translate(x) for x in subtitle_exts])
logger = P.logger


class Task(object):
    
    @staticmethod
    @celery.task(bind=True)
    def start(self, command, section_id, section_location):
        if command == 'start1':
            return Task.start_db(self, section_id, section_location, mode='all')
        elif command == 'start2':
            return Task.start_db(self, section_id, section_location, mode='dead_sub')
        elif command == 'start3':
            return Task.start_db(self, section_id, section_location, mode='missing_sub')

        db_file = P.ModelSetting.get('base_path_db')
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        
        locations = PlexDBHandle.section_location(library_id=section_id)
        if section_location != 'all':
            for tmp in locations:
                if tmp['root_path'] == section_location:
                    break
            locations = [tmp]

        P.logger.error(d(locations))

        status = {'is_working':'run', 'subtitle_count':0, 
            'subtitle_exist_in_meta_count':0, # 자막이 db에서 검색됨.
            'not_subtitle_exist_in_meta_count':0, # 자막이 db에서 검색되지 않음
            'videofile_exist_count':0,  #자막에 맞는 비디오 파일 있음
            'not_videofile_exist_count':0, # 자막만 있고 자막 파일명에 맞는 비디오 없음
            'videofile_exist_not_in_meta_count':0, # 자막에 맞는 비디오 파일이 메타에 없음. 스캔필요
            'videofile_exist_in_meta_count':0, #자막에 맞는 비디오 파일이 메타에 이미 있음. 메타새로고침 필요
            'smi_count':0, 
            'smi2srt_count':0, 
            'meta_refresh_show_metadata_item_id': None,
            'meta_refresh_show_metadata_item_title': None,
            'meta_refresh_show_count':0,
        }

        smi2srt = P.ModelSetting.get_bool('subtitle_use_smi_to_srt')
        
        for location in locations:
            section_type = 'movie' if location['section_type'] == 1 else 'show'
            root = location['root_path']
            #root = '/mnt/gds/외국TV/외국/0Z/CSI 마이애미 (2002) [CSI Miami]'

            for base, dirs, files in os.walk(root):
                ignore = False
                for rx in IGNORE_DIRS:
                    if re.match(rx, os.path.basename(base), re.IGNORECASE):
                        #logger.debug(f"IGNORE : {base}")
                        ignore = True
                        break
                if ignore:
                    continue

                files = [f for f in files if re.match(SUBTITLE_EXTS, f)]
                #process_base = False
                for fname in files:
                    if P.ModelSetting.get_bool('subtitle_task_stop_flag'):
                        return 'stop'
                    try:
                        status['subtitle_count'] += 1
                        data = {'status':status, 'need_smi2srt': False, 'section_type':section_type, 'dir':base, 'filename':fname, 'subtitle_filepath':os.path.join(base, fname), 'ret':{}, 'meta_subtitle':{}, 'meta_videofile':{}}
                        if os.path.splitext(fname)[-1].lower() == '.smi':
                            status['smi_count'] += 1
                            if smi2srt:
                                data['need_smi2srt'] = True

                        #logger.debug(data['subtitle_filepath'])
                        tmp = f"file://{data['subtitle_filepath'].replace('%', '%25').replace(' ', '%20')}"

                        #tmp = 'file:///mnt/gds/외국TV/다큐/펭귄%20타운%20(2021)%20[Penguin%20Town]%'

                        ce = con.execute(QUERY, (tmp,))
                        ce.row_factory = dict_factory
                        rows = ce.fetchall()

                        if len(rows) > 0:
                            status['subtitle_exist_in_meta_count'] += 1
                            data['ret']['find_meta'] = True
                            data['meta_subtitle']['video_file'] = rows[0]['file']
                            if section_type == 'movie':
                                data['meta_subtitle']['title'] = rows[0]['title']
                                data['meta_subtitle']['metadata_items_id'] = rows[0]['metadata_items_id']
                            elif section_type == 'show':
                                Task.get_show_meda(con, data['meta_subtitle'], rows[0])

                            if data['need_smi2srt']:
                                Task.smi2srt(data)
                                Task.try_vfs_refresh(base)
                                if section_type == 'movie':
                                    logger.warning(f"영화 smi2srt 메타 새로고침1 : {rows[0]['title']}")
                                    PlexWebHandle.refresh_by_id(rows[0]['metadata_items_id'])
                                elif section_type == 'show':
                                    Task.meta_refresh_show(data, data['meta_subtitle']['show_metadata_items_id'], data['meta_subtitle']['show_title'])
                            continue

                        logger.debug(f"==> 자막 DB에 없음 : {tmp}")

                        status['not_subtitle_exist_in_meta_count'] += 1
                        data['ret']['find_meta'] = False

                        data['ret']['find_video'],  data['ret']['find_videofilename'] = Task.find_video(base, fname)
                        logger.warning(f"비디오 파일 탐색 결과 : {data['ret']['find_video']}")

                        if data['ret']['find_video']:
                            if data['need_smi2srt']:
                                Task.smi2srt(data)
                            status['videofile_exist_count'] +=1
                            ce = con.execute(QUERY_VIDEO, (os.path.join(base, data['ret']['find_videofilename']),))
                            ce.row_factory = dict_factory
                            rows = ce.fetchall()
                            logger.error(rows)
                            
                            if len(rows) == 0:
                                # 비디오 파일이 없다면 스캔
                                Task.try_vfs_refresh(base)
                                status['videofile_exist_not_in_meta_count'] += 1
                                data['ret']['meta_by_videofile'] = False
                                if section_type == 'movie':
                                    logger.warning(f'영화 스캔 : {base}')
                                    PlexBinaryScanner.scan_refresh(section_id, base)
                                elif section_type == 'show':
                                    # 쇼는 쇼폴더에서 스캔해야한다.
                                    tmp = base.replace(root, '')
                                    tmps = tmp.split(os.sep)  # tmps[0] == ''
                                    if len(tmps) > 1:
                                        logger.warning(f'쇼 스캔 : {base} {os.path.join(root, tmps[1])}')
                                        PlexBinaryScanner.scan_refresh(section_id, os.path.join(root, tmps[1]))
                                ##process_base = True
                                #return
                            else:
                                status['videofile_exist_in_meta_count'] += 1
                                data['ret']['meta_by_videofile'] = True
                                # 비디오 파일이 이미 있다면 메타새로고침
                                Task.try_vfs_refresh(base)
                                if section_type == 'movie':
                                    data['meta_videofile']['title'] = rows[0]['title']
                                    data['meta_videofile']['metadata_items_id'] = rows[0]['metadata_items_id']
                                    logger.warning(f"영화 메타 새로고침2 : {rows[0]['title']}")
                                    PlexWebHandle.refresh_by_id(rows[0]['metadata_items_id'])
                                elif section_type == 'show':
                                    Task.get_show_meda(con, data['meta_videofile'], rows[0], is_video=True)
                                   
                                    Task.meta_refresh_show(data, data['meta_videofile']['show_metadata_items_id'], data['meta_videofile']['show_title'])
                                    #
                                    try:
                                        if data['meta_videofile']['episode_subtitle'][0]['sub'] != '':
                                            PlexWebHandle.refresh_by_id(rows[0]['metadata_items_id'])
                                            logger.debug(f"에피소드 메타새로고침 : {rows[0]['metadata_items_id']}")
                                    except Exception as e:
                                        #logger.error(f'Exception:{str(e)}')
                                        #logger.error(traceback.format_exc())
                                        pass
                                    
                                #return 'stop'
                                #process_base = True
                                #return
                                #break
                        else:
                            status['not_videofile_exist_count'] +=1
                            #return
                    except Exception as e:
                        logger.error(f'Exception:{str(e)}')
                        logger.error(traceback.format_exc())
                        #logger.error(show['title'])
                    finally:
                        #logger.debug(d(data))
                        if F.config['use_celery']:
                            self.update_state(state='PROGRESS', meta=data)
                        else:
                            self.receive_from_task(data, celery=False)
                        #if process_base:
                        #    break
            # 남아 있는 것을 갱신하기 위해
            Task.meta_refresh_show({'status':status}, None, None)
        return 'wait'

    @staticmethod
    def start_db(self, section_id, section_location, mode='all'):
        Task.readonly_paths = set()
        con = None
        status = {
            'is_working': 'run',
            'mode': 'db',
            'sub_mode': mode,
            'section_name': '',
            'section_type': 'movie',
            'db_total_sub_count': 0,
            'db_checked_sub_count': 0,
            'db_normal_sub_count': 0,
            'db_dead_sub_count': 0,
            'db_unknown_sub_count': 0,
            'db_smi2srt_count': 0,
            'db_meta_refresh_count': 0,
            'db_refreshed_items': [],
            'db_total_media_count': 0,
            'db_checked_media_count': 0,
            'db_hardsub_count': 0,
            'db_found_disk_sub_count': 0,
            'db_missing_korean_count': 0,
            'current_step': ('1단계: 외부 자막 무결성 검사 (죽은 자막 탐지)' if mode == 'all' 
                            else ('외부 자막 무결성 검사 (죽은 자막 탐지)' if mode == 'dead_sub' 
                            else '외화 컨텐츠 한글 자막 누락 및 디스크 자막 진단'))
        }

        last_notify_time = [0.0]
        def notify(data, force=False):
            now = time.time()
            is_log = bool(data.get('ret', {}).get('log_type'))
            if force or is_log or (now - last_notify_time[0] >= 0.5):
                last_notify_time[0] = now
                try:
                    if F.config['use_celery']:
                        self.update_state(state='PROGRESS', meta=data)
                    else:
                        self.receive_from_task(data, celery=False)
                except Exception as e:
                    logger.error(f"[DB기준] notify 에러: {str(e)}")

        try:
            db_file = P.ModelSetting.get('base_path_db')
            con = sqlite3.connect(db_file)
            cur = con.cursor()

            library_section = PlexDBHandle.library_section(section_id)
            if not library_section:
                logger.error(f"[DB기준] 라이브러리 섹션을 찾을 수 없습니다: {section_id}")
                return 'wait'

            section_name = library_section.get('name', '')
            section_type = 'movie' if library_section.get('section_type') == 1 else 'show'
            status['section_name'] = section_name
            status['section_type'] = section_type

            locations = PlexDBHandle.section_location(library_id=section_id)
            Task.section_locations = [tmp.get('root_path', '') for tmp in locations if tmp.get('root_path')]
            selected_location = None
            if section_location != 'all':
                for tmp in locations:
                    if tmp['root_path'] == section_location:
                        selected_location = tmp['root_path']
                        break

            notify({'status': status, 'mode': 'db', 'ret': {}})

            # -----------------------------------------------------------------
            # 공통 헬퍼 및 캐시
            # -----------------------------------------------------------------
            def get_disk_path(stream_url):
                if not stream_url:
                    return None
                if stream_url.startswith('file://'):
                    path = stream_url[7:]
                else:
                    path = stream_url
                return urllib.parse.unquote(path)

            season_to_show = {}
            def get_show_info(season_id):
                if season_id in season_to_show:
                    return season_to_show[season_id]
                try:
                    c = con.execute("SELECT id, parent_id, metadata_type, title FROM metadata_items WHERE id = ?", (season_id,))
                    c.row_factory = dict_factory
                    row = c.fetchone()
                    if not row:
                        season_to_show[season_id] = (None, None)
                        return None, None
                    if row['metadata_type'] == 2:
                        res = (row['id'], row['title'])
                    else:
                        c2 = con.execute("SELECT id, title FROM metadata_items WHERE id = ?", (row['parent_id'],))
                        c2.row_factory = dict_factory
                        show_row = c2.fetchone()
                        if show_row:
                            res = (show_row['id'], show_row['title'])
                        else:
                            res = (row['parent_id'], row['title'])
                    season_to_show[season_id] = res
                    return res
                except Exception as e:
                    logger.error(f"get_show_info error: {str(e)}")
                    return None, None

            dead_stream_ids = set()

            # -----------------------------------------------------------------
            # 1·2단계: 외부 자막(External Subtitle) 죽은 자막 병렬 탐지 및 정리
            # -----------------------------------------------------------------
            if mode in ['all', 'dead_sub']:
                status['current_step'] = '1단계: 외부 자막 무결성 검사 (죽은 자막 탐지)' if mode == 'all' else '외부 자막 무결성 검사 (죽은 자막 탐지)'
                sub_query = """
                SELECT 
                    media_streams.id AS stream_id,
                    media_streams.url AS stream_url,
                    media_streams.codec AS stream_codec,
                    media_streams.language AS stream_language,
                    media_parts.id AS part_id,
                    media_parts.file AS video_file,
                    media_items.id AS media_item_id,
                    metadata_items.id AS metadata_item_id,
                    metadata_items.parent_id AS parent_id,
                    metadata_items.metadata_type AS metadata_type,
                    metadata_items.title AS title
                FROM media_streams
                JOIN media_items ON media_streams.media_item_id = media_items.id
                JOIN media_parts ON media_items.id = media_parts.media_item_id
                JOIN metadata_items ON media_items.metadata_item_id = metadata_items.id
                WHERE media_streams.stream_type_id = 3
                  AND media_streams.url IS NOT NULL 
                  AND media_streams.url LIKE 'file://%'
                  AND metadata_items.library_section_id = ?
                """
                params = [section_id]
                if selected_location:
                    sub_query += " AND media_parts.file LIKE ?"
                    params.append(f"{selected_location}%")

                ce = con.execute(sub_query, tuple(params))
                ce.row_factory = dict_factory
                subtitle_rows = ce.fetchall()

                status['db_total_sub_count'] = len(subtitle_rows)
                notify({'status': status, 'mode': 'db', 'ret': {}})

                refresh_movie_ids = {} # {metadata_item_id: title}
                refresh_movie_reasons = {} # {metadata_item_id: set()}
                refresh_movie_dirs = {} # {metadata_item_id: set()}
                refresh_show_ids = {}  # {show_id: show_title}
                refresh_show_reasons = {}  # {show_id: set()}
                refresh_show_dirs = {}  # {show_id: set()}

                chunk_size = 50
                chunk_timeout = 30
                hung_chunks = 0
                pool = fs_probe.executor(8)
                try:
                    for i in range(0, len(subtitle_rows), chunk_size):
                        if P.ModelSetting.get_bool('subtitle_task_stop_flag'):
                            status['is_working'] = 'stop'
                            notify({'status': status, 'mode': 'db', 'ret': {}})
                            return 'stop'

                        chunk = subtitle_rows[i:i+chunk_size]
                        states, hung = fs_probe.probe_many(
                            pool,
                            [(idx, get_disk_path(row.get('stream_url', '')), row.get('video_file')) for idx, row in enumerate(chunk)],
                            chunk_timeout)
                        if hung:
                            hung_chunks += 1
                            logger.warning(f"[DB기준] 자막 파일 검사 {hung}건이 {chunk_timeout}초 안에 응답하지 않아 건너뜁니다.")
                            if hung_chunks >= 3:
                                raise RuntimeError('스토리지가 응답하지 않습니다. 마운트 상태를 확인하세요.')
                        else:
                            hung_chunks = 0

                        for idx, sub_row in enumerate(chunk):
                            status['db_checked_sub_count'] += 1
                            disk_path = get_disk_path(sub_row.get('stream_url', ''))
                            state = states[idx]
                            exists = state == fs_probe.OK

                            if state == fs_probe.UNKNOWN:
                                # 영상도 안 보이거나 응답이 없다: 마운트 문제일 수 있어 죽은 자막으로 치지 않는다
                                status['db_unknown_sub_count'] += 1
                            elif exists:
                                status['db_normal_sub_count'] += 1
                                # smi to srt 옵션 활성화 시 정상 외부 자막에 대해서도 변환/리네임 수행
                                if P.ModelSetting.get_bool('subtitle_use_smi_to_srt'):
                                    stream_lang = (sub_row.get('stream_language') or '').lower()
                                    # DB 상에 이미 명확히 외국어(eng, en, jpn 등)로 등록된 자막은 제외
                                    if stream_lang and stream_lang not in ['ko', 'kor', 'korean']:
                                        conv_res = None
                                    else:
                                        conv_res = Task.process_smi_to_srt(disk_path, video_file=sub_row.get('video_file'))
                                    if conv_res and conv_res.get('action') in ['smi2srt', 'rename_ko']:
                                        status['db_smi2srt_count'] += 1
                                        act = conv_res['action'] # 'smi2srt' or 'rename_ko'
                                        if sub_row['metadata_type'] == 1:
                                            m_id = sub_row['metadata_item_id']
                                            refresh_movie_ids[m_id] = sub_row['title']
                                            if m_id not in refresh_movie_reasons:
                                                refresh_movie_reasons[m_id] = set()
                                            refresh_movie_reasons[m_id].add(act)
                                            if disk_path:
                                                refresh_movie_dirs.setdefault(m_id, set()).add(os.path.dirname(disk_path))
                                        elif sub_row['metadata_type'] == 4:
                                            show_id, show_title = get_show_info(sub_row['parent_id'])
                                            if show_id:
                                                refresh_show_ids[show_id] = show_title
                                                if show_id not in refresh_show_reasons:
                                                    refresh_show_reasons[show_id] = set()
                                                refresh_show_reasons[show_id].add(act)
                                                if disk_path:
                                                    refresh_show_dirs.setdefault(show_id, set()).add(os.path.dirname(disk_path))

                                        conv_log = {
                                            'status': status,
                                            'mode': 'db',
                                            'ret': {'log_type': ('SMI2SRT' if act == 'smi2srt' else 'RENAME_KO')},
                                            'title': sub_row['title'],
                                            'video_file': sub_row['video_file'],
                                            'old_path': conv_res['old_path'],
                                            'new_path': conv_res['new_path'],
                                            'stream_id': sub_row['stream_id'],
                                            'section_type': section_type
                                        }
                                        notify(conv_log)
                            else:
                                status['db_dead_sub_count'] += 1
                                dead_stream_ids.add(sub_row['stream_id'])

                                # 새로고침 타겟 등록
                                if sub_row['metadata_type'] == 1:
                                    m_id = sub_row['metadata_item_id']
                                    refresh_movie_ids[m_id] = sub_row['title']
                                    if m_id not in refresh_movie_reasons:
                                        refresh_movie_reasons[m_id] = set()
                                    refresh_movie_reasons[m_id].add('dead')
                                    if disk_path:
                                        refresh_movie_dirs.setdefault(m_id, set()).add(os.path.dirname(disk_path))
                                elif sub_row['metadata_type'] == 4:
                                    show_id, show_title = get_show_info(sub_row['parent_id'])
                                    if show_id:
                                        refresh_show_ids[show_id] = show_title
                                        if show_id not in refresh_show_reasons:
                                            refresh_show_reasons[show_id] = set()
                                        refresh_show_reasons[show_id].add('dead')
                                        if disk_path:
                                            refresh_show_dirs.setdefault(show_id, set()).add(os.path.dirname(disk_path))

                                dead_log = {
                                    'status': status,
                                    'mode': 'db',
                                    'ret': {'log_type': 'DEAD'},
                                    'title': sub_row['title'],
                                    'video_file': sub_row['video_file'],
                                    'dead_subtitle_path': disk_path,
                                    'stream_id': sub_row['stream_id'],
                                    'section_type': section_type
                                }
                                notify(dead_log)

                            # 10개마다 또는 마지막에 실시간 진행 상황 브로드캐스트
                            if status['db_checked_sub_count'] % 10 == 0 or status['db_checked_sub_count'] == status['db_total_sub_count']:
                                notify({'status': status, 'mode': 'db', 'ret': {}})
                finally:
                    pool.shutdown(wait=False)

                # 2단계: 메타 새로고침 (쇼/영화 단위 중복 없이 일괄 호출)
                if refresh_movie_ids or refresh_show_ids:
                    status['current_step'] = f"{'2단계: ' if mode == 'all' else ''}메타 새로고침 (영화 {len(refresh_movie_ids)}편, TV쇼 {len(refresh_show_ids)}개)"
                    notify({'status': status, 'mode': 'db', 'ret': {}})

                    for m_id, m_title in refresh_movie_ids.items():
                        if P.ModelSetting.get_bool('subtitle_task_stop_flag'):
                            status['is_working'] = 'stop'
                            notify({'status': status, 'mode': 'db', 'ret': {}})
                            return 'stop'
                        try:
                            vfs_done = False
                            for d_path in refresh_movie_dirs.get(m_id, []):
                                if Task.try_vfs_refresh(d_path):
                                    vfs_done = True
                            logger.warning(f"[DB기준] 영화 메타 새로고침: {m_title} (ID: {m_id})")
                            if not PlexWebHandle.refresh_by_id(m_id):
                                raise RuntimeError('Plex가 새로고침 요청을 받지 않았습니다.')
                            status['db_meta_refresh_count'] += 1

                            vfs_tag = " (VFS 갱신)" if vfs_done else ""
                            m_reasons = refresh_movie_reasons.get(m_id, set(['dead']))
                            if 'dead' in m_reasons and ('smi2srt' in m_reasons or 'rename_ko' in m_reasons):
                                r_type = 'DEAD_AND_CONV'
                                r_type_kor = '죽은 자막 및 변환'
                                r_detail = f"삭제된 자막 정리 및 변환 자막{vfs_tag} ➔ 영화 메타 새로고침 완료"
                            elif 'smi2srt' in m_reasons and 'rename_ko' in m_reasons:
                                r_type = 'SMI2SRT'
                                r_type_kor = 'SMI/한글 변환'
                                r_detail = f"SMI 변환 및 한글 자막 복사{vfs_tag} ➔ 영화 메타 새로고침 완료"
                            elif 'smi2srt' in m_reasons:
                                r_type = 'SMI2SRT'
                                r_type_kor = 'SMI➔SRT 변환'
                                r_detail = f"SMI ➔ SRT 변환{vfs_tag} ➔ 영화 메타 새로고침 완료"
                            elif 'rename_ko' in m_reasons:
                                r_type = 'RENAME_KO'
                                r_type_kor = '한글 .ko.srt'
                                r_detail = f"한글 자막 .ko.srt 복사{vfs_tag} ➔ 영화 메타 새로고침 완료"
                            else:
                                r_type = 'DEAD'
                                r_type_kor = '죽은 자막 정리'
                                r_detail = f"삭제된 자막 정리{vfs_tag} ➔ 영화 메타 새로고침 완료"

                            refresh_item = {
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': r_type,
                                'type_kor': r_type_kor,
                                'title': m_title,
                                'target_id': m_id,
                                'section_type': 'movie',
                                'status': 'success',
                                'detail': r_detail
                            }
                            status['db_refreshed_items'].append(refresh_item)
                            notify({
                                'status': status,
                                'mode': 'db',
                                'ret': {'log_type': 'REFRESH'},
                                'title': m_title,
                                'target_id': m_id,
                                'section_type': 'movie',
                                'msg': f"영화 메타 새로고침 요청 완료 ({m_title})"
                            })
                            time.sleep(0.1)
                        except Exception as e:
                            logger.error(f"[DB기준] 영화 메타 새로고침 실패: {m_title} - {str(e)}")
                            refresh_item = {
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': 'DEAD',
                                'type_kor': '죽은 자막 정리',
                                'title': m_title,
                                'target_id': m_id,
                                'section_type': 'movie',
                                'status': 'fail',
                                'detail': f"메타 새로고침 실패: {str(e)}"
                            }
                            status['db_refreshed_items'].append(refresh_item)

                    for s_id, s_title in refresh_show_ids.items():
                        if P.ModelSetting.get_bool('subtitle_task_stop_flag'):
                            status['is_working'] = 'stop'
                            notify({'status': status, 'mode': 'db', 'ret': {}})
                            return 'stop'
                        try:
                            vfs_done = False
                            for d_path in refresh_show_dirs.get(s_id, []):
                                if Task.try_vfs_refresh(d_path):
                                    vfs_done = True
                            logger.warning(f"[DB기준] TV쇼 메타 새로고침: {s_title} (ID: {s_id})")
                            if not PlexWebHandle.refresh_by_id(s_id):
                                raise RuntimeError('Plex가 새로고침 요청을 받지 않았습니다.')
                            status['db_meta_refresh_count'] += 1

                            vfs_tag = " (VFS 갱신)" if vfs_done else ""
                            s_reasons = refresh_show_reasons.get(s_id, set(['dead']))
                            if 'dead' in s_reasons and ('smi2srt' in s_reasons or 'rename_ko' in s_reasons):
                                r_type = 'DEAD_AND_CONV'
                                r_type_kor = '죽은 자막 및 변환'
                                r_detail = f"삭제된 자막 정리 및 변환 자막{vfs_tag} ➔ TV쇼 메타 새로고침 완료"
                            elif 'smi2srt' in s_reasons and 'rename_ko' in s_reasons:
                                r_type = 'SMI2SRT'
                                r_type_kor = 'SMI/한글 변환'
                                r_detail = f"SMI 변환 및 한글 자막 복사{vfs_tag} ➔ TV쇼 메타 새로고침 완료"
                            elif 'smi2srt' in s_reasons:
                                r_type = 'SMI2SRT'
                                r_type_kor = 'SMI➔SRT 변환'
                                r_detail = f"SMI ➔ SRT 변환{vfs_tag} ➔ TV쇼 메타 새로고침 완료"
                            elif 'rename_ko' in s_reasons:
                                r_type = 'RENAME_KO'
                                r_type_kor = '한글 .ko.srt'
                                r_detail = f"한글 자막 .ko.srt 복사{vfs_tag} ➔ TV쇼 메타 새로고침 완료"
                            else:
                                r_type = 'DEAD'
                                r_type_kor = '죽은 자막 정리'
                                r_detail = f"삭제된 자막 정리{vfs_tag} ➔ TV쇼 메타 새로고침 완료"

                            refresh_item = {
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': r_type,
                                'type_kor': r_type_kor,
                                'title': s_title,
                                'target_id': s_id,
                                'section_type': 'show',
                                'status': 'success',
                                'detail': r_detail
                            }
                            status['db_refreshed_items'].append(refresh_item)
                            notify({
                                'status': status,
                                'mode': 'db',
                                'ret': {'log_type': 'REFRESH'},
                                'title': s_title,
                                'target_id': s_id,
                                'section_type': 'show',
                                'msg': f"TV 쇼 메타 새로고침 요청 완료 ({s_title})"
                            })
                            time.sleep(0.1)
                        except Exception as e:
                            logger.error(f"[DB기준] TV쇼 메타 새로고침 실패: {s_title} - {str(e)}")
                            refresh_item = {
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': 'DEAD',
                                'type_kor': '죽은 자막 정리',
                                'title': s_title,
                                'target_id': s_id,
                                'section_type': 'show',
                                'status': 'fail',
                                'detail': f"메타 새로고침 실패: {str(e)}"
                            }
                            status['db_refreshed_items'].append(refresh_item)

            # -----------------------------------------------------------------
            # 3단계: 외화 한글 자막 누락 진단 및 자체자막(하드서브) 회피
            # -----------------------------------------------------------------
            if mode in ['all', 'missing_sub']:
                step_prefix = '3단계: ' if mode == 'all' else ''
                # 쇼·에피소드에는 국가 정보가 없어서 한국 컨텐츠 섹션은 이름 규칙과 사용자 지정 목록으로 거른다
                skip_sections = [x.strip() for x in (P.ModelSetting.get('subtitle_missing_skip_sections') or '').split(',') if x.strip()]
                is_korean_section = ('한국' in section_name or '국내' in section_name
                                     or str(section_id) in skip_sections or section_name.strip() in skip_sections)
                if is_korean_section:
                    status['current_step'] = f"{step_prefix}한국 컨텐츠 라이브러리('{section_name}')이므로 자막 누락 진단을 건너뜁니다."
                    notify({'status': status, 'mode': 'db', 'ret': {}})
                else:
                    status['current_step'] = f"{step_prefix}외화 컨텐츠 한글 자막 누락 및 자체자막 진단"
                    notify({'status': status, 'mode': 'db', 'ret': {}})

                    media_query = """
                    SELECT 
                        metadata_items.id AS metadata_item_id,
                        metadata_items.parent_id AS parent_id,
                        metadata_items.metadata_type AS metadata_type,
                        metadata_items.title AS title,
                        metadata_items.year AS year,
                        metadata_items.tags_country AS tags_country,
                        media_items.id AS media_item_id,
                        media_parts.id AS part_id,
                        media_parts.file AS video_file
                    FROM metadata_items
                    JOIN media_items ON metadata_items.id = media_items.metadata_item_id
                    JOIN media_parts ON media_items.id = media_parts.media_item_id
                    WHERE metadata_items.library_section_id = ?
                      AND metadata_items.metadata_type IN (1, 4)
                    """
                    m_params = [section_id]
                    if selected_location:
                        media_query += " AND media_parts.file LIKE ?"
                        m_params.append(f"{selected_location}%")

                    ce = con.execute(media_query, tuple(m_params))
                    ce.row_factory = dict_factory
                    media_rows = ce.fetchall()

                    status['db_total_media_count'] = len(media_rows)
                    notify({'status': status, 'mode': 'db', 'ret': {}})

                    # 해당 라이브러리의 모든 자막 스트림(stream_type_id = 3) 조회하여 media_item_id별 매핑
                    # 내장 자막은 media_part_id, 외부 자막은 media_item_id에 연결됨.
                    # UNION ALL로 분리하여 인덱스를 100% 활용하고 TV/영화 무관하게 정확히 조회
                    streams_query = """
                    SELECT 
                        media_streams.id AS stream_id,
                        media_items.id AS media_item_id,
                        media_streams.url AS url,
                        media_streams.codec AS codec,
                        media_streams.language AS language,
                        media_streams.extra_data AS extra_data
                    FROM media_streams
                    JOIN media_parts ON media_streams.media_part_id = media_parts.id
                    JOIN media_items ON media_parts.media_item_id = media_items.id
                    WHERE media_streams.stream_type_id = 3
                      AND media_items.library_section_id = ?

                    UNION ALL

                    SELECT 
                        media_streams.id AS stream_id,
                        media_items.id AS media_item_id,
                        media_streams.url AS url,
                        media_streams.codec AS codec,
                        media_streams.language AS language,
                        media_streams.extra_data AS extra_data
                    FROM media_streams
                    JOIN media_items ON media_streams.media_item_id = media_items.id
                    WHERE media_streams.stream_type_id = 3
                      AND media_streams.media_part_id IS NULL
                      AND media_items.library_section_id = ?
                    """
                    ce = con.execute(streams_query, (section_id, section_id))
                    ce.row_factory = dict_factory
                    all_streams = ce.fetchall()

                    media_streams_map = {}
                    for st in all_streams:
                        m_id = st['media_item_id']
                        if m_id not in media_streams_map:
                            media_streams_map[m_id] = []
                        media_streams_map[m_id].append(st)

                    def detect_hardsub_tag(video_file):
                        if not video_file:
                            return None
                        fname = os.path.basename(video_file)
                        stem, _ = os.path.splitext(fname)
                        # 1. 파일명에 ST 또는 SW (단어 경계 또는 끝자리, 예: -SW, .SW, _SW, -ST, .ST, _ST 등)
                        m = re.search(r'[\.\-_](ST|SW)($|[\.\-_])', stem, re.IGNORECASE)
                        if m:
                            return m.group(1).upper()
                        # 2. 파일명에 KOR 또는 자체자막 포함 (예: .KOR., -KOR-, [KOR], [자체자막] 등)
                        m = re.search(r'(^|[\.\s_\-\[\(])(KOR|자체자막)($|[\.\s_\-\]\)])', stem, re.IGNORECASE)
                        if m:
                            return m.group(2).upper()
                        return None

                    korean_langs = {'ko', 'kor', 'korean', '한국어'}
                    korean_countries = {'한국', '대한민국', 'korea', 'south korea', 'republic of korea'}
                    refreshed_disk_target_ids = set()

                    for row_idx, m_row in enumerate(media_rows):
                        if row_idx % 50 == 0:
                            if P.ModelSetting.get_bool('subtitle_task_stop_flag'):
                                status['is_working'] = 'stop'
                                notify({'status': status, 'mode': 'db', 'ret': {}})
                                return 'stop'
                            notify({'status': status, 'mode': 'db', 'ret': {}})

                        status['db_checked_media_count'] += 1
                        video_file = m_row.get('video_file', '')

                        try:
                            # 0. 메타데이터 국가(Country)가 한국인 컨텐츠는 자막 검사 제외 (통합 라이브러리 오탐 방지)
                            tags_country = (m_row.get('tags_country') or '').lower()
                            if any(k in tags_country for k in korean_countries):
                                continue

                            # 1. 한글 자막 스트림 보유 여부 검사 (내부/외부 자막)
                            m_streams = media_streams_map.get(m_row['media_item_id'], [])
                            has_korean_sub = False

                            for st in m_streams:
                                # 죽은 자막으로 확인된 것은 제외
                                if st['stream_id'] in dead_stream_ids:
                                    continue

                                lang = (st.get('language') or '').strip().lower()
                                url = st.get('url') or ''
                                extra_raw = st.get('extra_data') or ''
                                extra_decoded = urllib.parse.unquote(extra_raw).lower()

                                # 1) language 컬럼 검사 (ko, kor, korean, 한국어 등)
                                if lang in korean_langs or any(k in lang for k in ['한국', 'korean', 'kor', 'ko']):
                                    has_korean_sub = True
                                    break

                                # 2) extra_data 컬럼 검사 (URL 디코딩 후 languageCode=kor, languageTag=ko-KR, displayTitle=한국어 등)
                                if any(k in extra_decoded for k in ['kor', 'ko-kr', 'ko_kr', 'korean', '한국']):
                                    has_korean_sub = True
                                    break
                                if re.search(r'(languagecode|languagetag|lang)[=:]\s*ko\b', extra_decoded):
                                    has_korean_sub = True
                                    break

                                # 3) 외부 자막인 경우 파일명 또는 단일 자막 검사
                                if url != '':
                                    sub_disk_path = get_disk_path(url)
                                    if sub_disk_path:
                                        sub_fname = os.path.basename(sub_disk_path).lower()
                                        if any(k in sub_fname for k in ['.ko.', '.kor.', '_ko.', '_kor.', '.korean.', '한글']):
                                            has_korean_sub = True
                                            break

                            # 외화인데 외부 자막이 등록되어 있고 1개만 존재하는 경우도 한글 자막으로 인정
                            if not has_korean_sub and len(m_streams) > 0:
                                valid_ext_subs = [s for s in m_streams if s.get('url') and s['stream_id'] not in dead_stream_ids]
                                if len(valid_ext_subs) == 1:
                                    has_korean_sub = True

                            if not has_korean_sub:
                                # DB에 자막이 없다면, 비디오 파일과 같은 폴더에 자막 파일(ko.srt 등)이 실제로 존재하는지 핀포인트 확인!
                                dir_path = os.path.dirname(video_file)
                                base_stem, _ = os.path.splitext(os.path.basename(video_file))
                                candidate_exts = ['.ko.srt', '.kor.srt', '.ko.smi', '.kor.smi', '.srt', '.smi', '.ko.ass', '.ass']

                                found_disk_sub = None
                                sub_action_type = None
                                use_smi2srt = P.ModelSetting.get_bool('subtitle_use_smi_to_srt')

                                for sub_ext in candidate_exts:
                                    check_path = os.path.join(dir_path, base_stem + sub_ext)
                                    try:
                                        if os.path.exists(check_path):
                                            if use_smi2srt:
                                                conv_res = Task.process_smi_to_srt(check_path, video_file=video_file)
                                                if conv_res:
                                                    if conv_res['action'] in ['smi2srt', 'rename_ko']:
                                                        status['db_smi2srt_count'] += 1
                                                    found_disk_sub = conv_res['new_path']
                                                    sub_action_type = conv_res['action'] # 'smi2srt', 'rename_ko', or 'keep_ko'
                                                    break
                                                else:
                                                    # process_smi_to_srt 결과가 없는 경우:
                                                    # 1) .srt 인데 한글이 포함되지 않은 경우 -> 한글 자막이 아니므로 continue
                                                    if sub_ext == '.srt':
                                                        continue
                                                    # 2) .ko.srt, .kor.srt 등 이미 정상이거나 변환 대상이 아닌 자막 -> 인정
                                                    found_disk_sub = check_path
                                                    break
                                            else:
                                                found_disk_sub = check_path
                                                break
                                    except Exception:
                                        pass

                                full_title = m_row['title']
                                refresh_target_id = m_row['metadata_item_id']
                                if m_row['metadata_type'] == 4:
                                    show_id, show_title = get_show_info(m_row['parent_id'])
                                    if show_title:
                                        full_title = f"{show_title} - {m_row['title']}"
                                    if show_id:
                                        refresh_target_id = show_id

                                if found_disk_sub:
                                    # 디스크에 자막 파일이 존재함 -> 메타 새로고침 지시하여 Plex DB에 등록 유도!
                                    status['db_found_disk_sub_count'] += 1
                                    is_new_refresh = False
                                    target_name = show_title if (m_row['metadata_type'] == 4 and show_title) else m_row['title']

                                    type_code = 'FOUND_DISK'
                                    type_kor = '디스크 자막 감지'
                                    action_prefix = "자막 파일"
                                    if sub_action_type == 'smi2srt':
                                        type_code = 'FOUND_SMI2SRT'
                                        type_kor = 'SMI➔SRT 변환'
                                        action_prefix = "SMI 변환 자막"
                                    elif sub_action_type == 'rename_ko':
                                        type_code = 'FOUND_RENAME_KO'
                                        type_kor = '한글 .ko.srt'
                                        action_prefix = "한글 리네임 자막"
                                    elif sub_action_type == 'keep_ko':
                                        type_code = 'FOUND_DISK'
                                        type_kor = '디스크 한글자막 감지'
                                        action_prefix = "디스크 한글자막"

                                    if refresh_target_id not in refreshed_disk_target_ids:
                                        refreshed_disk_target_ids.add(refresh_target_id)
                                        is_new_refresh = True
                                        ref_status = 'success'
                                        vfs_done = False
                                        try:
                                            vfs_done = Task.try_vfs_refresh(found_disk_sub)
                                            logger.warning(f"[DB기준] 디스크 자막 발견으로 메타 새로고침: {full_title} (ID: {refresh_target_id}, 자막: {found_disk_sub})")
                                            if not PlexWebHandle.refresh_by_id(refresh_target_id):
                                                raise RuntimeError('Plex가 새로고침 요청을 받지 않았습니다.')
                                            status['db_meta_refresh_count'] += 1
                                            time.sleep(0.1)
                                        except Exception as e:
                                            logger.error(f"[DB기준] 메타 새로고침 실패: {str(e)}")
                                            ref_status = 'fail'
                                            fail_reason = str(e)  # except 블록을 나가면 e는 사라진다

                                        vfs_tag = " (VFS 갱신)" if vfs_done else ""
                                        if ref_status == 'success':
                                            ref_detail = f"{action_prefix}({os.path.basename(found_disk_sub)}) 감지{vfs_tag} ➔ 메타 새로고침 지시 완료"
                                        else:
                                            ref_detail = f"메타 새로고침 실패: {fail_reason}"

                                        refresh_item = {
                                            'time': datetime.now().strftime('%H:%M:%S'),
                                            'type': type_code,
                                            'type_kor': type_kor,
                                            'title': target_name,
                                            'target_id': refresh_target_id,
                                            'section_type': section_type,
                                            'found_sub': os.path.basename(found_disk_sub),
                                            'sub_count': 1,
                                            'vfs_done': vfs_done,
                                            'status': ref_status,
                                            'detail': ref_detail
                                        }
                                        status['db_refreshed_items'].append(refresh_item)
                                    else:
                                        for r_item in status['db_refreshed_items']:
                                            if r_item.get('target_id') == refresh_target_id:
                                                r_item['sub_count'] = r_item.get('sub_count', 1) + 1
                                                if r_item.get('status') == 'success':
                                                    vfs_tag = " (VFS 갱신)" if r_item.get('vfs_done') else ""
                                                    r_item['detail'] = f"{action_prefix}({r_item.get('found_sub')} 포함 총 {r_item['sub_count']}편 변환){vfs_tag} ➔ {('TV쇼' if section_type == 'show' else '영화')} 메타 새로고침 완료"
                                                break

                                    found_log = {
                                        'status': status,
                                        'mode': 'db',
                                        'ret': {'log_type': ('FOUND_SMI2SRT' if sub_action_type == 'smi2srt' else ('FOUND_RENAME_KO' if sub_action_type == 'rename_ko' else 'FOUND_DISK_SUB'))},
                                        'title': full_title,
                                        'video_file': video_file,
                                        'found_sub_path': found_disk_sub,
                                        'sub_action_type': sub_action_type,
                                        'section_type': section_type,
                                        'msg': f"{action_prefix} 발견됨 -> 메타 새로고침 지시 완료" if is_new_refresh else f"{action_prefix} 발견됨 (해당 쇼 메타 새로고침 이미 요청됨)"
                                    }
                                    notify(found_log)
                                else:
                                    # 디스크에도 자막이 전혀 없음 -> 한글 자막 누락 외화 (자체자막 태그 여부 감지)
                                    status['db_missing_korean_count'] += 1
                                    hardsub_tag = detect_hardsub_tag(video_file)
                                    if hardsub_tag:
                                        status['db_hardsub_count'] += 1
                                        msg = f"외화 한글 자막 누락 (파일명에 [{hardsub_tag}] 태그 감지: 영상 자체자막일 수 있음)"
                                    else:
                                        msg = f"외화 한글 자막 누락 ({full_title})"

                                    missing_log = {
                                        'status': status,
                                        'mode': 'db',
                                        'ret': {'log_type': 'MISSING_KOREAN'},
                                        'title': full_title,
                                        'video_file': video_file,
                                        'hardsub_tag': hardsub_tag,
                                        'section_type': section_type,
                                        'msg': msg
                                    }
                                    notify(missing_log)
                        except Exception as e:
                            logger.error(f"[DB기준] 미디어({m_row.get('title')}) 검사 오류: {str(e)}")

            # -----------------------------------------------------------------
            # 완료
            # -----------------------------------------------------------------
            if mode == 'dead_sub':
                status['current_step'] = '죽은 자막 무결성 검사 및 정리가 완료되었습니다.'
            elif mode == 'missing_sub':
                status['current_step'] = '외화 한글 자막 누락 및 디스크 자막 진단이 완료되었습니다.'
            else:
                status['current_step'] = '모든 검사가 완료되었습니다.'
            status['is_working'] = 'wait'
            notify({'status': status, 'mode': 'db', 'ret': {}}, force=True)
            return 'wait'

        except Exception as e:
            logger.error(f"[DB기준] Task.start_db 오류 발생: {str(e)}")
            logger.error(traceback.format_exc())
            status['current_step'] = f'오류 발생으로 중단됨: {str(e)}'
            status['is_working'] = 'wait'
            notify({'status': status, 'mode': 'db', 'ret': {}}, force=True)
            return 'wait'
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass

    """
    - 니미 일드에서 에피소드별 메타 새로고침으로 자막 갱신되지 않음. 중드, 외국 다큐, 예능에는 문제 없없음. 버리기 아까운데........
      ERROR (model:205) - Cannot read model from /var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Metadata/TV Shows/a/7ef956be45b59550bb4324550f39aba689c6eab.bundle/Contents/com.plexapp.agents.localmedia
      이게 스캔과정에서 실패해서 나오는지, 파일정리에 나오는지 모르겠음.
    - 에피소드 갱신시마다 쇼 전체 데이터를 가져오는 것도 부담이기도 하니 쇼 기준으로 날리는 것으로 함
    - 에피소드 메타새로고침시 메타 info argument 확인 필요. 예전에는 시즌, 에피 index가 없는게 확실한데 언제 생겼을지도 모름
    - info.json 있을텐데 sjva에 데이터 요청하는 경우도 있음. 확인 필요
    """

    @staticmethod
    def meta_refresh_show(data, new_item_id, new_item_title):
        if data['status']['meta_refresh_show_metadata_item_id'] == None:
            data['status']['meta_refresh_show_metadata_item_id'] = new_item_id
            data['status']['meta_refresh_show_metadata_item_title'] = new_item_title
            
        elif data['status']['meta_refresh_show_metadata_item_id'] == new_item_id:
            logger.debug(f"동일 쇼 : {data['status']['meta_refresh_show_metadata_item_id']}")
        elif data['status']['meta_refresh_show_metadata_item_id'] != new_item_id:
            logger.warning(f"쇼 전체 메타 새로고침 : {data['status']['meta_refresh_show_metadata_item_id']} {data['status']['meta_refresh_show_metadata_item_title']}")
            PlexWebHandle.refresh_by_id(data['status']['meta_refresh_show_metadata_item_id'])
            data['status']['meta_refresh_show_metadata_item_id'] = new_item_id
            data['status']['meta_refresh_show_metadata_item_title'] = new_item_title
            data['status']['meta_refresh_show_count'] += 1


    @staticmethod
    def smi2srt(data):
        try:
            if data['need_smi2srt']:
                PP = F.PluginManager.get_plugin_instance('subtitle_tool')
                ret = PP.SupportSmi2srt.start(data['subtitle_filepath'], remake=False, no_remove_smi=False, no_append_ko=False, no_change_ko_srt=False, fail_move_path=None)
                data['status']['smi2srt_count'] += 1
                data['ret']['smi2srt'] = True
                if ret['list']:
                    data['smi2srt'] = ret['list'][0]
                #logger.debug(ret)
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            logger.error('smi2srt 플러그인 설치 필요')


    readonly_paths = set()
    section_locations = []

    @staticmethod
    def mark_readonly_root(filepath):
        # 1. 라이브러리 루트와 매칭
        for loc in getattr(Task, 'section_locations', []):
            if filepath.startswith(loc):
                if loc not in Task.readonly_paths:
                    Task.readonly_paths.add(loc)
                    logger.warning(f"[DB smi2srt] 읽기전용/머지 드라이브 감지: 라이브러리 경로 전체({loc}) 쓰기 작업을 건너뜁니다.")
                return loc

        # 2. 마운트 포인트 탐색
        p = os.path.abspath(filepath)
        while p and p != os.path.dirname(p):
            try:
                if os.path.ismount(p):
                    if p not in Task.readonly_paths:
                        Task.readonly_paths.add(p)
                        logger.warning(f"[DB smi2srt] 읽기전용/머지 드라이브 감지: 마운트 경로 전체({p}) 쓰기 작업을 건너뜁니다.")
                    return p
            except Exception:
                pass
            p = os.path.dirname(p)

        d = os.path.dirname(filepath)
        Task.readonly_paths.add(d)
        return d

    @staticmethod
    def is_readonly_path(filepath):
        for ro in getattr(Task, 'readonly_paths', set()):
            if filepath.startswith(ro):
                return True
        return False

    @staticmethod
    def try_vfs_refresh(target_path):
        """
        subtitle_use_vfs_refresh 설정 활성화 시, Plex 메타 새로고침 전
        해당 자막/영상 디렉토리에 대해 Rclone vfs/refresh 호출
        """
        if not P.ModelSetting.get_bool('subtitle_use_vfs_refresh'):
            return False
        if not target_path:
            return False
        try:
            if os.path.isfile(target_path) or os.path.splitext(target_path)[1]:
                target_dir = os.path.dirname(target_path)
            else:
                target_dir = target_path
            if target_dir:
                logger.warning(f"[VFS] Rclone vfs/refresh 요청: {target_dir}")
                vfs_refresh(target_dir)
                return True
        except Exception as e:
            logger.error(f"[VFS] vfs_refresh 실패: {str(e)}")
            return False
        return False

    @staticmethod
    def process_smi_to_srt(filepath, video_file=None):
        """
        subtitle_use_smi_to_srt 설정 활성화 시 DB 검사 도중 파일 변환/복사 생성 수행:
        1. .smi 파일: subtitle_tool 플러그인으로 .ko.srt 변환 (이미 .ko.srt 존재 시 스킵)
        2. .srt 파일: 언어 태그 없는 순수 .srt 중 실제 한글(20자 이상) 포함 시 .ko.srt 로 복사 생성
           - 이미 해당 .ko.srt 가 있거나 외국어 태그(eng, sdh 등)가 있는 경우 스킵
           - 읽기전용 드라이브인 경우 복사 쓰기 없이 한글 자막으로 인정(유지): keep_ko
        """
        if not filepath or not os.path.exists(filepath):
            return None

        is_readonly = Task.is_readonly_path(filepath)

        FOREIGN_LANG_CODES = {
            'eng', 'en', 'ja', 'jpn', 'chi', 'zh', 'chs', 'cht', 'spa', 'es',
            'fre', 'fra', 'fr', 'ger', 'de', 'deu', 'ita', 'it', 'rus', 'ru',
            'por', 'pt', 'vie', 'vi', 'tha', 'th', 'ind', 'id', 'ara', 'ar',
            'heb', 'he', 'pol', 'pl', 'tur', 'tr', 'dut', 'nl', 'dan', 'da',
            'nor', 'no', 'swe', 'sv', 'fin', 'fi', 'cze', 'cs', 'hun', 'hu',
            'gre', 'el', 'rum', 'ro', 'bul', 'bg', 'ukr', 'uk'
        }

        try:
            ext = os.path.splitext(filepath)[1].lower()
            basename = os.path.basename(filepath)
            dirname = os.path.dirname(filepath)
            base_stem, _ = os.path.splitext(basename)

            # 대상 .ko.srt 경로 계산
            if base_stem.lower().endswith('.ko'):
                target_ko_srt = filepath
            else:
                target_ko_srt = os.path.join(dirname, base_stem + '.ko.srt')

            # 이미 해당 파일명의 .ko.srt 가 디스크에 존재하는 경우 -> 추가 작업 불필요
            if os.path.exists(target_ko_srt) and os.path.abspath(filepath) != os.path.abspath(target_ko_srt):
                return None

            # 비디오 파일 경로가 제공된 경우, 비디오 기준 정식 .ko.srt 가 이미 존재하는지 확인
            if video_file:
                v_stem, _ = os.path.splitext(os.path.basename(video_file))
                v_dir = os.path.dirname(video_file)
                v_ko_srt = os.path.join(v_dir, v_stem + '.ko.srt')
                if os.path.exists(v_ko_srt) and os.path.abspath(filepath) != os.path.abspath(v_ko_srt):
                    # 비디오에 매칭되는 정식 .ko.srt 가 이미 있으므로 기타 보조 .srt 는 추가 복사하지 않음
                    return None

            # 1) .smi 파일 변환
            if ext == '.smi':
                if is_readonly:
                    return None
                try:
                    PP = F.PluginManager.get_plugin_instance('subtitle_tool')
                    if PP and hasattr(PP, 'SupportSmi2srt'):
                        # merge 드라이브 원본 삭제 불가 대응: no_remove_smi=True 로 원본 유지하며 .ko.srt 만 생성
                        PP.SupportSmi2srt.start(
                            filepath, 
                            remake=False, 
                            no_remove_smi=True, 
                            no_append_ko=False, 
                            no_change_ko_srt=False
                        )
                        # 변환 후 생성 가능한 SRT 파일 경로 후보군 확인
                        candidates = [
                            os.path.join(dirname, base_stem + '.ko.srt'),
                            os.path.join(dirname, base_stem + '.srt')
                        ]
                        if base_stem.lower().endswith('.ko'):
                            candidates.insert(0, os.path.join(dirname, base_stem[:-3] + '.ko.srt'))

                        target_srt = None
                        for cand in candidates:
                            if os.path.exists(cand):
                                target_srt = cand
                                break

                        if target_srt:
                            logger.warning(f"[DB smi2srt] .smi 변환 완료: {basename} -> {os.path.basename(target_srt)}")
                            return {'action': 'smi2srt', 'new_path': target_srt, 'old_path': filepath}
                except OSError as e:
                    if getattr(e, 'errno', None) in [30, 13] or 'Read-only' in str(e) or 'Permission' in str(e):
                        Task.mark_readonly_root(filepath)
                        return None
                    logger.error(f"[DB smi2srt] 변환 에러 ({filepath}): {str(e)}")
                except Exception as e:
                    logger.error(f"[DB smi2srt] 변환 에러 ({filepath}): {str(e)}")
                return None

            # 2) .srt 파일 중 언어 태그가 없는 경우: 한글 포함 여부 검사 후 .ko.srt 로 복사 생성
            if ext == '.srt':
                lower_name = basename.lower()

                # 이미 한국어 태그가 붙어있는 경우 (.ko.srt, _ko.srt, ,ko.srt, .kor.srt 등)
                if re.search(r'[\._\-, ](ko|kor|korean)(\.[\w\-]+)?\.srt$', lower_name):
                    return None

                # 파일명 토큰 분석: 외래어 언어 코드(eng, ja, chi 등)가 포함되어 있는지 확인
                stem_tokens = set(re.split(r'[\._\-, ]+', base_stem.lower()))
                if stem_tokens.intersection(FOREIGN_LANG_CODES):
                    return None

                # 정규식 패턴: 외국어 코드 및 sdh/forced/cc/hi 등 서브태그가 포함된 경우 (예: .eng.sdh.srt)
                foreign_pattern = r'[\._\-, ](' + '|'.join(FOREIGN_LANG_CODES) + r')([\._\-, ][\w\-]+)*\.srt$'
                if re.search(foreign_pattern, lower_name):
                    return None

                # 파일 본문에서 완성형 한글(\uac00-\ud7a3) 검사: 최소 20글자 이상이어야 유효한 한글 자막으로 인정
                content = None
                for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr', 'utf-16']:
                    try:
                        with open(filepath, 'r', encoding=enc, errors='ignore') as f:
                            content = f.read(65536)
                            if content and len(re.findall(r'[\uac00-\ud7a3]', content)) >= 20:
                                break
                    except Exception:
                        pass

                if content and len(re.findall(r'[\uac00-\ud7a3]', content)) >= 20:
                    # 머지/읽기전용 드라이브로 이미 확인된 경우 복사 쓰기 시도 없이 한글 자막으로 인정(유지)
                    if is_readonly:
                        return {'action': 'keep_ko', 'new_path': filepath, 'old_path': filepath}

                    try:
                        # 원본 삭제/이름변경 불가 머지 드라이브 대응: 원본은 그대로 두고 .ko.srt 로 복사 생성
                        shutil.copyfile(filepath, target_ko_srt)
                        logger.warning(f"[DB smi2srt] 한글 자막 감지되어 .ko.srt 복사 생성: {basename} -> {os.path.basename(target_ko_srt)}")
                        return {'action': 'rename_ko', 'new_path': target_ko_srt, 'old_path': filepath}
                    except OSError as e:
                        # 복사 쓰기마저 불가능한 완전 읽기 전용 스토리지인 경우
                        if getattr(e, 'errno', None) in [30, 13] or 'Read-only' in str(e) or 'Permission' in str(e):
                            Task.mark_readonly_root(filepath)
                            return {'action': 'keep_ko', 'new_path': filepath, 'old_path': filepath}
                        raise
        except Exception as e:
            logger.error(f"[DB smi2srt] process_smi_to_srt 예외 ({filepath}): {str(e)}")

        return None





    @staticmethod
    def get_show_meda(con, data, episode_data, is_video=False):

        data['epidode_title'] = episode_data['title']
        data['episode_index'] = episode_data['metadata_items_index']
        data['epidose_metadata_items_id'] = episode_data['metadata_items_id']

        query = '''SELECT id, parent_id, title, metadata_items.'index' AS metadata_items_index FROM metadata_items WHERE id = ?'''
        ce = con.execute(query, (episode_data['metadata_items_parent_id'],))
        ce.row_factory = dict_factory
        season_data = ce.fetchall()[0]

        data['season_title'] = season_data['title']
        data['season_index'] = season_data['metadata_items_index']
        data['season_metadata_items_id'] = season_data['metadata_items_index']
        
        ce = con.execute(query, (season_data['parent_id'],))
        ce.row_factory = dict_factory
        show_data = ce.fetchall()[0]
        data['show_title'] = show_data['title']
        data['show_metadata_items_id'] = show_data['id']

        if is_video:
            query = """SELECT url, codec, language FROM media_streams WHERE media_item_id = ? AND stream_type_id = 3 AND url != ''"""
            ce = con.execute(query, (episode_data['media_items_id'],))
            ce.row_factory = dict_factory
            rows = ce.fetchall()
            for row in rows:
                row['sub'] = row['url'][7:].replace('%20', ' ').replace('%25', '%')
                #logger.debug(row['sub'])
                row['sub'] = os.path.basename(row['sub'])
            data['episode_subtitle'] = rows
            







    @staticmethod
    def find_video(dir_path, fname):
        fn, ext  = os.path.splitext(fname)
        #logger.error((fn, ext))
        tmps = fn.rsplit('.', 1)
        search_filename = fn
        search_filename2 = None
        if len(tmps[-1]) == 2 or len(tmps[-1]) == 3:
            search_filename = tmps[0]
            search_filename2 = fn
        elif tmps[-1] in ['forced', 'normal', 'default']:
            search_filename = tmps[0]

        files = os.listdir(dir_path)
        #logger.error(files)
        
        files = [f for f in files if not re.match(SUBTITLE_EXTS, f)]
        #logger.error(files)
        for f in files:
            #logger.debug(f)
            #logger.debug(search_filename in f)
            if search_filename in f and os.path.splitext(f)[-1].lstrip('.') in VIDEO_EXTS:
                return True, f

        """
        files_1 = [f for f in files if re.match(search_filename, f)]
        for f in files_1:
            if os.path.splitext(f)[-1].lstrip('.') in VIDEO_EXTS:
                return True, f
        
        # org.srt
        files_2 = None
        if search_filename2 is not None:
            files_2 = [f for f in files if re.match(search_filename2, f)]
            for f in files_2:
                if os.path.splitext(f)[-1].lstrip('.') in VIDEO_EXTS:
                    return True, f

        logger.warning("비디오 파일 찾기 실패")
        """
        logger.warning(search_filename)
        logger.warning(files)
        #logger.warning(files_1)
        #logger.warning(files_2)

        return False, None



































QUERY = f'''
SELECT
    metadata_items.id AS metadata_items_id, 
    metadata_items.parent_id AS metadata_items_parent_id, 
    metadata_items.library_section_id AS library_section_id, 
    metadata_items.metadata_type AS metadata_type, 
    metadata_items.guid AS guid,
    metadata_items.media_item_count AS media_item_count,
    metadata_items.title AS title,
    metadata_items.year AS year,
    metadata_items.'index' AS metadata_items_index,
    metadata_items.hash AS metadata_items_hash,
    media_items.id AS media_items_id,
    media_items.section_location_id AS section_location_id,
    media_items.width AS width,
    media_items.height AS height,
    media_items.size AS size,
    media_items.duration AS duration,
    media_items.bitrate AS bitrate,
    media_items.container AS container,
    media_items.video_codec AS video_codec,
    media_items.audio_codec AS audio_codec,
    media_parts.id AS media_parts_id,
    media_parts.directory_id AS media_parts_directory_id,
    media_parts.hash AS media_parts_hash,
    media_parts.file AS file,
    media_streams.id AS media_streams_id,
    media_streams.url AS url
FROM metadata_items, media_items, media_parts, media_streams
WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND media_items.id == media_streams.media_item_id AND media_streams.url = ?'''


QUERY_VIDEO = f'''
SELECT
    metadata_items.id AS metadata_items_id, 
    metadata_items.parent_id AS metadata_items_parent_id, 
    metadata_items.library_section_id AS library_section_id, 
    metadata_items.metadata_type AS metadata_type, 
    metadata_items.guid AS guid,
    metadata_items.media_item_count AS media_item_count,
    metadata_items.title AS title,
    metadata_items.year AS year,
    metadata_items.'index' AS metadata_items_index,
    metadata_items.hash AS metadata_items_hash,
    media_items.id AS media_items_id,
    media_items.section_location_id AS section_location_id,
    media_items.width AS width,
    media_items.height AS height,
    media_items.size AS size,
    media_items.duration AS duration,
    media_items.bitrate AS bitrate,
    media_items.container AS container,
    media_items.video_codec AS video_codec,
    media_items.audio_codec AS audio_codec,
    media_parts.id AS media_parts_id,
    media_parts.directory_id AS media_parts_directory_id,
    media_parts.hash AS media_parts_hash,
    media_parts.file AS file
FROM metadata_items, media_items, media_parts
WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id AND file = ?'''



VIDEO_EXTS = ['3g2', '3gp', 'asf', 'asx', 'avc', 'avi', 'avs', 'bivx', 'bup', 'divx', 'dv', 'dvr-ms', 'evo', 'fli', 'flv', 'm2t', 'm2ts', 'm2v', 'm4v', 'mkv', 'mov', 'mp4', 'mpeg', 'mpg', 'mts', 'nsv', 'nuv', 'ogm', 'ogv', 'tp', 'pva', 'qt', 'rm', 'rmvb', 'sdp', 'svq3', 'strm', 'ts', 'ty', 'vdr', 'viv', 'vob', 'vp3', 'wmv', 'wtv', 'xsp', 'xvid', 'webm']

#SUBTITLE_EXTS =  ['ass', 'ssa', 'smi', 'srt', 'psb']

#Task.start('start', '23')


IGNORE_DIRS =  ['\\bextras?\\b', '!?samples?', 'bonus', '.*bonus disc.*', 'bdmv', 'video_ts', '^interview.?$', '^scene.?$', '^trailer.?$', '^deleted.?(scene.?)?$', '^behind.?the.?scenes$', '^featurette.?$', '^short.?$', '^other.?$', 'extras', 'sub']