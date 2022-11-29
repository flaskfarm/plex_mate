from .plex_db import PlexDBHandle
from .setup import *


class PageCopyCopy(PluginPageBase):
    
    def __init__(self, P, parent):
        super(PageCopyCopy, self).__init__(P, parent, name='copy')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_path_source_db' : '',
            f'{self.parent.name}_{self.name}_source_section_id' : '',
            f'{self.parent.name}_{self.name}_path_source_root_path' : '',
            f'{self.parent.name}_{self.name}_path_target_root_path' : '',
            f'{self.parent.name}_{self.name}_target_section_id' : '',
            f'{self.parent.name}_{self.name}_target_section_location_id' : '',
            f'{self.parent.name}_{self.name}_dir_updated_mode' : '0',
            f'{self.parent.name}_{self.name}_task_stop_flag' : 'False',
        }
        self.data = {
            'list' : [],
            'status' : {'is_working':'wait'}
        }
        default_route_socketio_page(self)


    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'source_section':
                data = PlexDBHandle.library_sections(db_file=arg1)
                ret['json'] = data
                ret['title'] = '소스 섹션'
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_path_source_db', arg1)
            elif command == 'target_section_id':
                data = PlexDBHandle.library_sections()
                ret['json'] = data
                ret['title'] = 'Plex Section'
            elif command == 'target_section_location_id':
                data = PlexDBHandle.select_arg('SELECT * FROM section_locations WHERE library_section_id = ?', (arg1,))
                ret['json'] = data
                ret['title'] = 'Plex Section Location'
            elif command == 'select_source_locations':
                data = PlexDBHandle.select('SELECT * FROM section_locations', db_file=arg1)
                ret['json'] = data
                ret['title'] = '소스 Section Locations'
            elif command == 'select_target_locations':
                data = PlexDBHandle.select('SELECT * FROM section_locations')
                ret['json'] = data
                ret['title'] = '타겟 Section Locations'
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})
