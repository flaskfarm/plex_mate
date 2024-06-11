import sqlite3

from support import SupportFile, d

from .plex_db import PlexDBHandle, dict_factory
from .setup import *


class Task(object):
    @staticmethod
    @F.celery.task(bind=True)
    def start(self, location, meta_type, folder, dryrun, mode):
        dryrun = True if dryrun == 'true'  else False
        if location == 'Metadata':
            root_path = os.path.join(P.ModelSetting.get('base_path_metadata'), meta_type)
        elif location == 'Media':
            root_path = os.path.join(P.ModelSetting.get('base_path_media'), 'localhost')
       
        if folder == 'all':
            folders = sorted(os.listdir(root_path))
        else:
            folders = [folder]
        
        db_file = P.ModelSetting.get('base_path_db')
        con = sqlite3.connect(db_file)
        cur = con.cursor()

        status = {'is_working':'run', 'remove_count' : 0, 'remove_size':0, 'count':0, 'current':0}

        #print(folders)
        for folder in folders:
            folder_path = os.path.join(root_path, folder)
            #P.logger.error(folder_path)
            if os.path.exists(folder_path) == False:
                continue

            bundle_list = os.listdir(folder_path)
            status['count'] += len(bundle_list)
            for bundle in bundle_list:
                try:
                    if P.ModelSetting.get_bool('clear_bundle_task_stop_flag'):
                        return 'stop'
                    time.sleep(0.05)
                    status['current'] += 1
                    data = {'folder':folder, 'bundle':bundle, 'status':status}
                    bundle_path = os.path.join(folder_path, bundle)
                    hash_value = folder + bundle.split('.')[0]
                    if location == 'Metadata':
                        ce = con.execute('SELECT * FROM metadata_items WHERE hash = ?', (hash_value,))
                    else:
                        ce = con.execute('SELECT * FROM media_parts WHERE hash = ?', (hash_value,))
                    ce.row_factory = dict_factory
                    fetch = ce.fetchall()
                    if len(fetch) > 0:
                        if location == 'Metadata':
                            data['title'] = fetch[0]['title']
                            data['metadata_type'] = fetch[0]['metadata_type']
                            if mode in ['step2','step3'] and data['metadata_type'] in [3,4]:
                                tmp = SupportFile.size(start_path=bundle_path)
                                data['remove'] = tmp
                                status['remove_size'] += tmp
                                status['remove_count'] += 1
                                if dryrun == False:
                                    SupportFile.rmtree(bundle_path)
                            if mode == 'step3' and data['metadata_type'] in [1,2] and dryrun == False:
                                data = Task.meta_step2(bundle_path, data)
                            Task.remove_empty_folder(bundle_path)
                        else:
                            data['file'] = fetch[0]['file']
                            data = Task.media_step2(bundle_path, data)
                            Task.remove_empty_folder(bundle_path)
                    elif len(fetch) == 0:
                        tmp = SupportFile.size(start_path=bundle_path)
                        data['remove'] = tmp
                        status['remove_size'] += tmp
                        status['remove_count'] += 1
                        if dryrun == False:
                            SupportFile.rmtree(bundle_path)
                    
                    if F.config['use_celery']:
                        self.update_state(state='PROGRESS', meta=data)
                    else:
                        self.receive_from_task(data, celery=False)
                except Exception as e: 
                    logger.error(f'Exception:{str(e)}')
                    logger.error(traceback.format_exc())
        return 'wait'

    
    def meta_step2(bundle_path, data):
        data['remove'] = 0
        for base, folders, files in os.walk(bundle_path):
            for f in files:
                if f.endswith('.xml'):
                    continue
                filepath = os.path.join(base, f)
                if os.path.islink(filepath):
                    if os.path.exists(os.path.realpath(filepath)) == False:
                        P.logger.info("링크제거")
                        os.remove(filepath)
                        continue
                
                    tmp = f.split('.')[-1]
                    using = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE user_thumb_url LIKE '%{tmp}' OR user_art_url LIKE '%{tmp}';")
                    
                    if len(using) == 0:
                        if os.path.exists(filepath):
                            data['remove'] += os.path.getsize(filepath)
                            P.logger.debug(f"안쓰는 파일 삭제 : {filepath}")
                            os.remove(filepath)
                        else:
                            P.logger.error('.................. 파일 없음')
                    else:
                        P.logger.debug(f"파일 사용: {filepath}")
        return data


    def media_step2(bundle_path, data):
        data['remove'] = 0
        for base, folders, files in os.walk(bundle_path):
            for f in files:
                if f.endswith('.xml'):
                    continue
                filepath = os.path.join(base, f)
                if os.path.islink(filepath):
                    if os.path.exists(os.path.realpath(filepath)) == False:
                        P.logger.info("링크제거")
                        os.remove(filepath)
                        continue
                    
                    print(tmp) 
                    
                    tmp = f.split('.')[-1]
                    #using = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE user_thumb_url LIKE '%{tmp}' OR user_art_url LIKE '%{tmp}';")
                    using = 0
                    if len(using) == 0:
                        if os.path.exists(filepath):
                            data['remove'] += os.path.getsize(filepath)
                            P.logger.debug(f"안쓰는 파일 삭제 : {filepath}")
                            os.remove(filepath)
                        else:
                            P.logger.error('.................. 파일 없음')
                    else:
                        P.logger.debug(f"파일 사용: {filepath}")
        return data


    def remove_empty_folder(bundle_path):
        while True:
            count = 0
            for base, folders, files in os.walk(bundle_path):
                if not folders and not files:
                    os.removedirs(base)
                    P.logger.debug(f"빈 폴더 삭제: {base} ")
                    count += 1
            if count == 0:
                break
        