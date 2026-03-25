from flask import Request, Response

from .page_tool_query import PageToolQuery
from .page_tool_select import PageToolSelect
from .page_tool_simple import PageToolSimple
from .plex_db import PlexDBHandle
from .setup import *
from .task_base import plex_exclusive, stop_plex_exclusive

#########################################################

class ModuleTool(PluginModuleBase):
    db_default = None

    def __init__(self, P):
        super(ModuleTool, self).__init__(P, name='tool', first_menu='simple')
        self.set_page_list([PageToolSimple, PageToolSelect, PageToolQuery])
        

    def process_menu(self, page, req):
        arg = P.ModelSetting.to_dict()
        arg['library_list'] = PlexDBHandle.library_sections()
        if page == 'select':
            arg['library_list'].insert(0, {'id':0, 'name':'전체'})
        return render_template(f'{P.package_name}_{self.name}_{page}.html', arg=arg)
        

    def process_api(self, sub: str, req: Request) -> Response:
        '''override'''
        
        def str_to_bool(value):
            return value.lower() in ['true', 'yes', 'y']
        
        if sub == 'plex_exclusive':
            try:
                stop = req.args.get('stop', False, type=str_to_bool)
                if stop:
                    stop_plex_exclusive()
                    return "모든 작업을 중단합니다.", 200
                section_id = req.args.get('section_id', 0, type=int)
                metadata_id = req.args.get('metadata_id', 0, type=int)
                reset = req.args.get('reset', False, type=str_to_bool)
                manual = req.args.get('manual', False, type=str_to_bool)
                allowed_sections = []
                if not manual:
                    allowed_sections = [int(s) for s in re.split(r'\W', P.ModelSetting.get('scan_plex_exclusive_sections')) if s.isdigit()]
                plex_exclusive.delay(section_id=section_id, metadata_id=metadata_id, reset=reset, manual=manual, allowed_sections=allowed_sections)
                return "작업을 시작했습니다.", 200
            except Exception:
                logger.exception(f"path='{sub}'")
        return "Bad Request", 400
