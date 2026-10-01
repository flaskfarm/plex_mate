import os
import time

import requests

from .setup import *

logger = P.logger


class ShyniBackend:

    @staticmethod
    def enabled():
        return P.ModelSetting.get_bool('scan_shyni_use')

    @staticmethod
    def get_config():
        # 연결 정보는 웹훅 설정의 샤이니 항목(intro_shyni_*)을 공유한다 — 한 곳만 입력.
        url = (P.ModelSetting.get('intro_shyni_url') or '').strip().rstrip('/')
        token = (P.ModelSetting.get('intro_shyni_token') or '').strip()
        return url, token

    @staticmethod
    def map_path(local_path):
        """plex_mate가 보는 경로 → 샤이니 서버가 보는 경로 (scan_shyni_path_rule: 'src|dst' 줄단위)."""
        if not local_path:
            return None
        rules = P.ModelSetting.get_list('scan_shyni_path_rule')
        for rule in rules:
            tmps = rule.split('|')
            if len(tmps) != 2:
                continue
            src, dst = tmps[0].strip(), tmps[1].strip()
            if src and local_path.startswith(src):
                return (dst + local_path[len(src):]).replace('\\', '/')
        return local_path.replace('\\', '/')

    @staticmethod
    def _gds_metadata(db_item):
        """수신 원문은 GDS_TOOL JSON에 그대로 보존된다. 마운트 파일은 읽지 않는다."""
        try:
            if (db_item.callback or '') != 'gds_tool' or not db_item.callback_id:
                return {}
            gds = F.PluginManager.get_plugin_instance('gds_tool')
            model = gds.get_module('fp').web_list_model
            fp_item = model.get_by_id(db_item.callback_id.rsplit('_', 1)[-1])
            if fp_item is None or not fp_item.data:
                return {}
            md = (fp_item.data.get('msg') or {}).get('data') or {}
            return md if isinstance(md, dict) else {}
        except Exception as e:
            logger.warning(f'[Shyni] GDS 수신 자료 조회 실패(무시): {type(e).__name__}')
            return {}

    @staticmethod
    def gather_probe_payload(db_item, shyni_path):
        """폴더별 압축 자료는 해제/경로 재작성 없이 샤이니가 검증하도록 전달한다.

        토큰은 폴더 안 파일명만 식별한다. 실제 범위는 변환된 스캔 path이며,
        여기서 파일 크기 확인이나 ffprobe를 실행하지 않는다.
        """
        md = ShyniBackend._gds_metadata(db_item)
        probe = md.get('scan_probe')
        if (isinstance(probe, dict) and probe.get('v') == 1
                and probe.get('codec') == 'zlib-json'
                and isinstance(probe.get('data'), str)
                and 0 < len(probe['data']) <= 65536):
            return {'scan_probe': probe}
        files = ShyniBackend.gather_ffprobe(db_item, shyni_path, metadata=md)
        return {'files': files} if files else {}

    @staticmethod
    def gather_ffprobe(db_item, shyni_path, metadata=None):
        """기존 파일 한 개짜리 ffprobe_data/ffprobe 메시지와의 호환 경로."""
        try:
            md = metadata if metadata is not None else ShyniBackend._gds_metadata(db_item)
            ffprobe = md.get('ffprobe_data') or md.get('ffprobe')
            if not ffprobe:
                return None
            size = md.get('size') or md.get('file_size') or 0
            if not size:
                try:
                    size = os.path.getsize(db_item.target)
                except Exception:
                    size = 0
            return [{'path': shyni_path, 'size': size, 'ffprobe': ffprobe}]
        except Exception as e:
            logger.error(f'[Shyni] ffprobe 자료 조회 실패(무시): {e}')
            return None

    @staticmethod
    def _section_by_path(url, headers, shyni_path):
        res = requests.get(f'{url}/compat/section_by_path', params={'path': shyni_path},
                           headers=headers, timeout=15)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json()['section_id']

    @staticmethod
    def request_scan(db_item):
        """ADD/REMOVE 공통 — 대상 경로가 속한 샤이니 Section을 찾아 부분 스캔 요청.

        FF 호스트의 파일 존재 여부와 무관하게 즉시 보낸다 — 파일이 아직 마운트에 안
        보이는 경우의 refresh·대기는 샤이니 서버가 자체 수행한다(mode=add + wait).
        db_item의 shyni_status/shyni_job_id만 갱신하고 저장은 호출자(finally save)가 한다."""
        try:
            if not ShyniBackend.enabled():
                return
            if db_item.shyni_status:  # READY 재진입 등으로 중복 요청 방지
                return
            url, token = ShyniBackend.get_config()
            if not url or not token:
                db_item.shyni_status = 'SKIP'
                return
            headers = {'X-Plex-Token': token}

            if db_item.mode == 'REMOVE_FOLDER':
                scan_mode, target = 'remove', db_item.target
            elif db_item.mode == 'REMOVE_FILE':
                scan_mode = 'remove'
                target = db_item.target.rsplit('/', 1)[0] if db_item.target.startswith('/') \
                    else db_item.target.rsplit('\\', 1)[0]
            else:
                scan_mode, target = 'add', db_item.target
            shyni_path = ShyniBackend.map_path(target)

            section_id = ShyniBackend._section_by_path(url, headers, shyni_path)
            if section_id is None:
                db_item.shyni_status = 'NOT_FIND_LIBRARY'
                return

            body = {
                'path': shyni_path,
                'mode': scan_mode,
                'wait': max(P.ModelSetting.get_int('scan_max_wait_time'), 1) * 60,
            }
            if scan_mode == 'add':
                body.update(ShyniBackend.gather_probe_payload(db_item, shyni_path))
            res = requests.post(
                f'{url}/library/sections/{section_id}/refresh', json=body,
                headers={**headers, 'Accept': 'application/json',
                         'Idempotency-Key': f'pm-scan-{db_item.id}-{db_item.mode}'},
                timeout=30,
            )
            res.raise_for_status()
            job_id = res.headers.get('X-Job-Id') or (res.json() or {}).get('job_id')
            db_item.shyni_job_id = str(job_id) if job_id else None
            db_item.shyni_status = 'RUNNING' if job_id else 'REQUESTED'
            logger.info(f'[Shyni] scan 요청: item={db_item.id} mode={db_item.mode} '
                        f'section={section_id} job={job_id} '
                        f'ffprobe={"files" in body or "scan_probe" in body}')
        except Exception as e:
            logger.error(f'[Shyni] scan 요청 실패: item={db_item.id} {e}')
            db_item.shyni_status = 'ERROR'

    # 대상별 실행이 끝났다고 볼 수 있는 상태(F-4 부분 성공 판정용)
    TERMINAL_OK = ('FINISH', 'REQUESTED')
    TERMINAL_FAIL = ('FAILED', 'ERROR', 'NOT_FIND_LIBRARY', 'NOT_FIND_IN_LIBRARY', 'SKIP')

    @staticmethod
    def finalize_plex_off(db_item):
        """PLEX 스캔 사용 OFF(샤이니 단독) — 샤이니 결과가 확정되면 항목을 FINISH 처리한다.
        set_status가 FINISH_*에서 GDS callback을 1회 발사하는 기존 경로를 그대로 탄다."""
        if not ShyniBackend.enabled():
            # Plex도 샤이니도 안 쓰는 잘못된 조합 — READY로 영원히 남지 않게 종료
            db_item.set_status('FINISH_SHYNI_FAILED', save=True)
            return
        st = db_item.shyni_status
        if st in ShyniBackend.TERMINAL_OK:
            db_item.set_status('FINISH_SHYNI', save=True)
        elif st in ShyniBackend.TERMINAL_FAIL:
            db_item.set_status('FINISH_SHYNI_FAILED', save=True)
        # RUNNING/None → READY 유지, 다음 filecheck 주기에 재판정

    @staticmethod
    def _refresh_path(target):
        # 경로 변환 후 파일명만 벗긴다. 점이 들어간 폴더를 파일로 오인하지 않는다.
        target = ShyniBackend.map_path(target).rstrip('/')
        file_exts = {'.yaml', '.yml', '.nfo', '.mp4', '.mkv', '.avi', '.ts', '.m2ts',
                     '.mov', '.m4v', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wav',
                     '.opus', '.wma', '.zip', '.cbz', '.epub', '.pdf', '.txt'}
        if os.path.splitext(target)[1].lower() in file_exts:
            return target.rsplit('/', 1)[0]
        return target

    @staticmethod
    def _refresh_metadata(url, headers, db_item, shyni_path):
        """찾은 항목만 refresh. 404는 호출자가 등록 대기/부분 스캔으로 처리한다."""
        res = requests.get(f'{url}/compat/metadata_by_path', params={'path': shyni_path},
                           headers=headers, timeout=15)
        if res.status_code == 404:
            return False
        res.raise_for_status()
        meta_id = res.json()['metadata_id']
        attempt = db_item.shyni_job_id or getattr(db_item, 'filecheck_count', 0)
        res = requests.put(f'{url}/library/metadata/{meta_id}/refresh',
                           headers={**headers, 'Accept': 'application/json',
                                    'Idempotency-Key': f'pm-refresh-{db_item.id}-{attempt}'}, timeout=30)
        res.raise_for_status()
        job_id = res.headers.get('X-Job-Id') or (res.json() or {}).get('job_id')
        db_item.shyni_job_id = str(job_id) if job_id else None
        db_item.shyni_status = 'RUNNING' if job_id else 'FINISH'
        logger.info(f'[Shyni] refresh 요청: item={db_item.id} meta={meta_id} job={job_id}')
        return True

    @staticmethod
    def _scan_before_refresh(url, headers, db_item, shyni_path):
        """YAML이 영상보다 먼저 도착한 경우: 폴더 등록 → metadata refresh 순서 보장.

        기존 job 필드에 단계와 만료 시각을 보존해 재시작 후에도 이어서 처리한다.
        scan 성공만으로 FINISH로 표시하지 않고 반드시 metadata refresh를 수행한다.
        """
        section_id = ShyniBackend._section_by_path(url, headers, shyni_path)
        if section_id is None:
            db_item.shyni_status = 'NOT_FIND_LIBRARY'
            return
        wait = max(P.ModelSetting.get_int('scan_max_wait_time'), 1) * 60
        attempt = getattr(db_item, 'filecheck_count', 0)
        body = {'path': shyni_path, 'mode': 'add', 'wait': wait}
        body.update(ShyniBackend.gather_probe_payload(db_item, shyni_path))
        res = requests.post(f'{url}/library/sections/{section_id}/refresh',
                            params={'force': 1},
                            json=body,
                            headers={**headers, 'Accept': 'application/json',
                                     'Idempotency-Key': f'pm-refresh-scan-{db_item.id}-{attempt}'},
                            timeout=30)
        res.raise_for_status()
        job_id = res.headers.get('X-Job-Id') or (res.json() or {}).get('job_id')
        db_item.shyni_job_id = f'refresh-scan:{job_id or 0}:{int(time.time()) + wait}'
        db_item.shyni_status = 'RUNNING'
        logger.info(f'[Shyni] refresh 대상 등록 대기: item={db_item.id} '
                    f'section={section_id} scan_job={job_id} wait={wait}s')

    @staticmethod
    def request_refresh(db_item):
        """REFRESH 모드 — 경로의 샤이니 metadata를 찾아 재동기화 요청."""
        try:
            if not ShyniBackend.enabled():
                return
            if db_item.shyni_status:
                return
            url, token = ShyniBackend.get_config()
            if not url or not token:
                db_item.shyni_status = 'SKIP'
                return
            headers = {'X-Plex-Token': token}
            shyni_path = ShyniBackend._refresh_path(db_item.target)
            if not ShyniBackend._refresh_metadata(url, headers, db_item, shyni_path):
                ShyniBackend._scan_before_refresh(url, headers, db_item, shyni_path)
        except Exception as e:
            logger.error(f'[Shyni] refresh 요청 실패: item={db_item.id} {e}')
            db_item.shyni_status = 'ERROR'

    @staticmethod
    def _poll_item(url, headers, item):
        job_id = str(item.shyni_job_id or '')
        waiting_refresh = job_id.startswith('refresh-scan:')
        deadline = None
        if waiting_refresh:
            _, job_id, deadline = job_id.split(':', 2)
            deadline = int(deadline)
        if job_id and job_id != '0':
            res = requests.get(f'{url}/compat/jobs/{job_id}', headers=headers, timeout=15)
            if res.status_code == 404:
                item.shyni_status = 'ERROR'
                return
            res.raise_for_status()
            job = res.json()
            if job['status'] == 'failed':
                item.shyni_status = 'FAILED'
                logger.warning(f"[Shyni] job 실패: item={item.id} error={job.get('error')}")
                return
            if job['status'] != 'completed':
                return
        elif not waiting_refresh:
            item.shyni_status = 'ERROR'
            return
        if not waiting_refresh:
            item.shyni_status = 'FINISH'
            return
        # 다른 ADD 스캔과 겹쳐 already_running으로 끝난 경우에도 다음 주기에 재조회한다.
        # 대기 중 scan을 반복 발사하거나 섹션 전체를 refresh하지 않는다.
        if ShyniBackend._refresh_metadata(
                url, headers, item, ShyniBackend._refresh_path(item.target)):
            return
        if time.time() >= deadline:
            item.shyni_status = 'NOT_FIND_IN_LIBRARY'
            logger.warning(f'[Shyni] refresh 대상 등록 대기 만료: item={item.id}')

    @staticmethod
    def poll_running():
        """filecheck 주기마다 호출 — RUNNING 항목의 job 상태를 확인해 확정한다."""
        try:
            if not ShyniBackend.enabled():
                return
            from .model_scan import ModelScanItem
            with F.app.app_context():
                items = F.db.session.query(ModelScanItem).filter(
                    ModelScanItem.shyni_status == 'RUNNING').all()
                if not items:
                    return
                url, token = ShyniBackend.get_config()
                if not url or not token:
                    return
                headers = {'X-Plex-Token': token}
                for item in items:
                    try:
                        ShyniBackend._poll_item(url, headers, item)
                    except Exception as e:
                        logger.error(f'[Shyni] job 폴링 실패: item={item.id} {e}')
                F.db.session.commit()
        except Exception as e:
            logger.error(f'[Shyni] poll_running 오류: {e}')
