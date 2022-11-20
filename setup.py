setting = {
    'filepath' : __file__,
    'use_db': True,
    'use_default_setting': True,
    'home_module': None,
    'menu': {
        'uri': __package__,
        'name': 'PLEX MATE',
        'list': [
            {
                'uri': 'base',
                'name': '설정',
                'list': [
                    {'uri': 'setting', 'name': '설정'},
                ]
            },
            {
                'uri': 'scan',
                'name': '스캔',
                'list': [
                    {'uri': 'setting', 'name': '설정'},
                    {'uri': 'list', 'name': '스캔 목록'},
                    {'uri': 'manual/files/스캔.md', 'name': '매뉴얼'},
                ]
            },
            
            {
                'uri': 'manual',
                'name': '매뉴얼',
                'list': [
                    {'uri':'README.md', 'name':'README.md'}
                ]
            },
            {
                'uri': 'log',
                'name': '로그',
            },
        ]
    },
    'setting_menu': None,
    'default_route': 'normal',
}


from plugin import *

P = create_plugin_instance(setting)

try:
    from .mod_base import ModuleBase
    from .mod_scan import ModuleScan
    

    P.set_module_list([ModuleBase, ModuleScan])
    from .model_scan import ModelScanItem
    P.ModelScanItem = ModelScanItem
except Exception as e:
    P.logger.error(f'Exception:{str(e)}')
    P.logger.error(traceback.format_exc())

logger = P.logger


"""
{
                'uri': 'clear',
                'name': '파일 정리',
                'list': [
                    {'uri': 'movie', 'name': '영화 정리'},
                    {'uri': 'show', 'name': 'TV 정리'},
                    {'uri': 'music', 'name': '음악 정리'},
                    {'uri': 'bundle', 'name': '번들 삭제'},
                    {'uri': 'cache', 'name': '캐시(PhotoTranscoder) 삭제'},
                ]
            },
            {
                'uri': 'tool',
                'name': 'DB 툴',
                'list': [
                    {'uri': 'simple', 'name': '간단 명령'},
                    {'uri': 'select', 'name': 'DB Select'},
                    {'uri': 'query', 'name': 'SQL Query'},
                ]
            },
            {
                'uri': 'periodic',
                'name': '라이브러리 주기적 스캔',
                'list': [
                    {'uri': 'task', 'name': '작업 관리'},
                    {'uri': 'list', 'name': '스캔 결과'},
                ]
            },
            {
                'uri': 'subtitle',
                'name': '자막 처리',
                'list': [
                    {'uri': 'setting', 'name': '설정'},
                    {'uri': 'task', 'name': '작업'},
                ]
            },
            {
                'uri': 'dbcopy',
                'name': '라이브러리 복사',
                'list': [
                    {'uri': 'make', 'name': '소스 DB 생성'},
                    {'uri': 'copy', 'name': '복사 설정'},
                    {'uri': 'status', 'name': '복사 상태'},
                ]
            },
"""