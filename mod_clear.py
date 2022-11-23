from .page_clear_library import PageClearLibraryShow, PageClearLibraryMovie, PageClearLibraryMusic
from .page_clear_bundle import PageClearBundle
from .page_clear_cache import PageClearCache
from .setup import *


class ModuleClear(PluginModuleBase):
    def __init__(self, P):
        super(ModuleClear, self).__init__(P, name='clear', first_menu='movie')
        self.set_page_list([PageClearLibraryShow, PageClearBundle, PageClearLibraryMovie, PageClearLibraryMusic, PageClearCache])
