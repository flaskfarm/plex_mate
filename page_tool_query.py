from .plex_db import PlexDBHandle
from .setup import *


class PageToolQuery(PluginPageBase):
    preset = [
        ['-', ""],
        ['시즌 제목 확인', "SELECT title, `index` FROM metadata_items WHERE parent_id = (SELECT id FROM metadata_items WHERE title = ' __ ' AND metadata_type = 2)"],
        ['시즌 제목 변경', "UPDATE metadata_items SET title = ' __ ' WHERE parent_id = (SELECT id FROM metadata_items WHERE title = ' __ ' and metadata_type = 2) AND `index` = __"],
        ['자막 없는 메타', '''SELECT title FROM metadata_items WHERE metadata_items.id not in (
	SELECT metadata_items.id
    FROM metadata_items, media_items, media_parts, media_streams
    WHERE metadata_items.id = media_items.metadata_item_id AND media_items.id = media_parts.media_item_id  AND media_parts.id = media_streams.media_part_id AND media_streams.stream_type_id = 3 AND (metadata_items.library_section_id = __ )
) AND metadata_items.library_section_id = __ AND metadata_type = 1 ORDER BY title'''],
    ]

    def __init__(self, P, parent):
        super(PageToolQuery, self).__init__(P, parent, name='query')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_query' : '',
        }

    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'execute':
                query = arg1
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_query', query)
                tmp = query.lower()
                if tmp.startswith('select'):
                    ret['mode'] = 'select'
                    ret['select'] = PlexDBHandle.select(query)
                    ret['msg'] = f"{len(ret['select'])}개의 데이터"
                elif tmp.startswith('update') or tmp.startswith('delete') or tmp.startswith('insert'):
                    ret['mode'] = 'not_select'
                    result = PlexDBHandle.execute_query(query)
                    if result != False:
                        ret['msg'] = f"실행했습니다."
                    else:
                        ret['ret'] = 'warning'
                        ret['msg'] = f"실패"
            elif command == 'get_preset':
                ret['preset'] = self.preset
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})
