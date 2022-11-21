from .page_clear_library import PageClearLibraryShow
from .plex_db import PlexDBHandle
from .setup import *


class ModuleClear(PluginModuleBase):
    def __init__(self, P):
        super(ModuleClear, self).__init__(P, name='clear', first_menu='movie')
        self.set_page_list([PageClearLibraryShow])


    def process_menu2222(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        arg['sub2'] = sub
        try:
            if sub == 'movie':
                arg['library_list'] = PlexDBHandle.library_sections(section_type=1)
            elif sub == 'show':
                arg['library_list'] = PlexDBHandle.library_sections(section_type=2)
            elif sub == 'music':
                arg['library_list'] = PlexDBHandle.library_sections(section_type=8)
            elif sub == 'cache':
                arg['scheduler'] = P.scheduler.is_include(self.sub_list[sub].get_scheduler_name())
                arg['is_running'] = str(scheduler.is_running(self.sub_list[sub].get_scheduler_name()))
            return render_template(f'{package_name}_{name}_{sub}.html', arg=arg)
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            return render_template('sample.html', title=f"{package_name}/{name}/{sub}")

