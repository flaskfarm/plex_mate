from .page_tool_query import PageToolQuery
from .page_tool_select import PageToolSelect
from .page_tool_simple import PageToolSimple
from .plex_db import PlexDBHandle
from .setup import *

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
        