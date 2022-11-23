from .page_copy_copy import PageCopyCopy
from .page_copy_make import PageCopyMake
from .page_copy_status import PageCopyStatus
from .setup import *


class ModuleCopy(PluginModuleBase):
    def __init__(self, P):
        super(ModuleCopy, self).__init__(P, name='copy', first_menu='make')
        self.set_page_list([PageCopyMake, PageCopyCopy, PageCopyStatus])
        



