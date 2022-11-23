from .page_clear_library import PageClearLibraryShow
from .page_clear_bundle import PageClearBundle
from .setup import *


class ModuleClear(PluginModuleBase):
    def __init__(self, P):
        super(ModuleClear, self).__init__(P, name='clear', first_menu='movie')
        self.set_page_list([PageClearLibraryShow, PageClearBundle])
