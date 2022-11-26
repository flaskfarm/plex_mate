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
                'uri': 'periodic',
                'name': '주기적 스캔',
                'list': [
                    {'uri': 'task', 'name': '작업 관리'},
                    {'uri': 'list', 'name': '스캔 결과'},
                    {'uri': 'manual/files/라이브러리 주기적 스캔.md', 'name': '매뉴얼'},
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
                'uri': 'clear',
                'name': '파일 정리',
                'list': [
                    {'uri': 'movie', 'name': '영화 정리'},
                    {'uri': 'show', 'name': 'TV 정리'},
                    {'uri': 'music', 'name': '음악 정리'},
                    {'uri': 'bundle', 'name': '번들 삭제'},
                    {'uri': 'cache', 'name': '캐시(PhotoTranscoder) 삭제'},
                    {'uri': 'manual/files/파일정리.md', 'name': '매뉴얼'},
                ]
            },
            {
                'uri': 'copy',
                'name': '라이브러리 복사',
                'list': [
                    {'uri': 'make', 'name': '소스 DB 생성'},
                    {'uri': 'copy', 'name': '복사 설정'},
                    {'uri': 'status', 'name': '복사 상태'},
                    {'uri': 'manual/files/라이브러리 복사.md', 'name': '매뉴얼'},
                ]
            },
            {
                'uri': 'subtitle',
                'name': '자막 처리',
                'list': [
                    {'uri': 'setting', 'name': '설정'},
                    {'uri': 'task', 'name': '작업'},
                    {'uri': 'manual/files/자막 정리.md', 'name': '매뉴얼'},
                ]
            },
            {
                'uri': 'manual',
                'name': '매뉴얼',
                'list': [
                    {'uri':'README.md', 'name':'README.md'},
                    {'uri':'files/tip.md', 'name':'Tip'},
                    {'uri':'files/config.md', 'name':'config 파일'},
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
    from .mod_clear import ModuleClear
    from .mod_copy import ModuleCopy
    from .mod_periodic import ModulePeriodic
    from .mod_scan import ModelScanItem, ModuleScan
    from .mod_subtitle import ModuleSubtitle
    from .mod_tool import ModuleTool

    P.set_module_list([ModuleBase, ModuleScan, ModulePeriodic, ModuleTool, ModuleClear, ModuleCopy, ModuleSubtitle])
    
    # 외부 호출
    from .plex_bin_scanner import PlexBinaryScanner
    from .plex_db import PlexDBHandle
    from .plex_web import PlexWebHandle
    P.PlexDBHandle = PlexDBHandle
    P.PlexWebHandle = PlexWebHandle
    P.PlexBinaryScanner = PlexBinaryScanner
    P.ModelScanItem = ModelScanItem
except Exception as e:
    P.logger.error(f'Exception:{str(e)}')
    P.logger.error(traceback.format_exc())

def load_config():
    from support import SupportYaml
    from tool import ToolUtil
    return SupportYaml.read_yaml(ToolUtil.make_path(P.ModelSetting.get('base_path_config')))
    
P.load_config = load_config

logger = P.logger
