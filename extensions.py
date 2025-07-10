import pathlib
import functools
import json
import traceback
import time
import datetime
import os
import urllib
import sqlite3
import shutil
from typing import Any, Optional, Union
from threading import Thread

import flask
import requests

from support import SupportSubprocess
from support import AlchemyEncoder
from plugin.create_plugin import PluginBase
from plugin.logic_module_base import PluginModuleBase, PluginPageBase

from .setup import F, P
from .plex_db import PlexDBHandle


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_rc_servers() -> list[dict]:
    '''
    로컬경로|리모트경로|ADDR#VFS|USER|PASS
    '''
    servers = []
    for user_rule in P.ModelSetting.get_list('scan_vfs_change_rule', comment=None):
        tmps = user_rule.split('|')
        if len(tmps) < 3:
            P.logger.warning(f'vfs/refresh 규칙을 확인하세요: {user_rule}')
            continue
        addr, _, vfs = tmps[2].partition('#')
        if vfs and ':' not in vfs:
            vfs = vfs if vfs.endswith(':') else f'{vfs}:'
        auth, _, addr = addr.rpartition('@')
        username, _, password = auth.partition(':')
        servers.append({
            'local': pathlib.Path(tmps[0]).as_posix(),
            'remote': pathlib.Path(tmps[1]).as_posix() if tmps[1] else '',
            'address': addr,
            'user': tmps[3] if len(tmps) > 4 else username,
            'pass': tmps[4] if len(tmps) > 4 else password,
            'vfs': vfs,
        })
    return servers


def get_scan_targets(target: str, section_id: int | str = None) -> dict[str, int]:
        target_ = pathlib.Path(pathlib.Path(target).as_posix())
        locations = PlexDBHandle.section_location(library_id=section_id)
        targets = {}
        for location in locations:
            root = pathlib.Path(pathlib.Path(location["root_path"]).as_posix())
            if target_.is_relative_to(root):
                targets[target_.as_posix()] = location['section_id']
            elif root.is_relative_to(target_):
                targets[root.as_posix()] = location['section_id']
        if targets:
            P.logger.debug(f'섹션 ID 검색 결과: {set(targets.values())}')
        else:
            P.logger.error(f'섹션 ID를 찾을 수 없습니다: {target}')
        return targets


def rc_command(function: callable) -> callable:
    @functools.wraps(function)
    def wrapper(*args: tuple, **kwds: dict) -> dict:
        data = function(*args, **kwds)
        command = '/'.join(function.__name__.split('__'))
        server = data.get('server')
        rclone = F.PluginManager.get_plugin_instance('rclone')
        cmd = [
            rclone.ModelSetting.get('rclone_path'),
            '--timeout=0',
            'rc',
            command,
            f'--url={server["address"]}'
        ]
        if server['user']:
            cmd.extend([f"--user={server['user']}", f"--pass={server['pass']}"])
        if data.get('args'):
            cmd.extend(data.get('args'))
        if data.get('async'):
            cmd.append('_async=true')
        #P.logger.debug(f'RC command: {cmd}')
        result = SupportSubprocess.execute_command_return(cmd)
        try:
            '''
            {'error': '', ...}
            {'result': {'/path/to': 'Invalid...'}}
            {'result': {'/path/to': 'OK'}}
            {'forgotten': ['/path/to']}
            {'jobid': 12345}
            '''
            rc_result = json.loads(result['log'])
            if data.get('async'):
                job_id = rc_result["jobid"]
                job_status = job__status(server, int(job_id))
                P.logger.debug(f"RC job status: {job_status}")
                counter = 1
                while not job_status['finished']:
                    # --rc-job-expire-duration=60s --rc-job-expire-interval=10s
                    # 작업 상태 확인: 10~60초
                    time.sleep(min(counter**2, 30))
                    job_status = job__status(server, int(job_id))
                    counter = counter + 1
                    P.logger.debug(f'Waiting for the RC job: {job_id}')
                P.logger.debug(f"RC job status: {job_status}")
                if job_status.get('error'):
                    P.logger.error(job_status)
                    raise Exception(job_status.get('error'))
                return job_status.get('output')
            else:
                if rc_result.get('error'):
                    P.logger.error(rc_result)
                    raise Exception(rc_result.get('error'))
                #P.logger.debug(f'RC result: {rc_result}')
                return rc_result
        except:
            P.logger.error(traceback.format_exc())
            P.logger.error(f'result={result}')
            P.logger.error(f'cmd={cmd}')
            P.logger.error(f'rclone={shutil.which(rclone.ModelSetting.get("rclone_path"))}')
            return {}
    return wrapper


@rc_command
def job__status(server: dict, job_id: int) -> dict:
    json_str = '{"jobid":%s}' % job_id
    return {
        'server': server,
        'args': [f"jobid={job_id}"],
    }


@rc_command
def vfs__refresh(server: dict, remote_path: str = None, recursive: bool = False, async_: bool = False) -> dict:
    data = {
        'server': server,
        'async': async_,
        'args': ['--fast-list'],
    }
    if remote_path:
        data['args'].append(f'dir={remote_path}')
    if recursive:
        data['args'].append('recursive=true')
    if server['vfs']:
        data['args'].append(f'fs={server["vfs"]}')
    return data


@rc_command
def vfs__forget(server: dict, remote_path: str, is_file: bool = False) -> dict:
    data = {
        'server': server,
        'args': [f'file={remote_path}'] if is_file else [f'dir={remote_path}'],
    }
    if server['vfs']:
        data['args'].append(f'fs={server["vfs"]}')
    return data


def with_servers(function: callable) -> callable:
    @functools.wraps(function)
    def wrapper(target: str, *args: tuple, **kwds: dict) -> dict:
        if not kwds.get('server'):
            target_path = pathlib.Path(pathlib.Path(target).as_posix())
            for server in get_rc_servers():
                local_path = pathlib.Path(pathlib.Path(server['local']).as_posix())
                if target_path.is_relative_to(local_path):
                    kwds['server'] = server
                    return function(target, *args, **kwds)
            raise Exception(f'대상에 적합한 RC 서버를 찾을 수 없습니다: {target}')
        return function(target, *args, **kwds)
    return wrapper


@with_servers
def vfs_forget(target: str, server: dict = None) -> None:
    is_file = pathlib.Path(target).is_file()
    remote_path = update_path(target, {server['local']: server['remote']})
    P.logger.info(vfs__forget(server, remote_path, is_file))


@with_servers
def vfs_refresh(target: str, recursive: bool = False, async_: bool = False, server: dict = None) -> dict:
    remote_path = pathlib.Path(update_path(target, {server['local']: server['remote']}))
    for parent in remote_path.parents:
        if parent == parent.parent:
            result = vfs__refresh(server) or {}
        else:    
            result = vfs__refresh(server, parent.as_posix()) or {}
        P.logger.info(f'RC result: {result}')
        if ((result.get('result') or {}).get(parent.as_posix()) or '').lower() == 'ok':
            break
        if (result.get('result') or {}).get('error'):
            return result
    else:
        P.logger.warning(f'It has hit the root path: "{remote_path.as_posix()}"')
    if not pathlib.Path(target).is_file():
        result = vfs__refresh(server, remote_path.as_posix(), recursive, async_)
        P.logger.info(f'RC result: {result}')
    return result


def update_path(target: str, mappings: dict) -> str:
    target = pathlib.Path(target).as_posix()
    for k, v in mappings.items():
        target = target.replace(k, v)
    if not target:
        target = '/'
    return target


def parse_json_response(response: requests.Response) -> dict[str, Any]:
    try:
        result = response.json()
    except Exception as e:
        result = {
            'status_code': response.status_code,
            'content': response.text.strip(),
            'exception': f'{repr(e)}',
            'url': response.url,
        }
    return result


def request(method: str, url: str, data: Optional[dict] = None, timeout: Union[int, tuple, None] = None, **kwds: dict) -> requests.Response:
    try:
        if method.upper() == 'JSON':
            return requests.request('POST', url, json=data or {}, timeout=timeout, **kwds)
        else:
            return requests.request(method, url, data=data, timeout=timeout, **kwds)
    except:
        tb = traceback.format_exc()
        P.logger.error(tb)
        response = requests.Response()
        response._content = bytes(tb, 'utf-8')
        response.status_code = 0
        return response


def plex_api(func: callable) -> callable:
    @functools.wraps(func)
    def wrapper(*args: tuple, **kwds: dict) -> dict[str, Any]:
        params: dict = func(*args, **kwds)
        key = params.pop('key', '/identity')
        method = params.pop('method', 'GET')
        params['X-Plex-Token'] = P.ModelSetting.get('base_token')
        headers = {'Accept': 'application/json'}
        return parse_json_response(request(method, f'{P.ModelSetting.get("base_url")}{key}', params=params, headers=headers))
    return wrapper


@plex_api
def plex_refresh(section: int, path: Optional[str] = None, force: bool = False) -> dict[str, str]:
    params = {
        'key': f'/library/sections/{section}/refresh',
        'method': 'GET',
    }
    if force:
        params['force'] = 1
    if path:
        params['path'] = path
    return params


@plex_api
def plex_sections() -> dict[str, str]:
    return {
        'key': '/library/sections',
        'method': 'GET'
    }


@plex_api
def plex_delete_media(meta_id: int, media_id: int) -> dict[str, str]:
    return {
        'key': f'/library/metadata/{meta_id}/media/{media_id}',
        'method': 'DELETE',
    }


@plex_api
def plex_empty_trash(section_id: int) -> dict[str, str]:
    return {
        'key': f'/library/sections/{section_id}/emptyTrash',
        'method': 'PUT',
    }


@plex_api
def plex_activities() -> dict[str, str]:
    return {
        'key': '/activities',
        'method': 'GET',
    }


def plex_empty(section_id: int) -> None:
    counter = 0
    while plex_library_is_updating(section_id):
        time.sleep(10)
        if counter > 36:
            P.logger.error(f'라이브러리({section_id})를 스캔 중이라 휴지통 비우기를 취소합니다.')
            return
        counter += 1
    result = plex_empty_trash(section_id)
    P.logger.info(f'휴지통 비우기 명령을 요청했습니다: status_code={result.get("status_code")}')


def plex_library_is_updating(section_id: int) -> bool:
    container = plex_activities().get('MediaContainer')
    if container:
        for act in container.get('Activity', []):
            if act.get('type') == 'library.update.section':
                updating_section_id = int(act.get('Context', {}).get('librarySectionID'))
                if updating_section_id == section_id:
                    P.logger.debug(f"status=scanning section_id={updating_section_id} title='{act.get('title')}' progress={act.get('progress')}")
                    return True
    return False


def plex_section_by_path(path: str) -> int | None:
    plex_path = pathlib.Path(path)
    sections = plex_sections()
    for directory in sections['MediaContainer']['Directory']:
        for location in directory['Location']:
            if plex_path.is_relative_to(location['path']) or \
                pathlib.Path(location['path']).is_relative_to(plex_path):
                return int(directory['key'])


def plex_major_sections() -> dict:
    return {
        'movie': [{'id': item['id'], 'name': item['name']} for item in P.PlexDBHandle.library_sections(section_type=1)],
        'show': [{'id': item['id'], 'name': item['name']} for item in P.PlexDBHandle.library_sections(section_type=2)],
        'artist': [{'id': item['id'], 'name': item['name']} for item in P.PlexDBHandle.library_sections(section_type=8)],
    }


def plex_trashes(section_id: int, page_no: int = 1, limit: int = 10) -> dict:
        query = '''
        SELECT media_items.id, media_items.metadata_item_id, media_items.deleted_at, media_parts.file, media_parts.deleted_at
        FROM media_parts, media_items
        WHERE media_parts.deleted_at != ''
            AND media_items.library_section_id = ?
            AND media_items.id = media_parts.media_item_id
        ORDER BY media_parts.file
        LIMIT ? OFFSET ?
        '''
        offset = (page_no - 1) * limit
        return P.PlexDBHandle.select_arg(query, (section_id, limit, offset))


def plex_trash_list(section_id: int, page_no: int = 1, limit: int = 10) -> dict:
        result = {'total': 0, 'limit': limit, 'page': page_no, 'section_id': section_id, 'total_paths': 0, 'data': None}
        total_rows = plex_trashes(section_id, 1, -1)
        paths ={pathlib.Path(row['file']).parent.as_posix() for row in total_rows}
        result['total'] = len(total_rows)
        result['total_paths'] = len(paths)
        rows = plex_trashes(section_id, page_no, limit)
        if len(rows) > 0:
            for row in rows:
                row['deleted_at'] = get_readable_time(row['deleted_at'])
            result['data'] = rows
        return result


def plex_scan(path: str = None, scan_by_bin: bool = True, section_id: int = -1) -> None:
    if scan_by_bin:
        scan_item = P.get_module('scan').web_list_model(path)
        scan_item.save()
        P.logger.info(f'스캔 ID: {scan_item.id}')
    else:
        section_id = plex_section_by_path(path) if section_id < 0 else section_id
        if not section_id or section_id < 0:
            P.logger.error(f'섹션 ID를 찾을 수 없습니다: {path}')
        else:
            result = plex_refresh(section_id, path)
            if result.get('status_code') == 200:
                P.logger.info(f'스캔 요청: section_id={section_id} path={path}')
            else:
                P.logger.error(f'스캔 요청 실패: {result}')


def check_timeover(overs: list, item_range: str) -> None:
    '''
    FINISH_TIMEOVER 항목 점검
    ID가 item_range 범위 안에 있는 TIMEOVER 항목들을 다시 READY 로 변경
    주의: 계속 시간 초과로 뜨는 항목은 확인 후 수동으로 조치
    '''
    start_id, end_id = list(map(int, item_range.split('~')))
    for over in overs:
        if over.id in range(start_id, end_id + 1):
            P.logger.warning(f'READY 로 상태 변경: {over.id} {over.target}')
            over.filecheck_count = 0
            over.created_time = datetime.datetime.now()
            over.set_status('READY', save=True)


def check_scanning(scannings: list, max_scan_time: int) -> None:
    for scan in scannings:
        if int((datetime.datetime.now() - scan.process_start_time).total_seconds() / 60) >= max_scan_time:
            P.logger.warning(f'스캔 시간 {max_scan_time}분 초과: {scan.target}')
            P.logger.warning(f'스캔 QUEUE에서 제외: {scan.target}')
            scan.remove_in_queue(scan)
            scan.set_status('FINISH_TIMEOVER', save=True)


def get_readable_time(_time: float) -> str:
    return datetime.datetime.fromtimestamp(_time, datetime.timezone.utc).strftime('%b %d %H:%M')


def get_dir(target_path: str) -> list[dict[str, str]]:
    target_path = pathlib.Path(target_path)
    with os.scandir(target_path) as scandirs:
        target_list = []
        for entry in scandirs:
            try:
                target_list.append(pack_dir(entry))
            except Exception as e:
                P.logger.warning(e)
        target_list = sorted(target_list, key=lambda entry: (entry.get('is_file'), entry.get('name')))
        parent_pack = pack_dir(target_path.parent)
        parent_pack['name'] = '..'
        target_list.insert(0, parent_pack)
        return target_list


def pack_dir(entry: os.DirEntry | pathlib.Path) -> dict:
    stats: os.stat_result = entry.stat(follow_symlinks=True)
    return {
        'name': entry.name,
        'path': pathlib.Path(entry.path).as_posix() if isinstance(entry, os.DirEntry) else str(pathlib.Path(entry).as_posix()),
        'is_file': entry.is_file(),
        'size': format_file_size(stats.st_size),
        'ctime': get_readable_time(stats.st_ctime),
        'mtime': get_readable_time(stats.st_mtime),
    }


def format_file_size(size: int, decimals: int = 1, binary_system: bool = True) -> str:
    units = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']
    largest_unit = 'Y'
    if binary_system:
        step = 1024
    else:
        step = 1000
    for unit in units:
        if size < step:
            return f'{size:.{decimals}f}{unit}'
        size /= step
    return f'{size:.{decimals}f}{largest_unit}'


def default_route_socketio_page(page):
    module = page.parent
    page.socketio_list = page.socketio_list or []

    @F.socketio.on('connect', namespace=f'/{P.package_name}/{module.name}/{page.name}')
    @F.login_required
    def connect():
        P.logger.debug(f'socket_connect : {P.package_name}/{module.name}/{page.name}')
        page.socketio_list.append(flask.request.sid)
        socketio_callback('start', '')
        page.socketio_connect()

    @F.socketio.on('disconnect', namespace=f'/{P.package_name}/{module.name}/{page.name}')
    def disconnect():
        P.logger.debug(f'socket_disconnect : {P.package_name}/{module.name}/{page.name}')
        page.socketio_list.remove(flask.request.sid)
        page.socketio_disconnect()

    def socketio_callback(cmd, data, encoding=True):
        if page.socketio_list:
            if encoding:
                data = json.dumps(data, cls=AlchemyEncoder)
                data = json.loads(data)
            F.socketio.emit(cmd, data, namespace=f'/{P.package_name}/{module.name}/{page.name}')

    page.socketio_callback = socketio_callback


def celery_is_available() -> bool:
    try:
        return True if F.celery.control.inspect().stats() else False
    except:
        return False


@F.celery.task
def start_task(task: dict) -> tuple[bool, str]:
    '''
    task: dict
        command: str
        path: str
        recursive: bool
        async: bool
        scan_by_bin: bool
    '''
    try:
        match task['command']:
            case 'refresh_scan':
                targets = get_scan_targets(task['path'])
                for location, section_id in targets.items():
                    vfs_refresh(location, task['recursive'], task['async'])
                    plex_scan(location, section_id=section_id, scan_by_bin=task['scan_by_bin'])
            case 'refresh':
                vfs_refresh(task['path'], task['recursive'], task['async'])
            case 'scan':
                targets = get_scan_targets(task['path'])
                for location, section_id in targets.items():
                    plex_scan(location, section_id=section_id, scan_by_bin=task['scan_by_bin'])
            case 'forget':
                vfs_forget(task['path'])
        msg = f'작업이 끝났습니다: command={task["command"]} path={task["path"]}'
        P.logger.info(msg)
        return True, msg
    except Exception as e:
        P.logger.error(traceback.format_exc())
        return False, f'작업 도중에 오류가 발생했습니다: {repr(e)}'


@F.celery.task
def start_trash_task(task: dict) -> tuple[bool, str]:
    P.ModelSetting.set('scan_trash_task_status', 'running')
    try:
        refresh = True if 'refresh' in task.get('command') else False
        scan = True if 'scan' in task.get('command') else False
        empty = True if 'empty' in task.get('command') else False
        if task.get('path'):
            if refresh:
                vfs_refresh(task.get('path'))
            if scan:
                plex_scan(task.get('path'), scan_by_bin=False, section_id=task.get('section_id'))
        elif task.get('section_id'):
            trashes = plex_trashes(task.get('section_id'), 1, -1)
            if trashes:
                for path in {pathlib.Path(row['file']).parent.as_posix() for row in trashes}:
                    if P.ModelSetting.get('scan_trash_task_status') != 'running':
                        P.logger.info(f'작업을 중지합니다: {task}')
                        break
                    if refresh:
                        vfs_refresh(path)
                    if scan:
                        plex_scan(path, scan_by_bin=False, section_id=task.get('section_id'))
            else:
                P.ModelSetting.warning('이용 불가 파일이 없습니다.')
                empty = False
            if empty and P.ModelSetting.get('scan_trash_task_status') == 'running':
                plex_empty(task.get('section_id'))
        else:
            msg = f'작업 대상이 없습니다: {task}'
            P.loggger.error(msg)
            return False, msg
        msg = f'작업이 끝났습니다: task={task}'
        P.logger.info(msg)
        return True, msg
    except Exception as e:
        P.logger.error(traceback.format_exc())
        return False, f'작업 도중에 오류가 발생했습니다: {repr(e)}'
    finally:
        P.ModelSetting.set('scan_trash_task_status', 'ready')


class ThreadHasReturn(Thread):

    def __init__(self, group=None, target: callable = None, name: str = None, args: tuple | list = (),
                 kwargs: dict = {}, daemon: bool = None, callback: callable = None) -> None:
        Thread.__init__(self, group, target, name, args, kwargs, daemon=daemon)
        self._return = None
        self.callback = callback

    def run(self) -> None:
        if self._target:
            self._return = self._target(*self._args, **self._kwargs)
        if self.callback:
            self.callback(self.get_return())

    def join(self, *args) -> dict:
        Thread.join(self, *args)
        return self.get_return()

    def get_return(self) -> dict:
        return self._return


class Base:

    _DB_VERSIONS = ['1']

    def __init__(self, *args, **kwds) -> None:
        super().__init__(*args, **kwds)

    def set_recent_menu(self, req: flask.Request) -> None:
        current_menu = '|'.join(req.path[1:].split('/')[1:])
        if not current_menu == P.ModelSetting.get('recent_menu_plugin'):
            P.ModelSetting.set('recent_menu_plugin', current_menu)

    def get_template_args(self) -> dict:
        args = {
            'package_name': P.package_name,
            'module_name': self.name if isinstance(self, PluginModuleBase) else self.parent.name,
            'page_name': self.name if isinstance(self, PluginPageBase) else None,
        }
        for conf in self.db_default.keys():
            args[conf] = P.ModelSetting.get(conf)
        return args

    def prerender(self, sub: str, req: flask.Request) -> None:
        self.set_recent_menu(req)

    def run_async(self, func: callable, args: tuple = (), kwargs: dict = {}, **opts) -> None:
        if celery_is_available():
            P.logger.debug(f'Run by celery: {func.__name__}()')
            result = func.apply_async(args=args, kwargs=kwargs, **opts)
            Thread(target=result.get, kwargs={'on_message': self.socketio_emit_by_celery, 'propagate': False}, daemon=True).start()
        else:
            P.logger.debug(f'Run by Thread: {func.__name__}()')
            th = ThreadHasReturn(target=func, args=args, kwargs=kwargs, daemon=True, callback=self.socketio_emit)
            th.start()

    def callback_sio(self, data: dict) -> None:
        self.socketio_callback('result', {'status': data.get('status'), 'data': data.get('result')})

    def process_command(self, command: str, arg1: str, arg2: str, arg3: str, request: flask.Request) -> flask.Response:
        '''override'''
        try:
            data = getattr(self, f'command_{command}', self.command_default)(self.parse_command(request))
        except Exception as e:
            P.logger.error(traceback.format_exc())
            data = self.returns('warning', str(e))
        finally:
            return flask.jsonify(data)

    def parse_command(self, request: flask.Request) -> dict[str, Any]:
        query = urllib.parse.parse_qs(request.form.get('arg1'), keep_blank_values=True)
        return {
            'command': request.form.get('command'),
            'query': query,
        }

    def command_default(self, request: flask.Request) -> tuple[bool, str]:
        data = self.returns('danger', title='Flaskfarmaider')
        data['msg'] = '아직 구현되지 않았습니다.'
        return data

    def returns(self, success: str, msg: str = None, title: str = None, modal: str = None, json: dict = None, reload: bool = False, data: dict = None) -> dict:
        return {'ret': success, 'msg': msg, 'title': title, 'modal': modal, 'json': json, 'reload': reload, 'data': data}

    def _migration(self, version_key: str, table: str, migrate_func: callable) -> None:
        version = P.ModelSetting.get(version_key) or self._DB_VERSIONS[0]
        P.logger.debug(f'{table} 현재 DB 버전: {version}')
        with F.app.app_context():
            db_file = F.app.config['SQLALCHEMY_BINDS'][P.package_name].replace('sqlite:///', '').split('?')[0]
            try:
                with sqlite3.connect(db_file) as conn:
                    conn.row_factory = sqlite3.Row
                    cs = conn.cursor()
                    # DB 볼륨 정리
                    cs.execute('VACUUM;')
                    for ver in self._DB_VERSIONS[(self._DB_VERSIONS.index(version)):]:
                        migrate_func(ver, table, cs)
                        version = ver
                    F.db.session.flush()
                P.logger.debug(f'{table} 최종 DB 버전: {version}')
                P.ModelSetting.set(version_key, version)
            except:
                P.logger.error(traceback.format_exc())
                P.logger.error('마이그레이션 실패')

    def socketio_emit(self, result: tuple[bool, str]) -> None:
        raise Exception('이 메소드를 구현하세요.')

    def socketio_emit_by_celery(self, result: dict) -> None:
        raise Exception('이 메소드를 구현하세요.')


class ExtPageBase(Base, PluginPageBase):

    def __init__(self, plugin: PluginBase, parent: PluginModuleBase, name: str = None, scheduler_desc: str = None) -> None:
        super().__init__(plugin, parent, name, scheduler_desc)
        default_route_socketio_page(self)
        self.db_default = {}

    def process_menu(self, req: flask.Request) -> flask.Response:
        '''override'''
        self.prerender(self.name, req)
        try:
            return flask.render_template(f'{P.package_name}_{self.parent.name}_{self.name}.html', args=self.get_template_args())
        except:
            P.logger.error(traceback.format_exc())
            return flask.render_template('sample.html', title=f"process_menu() - {P.package_name}/{self.parent.name}/{self.name}")

    def socketio_connect(self) -> None:
        pass

    def socketio_disconnect(self) -> None:
        pass

    def socketio_emit(self, result: tuple[bool, str]) -> None:
        '''override'''
        # {P.package_name}/{module.name}/{page.name}
        F.socketio.emit('result', {'status': 'success' if result[0] else 'warning', 'result': result[1]}, namespace=f'/{P.package_name}/{self.parent.name}/{self.name}')

    def socketio_emit_by_celery(self, result: dict) -> None:
        '''override'''
        # celery status: SUCCESS, STARTED, REVOKED, RETRY, RECEIVED, PENDING, FAILURE
        #{'status': 'SUCCESS', 'result': (True, '작업을 완료했습니다.'), 'traceback': None, 'children': [(('cf6280f8-917e-4a21-b89e-cf890a4c991c', None), None)], 'date_done': '2024-08-13T08:42:04.600936', 'task_id': '492119df-94e7-4aae-9e4a-ab6b3e080b1c'}
        self.socketio_emit(result['result'])


class BrowserPage(ExtPageBase):

    def __init__(self, plugin: PluginBase, parent: PluginModuleBase) -> None:
        super().__init__(plugin, parent, name='browser')
        default_route_socketio_page(self)
        self.db_default = {
            'scan_browser_working_directory': '/',
        }

    def command_default(self, commands: dict[str, Any]) -> tuple[bool, str]:
        '''override'''
        if commands['command'] in ['refresh_scan', 'refresh', 'scan', 'forget']:
            task = {
                'command': commands['command'],
                'path': commands['query'].get('path')[0],
            }
            if 'refresh' in commands['command']:
                task['recursive'] = commands['query'].get('recursive')[0].lower() == 'true'
                task['async'] = commands['query'].get('async')[0].lower() == 'true'
            if 'scan' in commands['command']:
                task['scan_by_bin'] = commands['query'].get('scanByBin')[0].lower() == 'true'
            self.run_async(start_task, (task,))
            return self.returns('success', '실행했습니다.')
        else:
            data = self.returns('danger', title='Browser')
            data['msg'] = '아직 구현되지 않았습니다.'
            return data

    def command_list(self, commands: dict[str, Any]) -> dict:
        path = commands['query'].get('path', ['/'])[0]
        try:
            dir_list = json.dumps(get_dir(path))
        except Exception as e:
            P.logger.error(traceback.format_exc())
            return self.returns('warning', str(e))
        P.ModelSetting.set('scan_browser_working_directory', path)
        if dir_list:
            return self.returns('success', data=dir_list)
        else:
            return self.returns('warning', '폴더 목록을 생성할 수 없습니다.')


class TrashPage(ExtPageBase):

    def __init__(self, plugin: PluginBase, parent: PluginModuleBase) -> None:
        super().__init__(plugin, parent, name='trash')
        default_route_socketio_page(self)
        self.db_default = {
            'scan_trash_task_status': 'ready',
            'scan_trash_last_list_option': '',
        }

    def get_template_args(self) -> dict:
        '''override'''
        args = super().get_template_args()
        try:
            args['plex_sections'] = plex_major_sections()
        except:
            P.logger.error(traceback.format_exc())
            args['plex_sections'] = {}
        return args

    def check_status(func: callable) -> callable:
        @functools.wraps(func)
        def wrap(*args, **kwds) -> dict:
            status = P.ModelSetting.get('scan_trash_task_status')
            if status == 'ready':
                return func(*args, **kwds)
            else:
                return {'ret': 'warning', 'msg': '작업이 실행중입니다.'}
        return wrap

    @check_status
    def command_default(self, commands: dict[str, Any]) -> tuple[bool, str]:
        '''override'''
        if commands['command'] in ['refresh_scan', 'refresh', 'scan', 'empty', 'refresh_scan_empty']:
            task = {
                'command': commands['command'],
                'path': commands['query'].get('path', [None])[0],
                'section_id': int(commands['query'].get('section_id', [-1])[0]),
            }
            self.run_async(start_trash_task, (task,))
            return self.returns('success', '실행했습니다.')
        else:
            data = self.returns('danger', title='Trash')
            data['msg'] = '아직 구현되지 않았습니다.'
            return data

    def command_list(self, commands: dict[str, Any]) -> dict:
        section_type = commands['query'].get('section_type', ['movie'])[0]
        section_id = int(commands['query'].get('section_id', ['-1'])[0])
        page_no = int(commands['query'].get('page', ['1'])[0])
        limit = int(commands['query'].get('limit', ['30'])[0])
        P.ModelSetting.set('scan_trash_last_list_option', f'{section_type}|{section_id}|{page_no}')
        return self.returns('success', data=plex_trash_list(section_id, page_no, limit))

    @check_status
    def command_delete(self, commands: dict[str, Any]) -> dict:
        metadata_id = int(commands['query'].get('metadata_id', ['-1'])[0])
        mediaitem_id = int(commands['query'].get('mediaitem_id', ['-1'])[0])
        result = plex_delete_media(metadata_id, mediaitem_id)
        return self.returns('success', f'삭제를 요청했습니다: status_code={result.get("status_code")}')

    def command_stop(self, commands: dict[str, Any]) -> dict:
        status = P.ModelSetting.get('scan_trash_task_status')
        if status in ['running', 'stopping']:
            P.ModelSetting.set('scan_trash_task_status', 'stopping')
            return self.returns('success', '작업을 멈추는 중입니다.')
        else:
            return self.returns('warning', '실행중이 아닙니다.')

    def plugin_load(self) -> None:
        '''override'''
        super().plugin_load()
        P.ModelSetting.set('scan_trash_task_status', 'ready')

    def plugin_unload(self) -> None:
        '''override'''
        super().plugin_unload()
        P.ModelSetting.set('scan_trash_task_status', 'ready')
