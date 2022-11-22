from support import SupportFile

from .plex_bin_scanner import PlexBinaryScanner
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .setup import *


class PageToolSelect(PluginPageBase):
    preset = [
        ['템플릿 : 키워드 입력 필요', ''],
        ['제목 포함 검색', "(metadata_items.title LIKE '% __ %' AND metadata_type BETWEEN 1 and 4)"],
        ['제목 일치 검색', "(metadata_items.title = ' __ ' AND metadata_type BETWEEN 1 and 2)"],
        ['메타제공 사이트 일치 검색', "(metadata_items.guid LIKE '%sjva_agent://__%' AND metadata_type BETWEEN 1 and 2)"],
        ['메타제공 사이트 불일치 검색', "(metadata_items.guid NOT LIKE '%sjva_agent://__%' AND metadata_type BETWEEN 1 and 2)"],
        ['휴지통', "(metadata_items.deleted_at != '')"],
        ['-------------', ''],
        ['제목 정렬시 한글 초성이 아닌 것들', "(metadata_type in (1,2,8,9) AND substr(metadata_items.title_sort, 1, 1) >= '가' and substr(metadata_items.title_sort, 1, 1) <= '힣')"],
        ['메타 없는 것', 'metadata_items.guid LIKE "local://%"'],
        ['미분석', '(metadata_type BETWEEN 1 and 4 AND width is null)'],
        ['불일치 상태', "(metadata_type BETWEEN 1 and 4 AND guid LIKE 'com.plexapp.agents.none%')"],
        ['Poster가 없거나, http가 아닌 경우', "(metadata_type BETWEEN 1 and 4 AND (user_thumb_url == NULL OR user_thumb_url == '' OR user_thumb_url NOT LIKE 'http%'))"],
        ['Art가 없거나, http가 아닌 경우', "(metadata_type BETWEEN 1 and 4 AND (user_art_url == NULL OR user_art_url == '' OR user_art_url NOT LIKE 'http%'))"],
    ]

    def __init__(self, P, parent):
        super(PageToolSelect, self).__init__(P, parent, name='select')
        self.db_default = {
            f'{self.parent.name}_{self.name}_db_version' : '1',
            f'{self.parent.name}_{self.name}_query' : '',
        }
      

    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'select':
                P.ModelSetting.set(f'{self.parent.name}_{self.name}_query', arg1)
                ret['select'] = PlexDBHandle.tool_select(arg1)
            elif command == 'refresh_web':
                PlexWebHandle.refresh_by_id(arg1)
                ret['msg'] = '명령을 전송하였습니다.'
            elif command == 'scan_bin':
                PlexBinaryScanner.scan_refresh(arg1, os.path.dirname(arg2))
                ret['msg'] = '완료'
            elif command == 'refresh_bin':
                PlexBinaryScanner.meta_refresh_by_id(arg1)
                ret['msg'] = '완료'
            elif command == 'analyze_web':
                PlexWebHandle.analyze_by_id(arg1)
                ret['msg'] = '명령을 전송하였습니다.'
            elif command == 'analyze_bin':
                PlexBinaryScanner.analyze(arg1, metadata_item_id=arg2)
                ret['msg'] = '완료'
            elif command == 'remove_metadata':
                folder_path = os.path.join(
                    P.ModelSetting.get('base_path_metadata'),
                    'Movies' if arg1 == '1' else 'TV Shows',
                    arg2[0],
                    f"{arg2[1:]}.bundle"
                )
                if os.path.exists(folder_path):
                    if SupportFile.rmtree(folder_path):
                        ret['msg'] = '삭제하였습니다.'
                    else:
                        ret['ret'] = 'warning'
                        ret['msg'] = '삭제 실패'
                else:
                    ret['ret'] = 'warning'
                    ret['msg'] = f'{folder_path} 없음'
            elif command == 'get_preset':
                ret['preset'] = self.preset
            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})
  
