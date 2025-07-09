from .page_clear_library import PageClearLibraryShow, PageClearLibraryMovie, PageClearLibraryMusic
from .page_clear_bundle import PageClearBundle
from .page_clear_cache import PageClearCache
from .setup import *


class ModuleClear(PluginModuleBase):
    def __init__(self, P):
        super(ModuleClear, self).__init__(P, name='clear', first_menu='movie')
        self.set_page_list([PageClearLibraryShow, PageClearBundle, PageClearLibraryMovie, PageClearLibraryMusic, PageClearCache])

    def process_api(self, sub: str, req: 'flask.Request') -> 'flask.Response':
        ret = {'ret':'success'}
        request_args = dict(req.args)
        request_form = dict(req.form)
        match sub:
            case 'retrieve_category':
                section_id = request_args.get('section_id') or request_form.get('section_id') or '-1'
                try:
                    section_id = int(section_id)
                except (ValueError, TypeError):
                    section_id = -1
                self.get_module('base').task_interface('retrieve_category', section_id)
                ret['msg'] = f'요청했습니다: {section_id=}'
            case _:
                return {'ret':'fail', 'msg':'알 수 없는 요청입니다.'}, 400
        return jsonify(ret)
