"""Shyni(샤이니) backend — plex_mate 스캔 이벤트를 샤이니 서버에도 분기한다 (서버 계약 F절).

원칙:
  - Plex 쪽 로직은 건드리지 않는다. 파일 확인이 끝난 시점(공통 준비 완료)에 독립 실행.
  - GDS_TOOL 원문(fp_item.data.msg.data)에 ffprobe_data가 있으면 스캔 요청에 함께 실어
    샤이니가 자체 분석을 생략하게 한다(A10). 없으면 경로만 보낸다.
  - 샤이니 Section ID는 Plex Section ID와 다르다 — /compat/section_by_path로 자동 결정.
  - 비동기 job: POST refresh → job_id 기록(shyni_status='RUNNING') → filecheck 주기에서
    /compat/jobs/{id} 폴링으로 FINISH/FAILED 확정. 실패는 Plex와 독립(부분 성공 허용, F-4).
"""
import os

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
    def gather_ffprobe(db_item, shyni_path):
        """GDS_TOOL fp_item 원문에서 ffprobe 자료를 찾는다. 없으면 None(샤이니가 직접 분석)."""
        try:
            if (db_item.callback or '') != 'gds_tool' or not db_item.callback_id:
                return None
            gds = F.PluginManager.get_plugin_instance('gds_tool')
            model = gds.get_module('fp').web_list_model
            fp_item = model.get_by_id(db_item.callback_id.rsplit('_', 1)[-1])
            if fp_item is None or not fp_item.data:
                return None
            md = (fp_item.data.get('msg') or {}).get('data') or {}
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
                files = ShyniBackend.gather_ffprobe(db_item, shyni_path)
                if files:
                    body['files'] = files
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
                        f'section={section_id} job={job_id} ffprobe={"files" in body}')
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
            # FF 마운트에 안 보여도 동작해야 하므로 os.path.isdir 대신 확장자로 파일/폴더 판단
            ext = os.path.splitext(db_item.target)[1]
            is_file = bool(ext) and len(ext) <= 6
            target = os.path.dirname(db_item.target) if is_file else db_item.target
            shyni_path = ShyniBackend.map_path(target)
            res = requests.get(f'{url}/compat/metadata_by_path', params={'path': shyni_path},
                               headers=headers, timeout=15)
            if res.status_code == 404:
                db_item.shyni_status = 'NOT_FIND_IN_LIBRARY'
                return
            res.raise_for_status()
            meta_id = res.json()['metadata_id']
            res = requests.put(f'{url}/library/metadata/{meta_id}/refresh',
                               headers={**headers, 'Accept': 'application/json'}, timeout=30)
            res.raise_for_status()
            job_id = res.headers.get('X-Job-Id') or (res.json() or {}).get('job_id')
            db_item.shyni_job_id = str(job_id) if job_id else None
            db_item.shyni_status = 'RUNNING' if job_id else 'FINISH'
            logger.info(f'[Shyni] refresh 요청: item={db_item.id} meta={meta_id} job={job_id}')
        except Exception as e:
            logger.error(f'[Shyni] refresh 요청 실패: item={db_item.id} {e}')
            db_item.shyni_status = 'ERROR'

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
                        res = requests.get(f'{url}/compat/jobs/{item.shyni_job_id}',
                                           headers=headers, timeout=15)
                        if res.status_code == 404:
                            item.shyni_status = 'ERROR'
                            continue
                        res.raise_for_status()
                        job = res.json()
                        if job['status'] == 'completed':
                            item.shyni_status = 'FINISH'
                        elif job['status'] == 'failed':
                            item.shyni_status = 'FAILED'
                            logger.warning(f"[Shyni] job 실패: item={item.id} error={job.get('error')}")
                    except Exception as e:
                        logger.error(f'[Shyni] job 폴링 실패: item={item.id} {e}')
                F.db.session.commit()
        except Exception as e:
            logger.error(f'[Shyni] poll_running 오류: {e}')
