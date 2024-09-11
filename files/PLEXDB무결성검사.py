
import json
import os
import sys
import traceback

logger = None
########################################################################## 이 위 고정

import shutil
import time

from framework import F
from plex_mate.plex_bin_scanner import PlexBinaryScanner
from plex_mate.plex_db import PlexDBHandle
from plex_mate.plex_web import PlexWebHandle
from support import SupportSubprocess, d

DRYRUN = True

def start():
    # 앨범이 없는 아티스트
    query = f"""select * from (select parent_id as parent_id1, title from metadata_items where metadata_type = 9 group by parent_id) as A left OUTER join metadata_items as B
on A.parent_id1 = B.id
where B.id is null;"""
    rows = PlexDBHandle.select(query)
    log(f"- 앨범이 없는 아티스트: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 앨범이 없는 아티스트: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE parent_id = {row['parent_id']};"""
        break
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    # 트랙이 없는 앨범
    query = f"""select metadata_items.id as artist_id, metadata_items.title as artist, A.id as album_id, A.title as album from (select * from metadata_items where metadata_type = 9 and id not in (select parent_id from metadata_items where metadata_type = 10 group by parent_id)) as A left outer join metadata_items
on A.parent_id = metadata_items.id;"""
    rows = PlexDBHandle.select(query)
    log(f"- 트랙이 없는 앨범:  {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 트랙이 없는 앨범: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE id = {row['album_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
        
    # 에피없는 시즌
    query = f"""select metadata_items.id as artist_id, metadata_items.title as artist, A.id as album_id, A.title as album from (select * from metadata_items where metadata_type = 3 and id not in (select parent_id from metadata_items where metadata_type = 4 group by parent_id)) as A left outer join metadata_items
on A.parent_id = metadata_items.id;"""
    rows = PlexDBHandle.select(query)
    log(f"- 에피없는 시즌:  {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 에피없는 시즌: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE id = {row['album_id']};"""

    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    
    # 시즌 없는 쇼
    query = f"""select * from (select parent_id as parent_id1, title from metadata_items where metadata_type = 3 group by parent_id) as A left OUTER join metadata_items as B
on A.parent_id1 = B.id
where B.id is null;"""
    rows = PlexDBHandle.select(query)
    log(f"- 시즌 없는 쇼: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 시즌 없는 쇼: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE parent_id = {row['parent_id1']};"""
        
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    # 앨범이 없는 트랙
    query = "select A.id as id2, A.title as title2, A.parent_id, A.metadata_type, B.id, B.title from metadata_items as A left outer join metadata_items as B on A.parent_id = B.id where A.metadata_type = 10 and B.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 앨범이 없는 트랙: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 앨범이 없는 트랙: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE id = {row['id2']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)

    # 시즌 없는 에피
    query = "select A.id as id2, A.title as title2, A.parent_id, A.metadata_type, B.id, B.title from metadata_items as A left outer join metadata_items as B on A.parent_id = B.id where A.metadata_type = 4 and B.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 시즌 없는 에피:  {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 시즌 없는 에피: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM metadata_items WHERE id = {row['id2']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    
    # 메타없는 미디어 아이템
    query = "select media_items.id as media_id, metadata_items.id from media_items left outer join metadata_items on media_items.metadata_item_id = metadata_items.id where metadata_items.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 메타없는 미디어 아이템: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 메타없는 미디어 아이템: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM media_items WHERE id = {row['media_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    
    # 미디어 아이템 없는 미디어 파트
    query = "select media_parts.id as part_id from media_parts left outer join media_items on media_parts.media_item_id = media_items.id where media_items.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 미디어 아이템 없는 미디어 파트: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 미디어 아이템 없는 미디어 파트: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM media_parts WHERE id = {row['part_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    

    # 미디어 아이템 없는 미디어 스트림
    query = "select media_streams.id as target_id from media_streams left outer join media_items on media_streams.media_item_id = media_items.id where media_items.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 미디어 아이템 없는 미디어 스트림: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 미디어 아이템 없는 미디어 스트림: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM media_streams WHERE id = {row['target_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    
    
    # 미디어 파트 없는 미디어 스트림
    query = "select media_streams.id as target_id from media_streams left outer join media_parts on media_streams.media_part_id = media_parts.id where media_parts.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 미디어 파트 없는 미디어 스트림: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 미디어 파트 없는 미디어 스트림: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM media_streams WHERE id = {row['target_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)
    

    # 미디어 파트가 없는 미디어 아이템
    query = "select media_items.id as target_id from media_items  left outer join media_parts on media_parts.media_item_id = media_items.id where media_parts.id is null"
    rows = PlexDBHandle.select(query)
    log(f"- 미디어 파트가 없는 미디어 아이템: {len(rows)}")
    query = ''
    for idx, row in enumerate(rows):
        log(f"- 미디어 파트가 없는 미디어 아이템: {idx+1}/{len(rows)}")
        log(d(row))
        query += f"""DELETE FROM media_items WHERE id = {row['target_id']};"""
    if not DRYRUN:
        PlexDBHandle.execute_query(query)



def 음악분석():
    라이브러리번호 = 1
    COUNT = 30
    query = f"""select * from metadata_items as A left outer join (
	select metadata_items.id as meta_id from metadata_items, media_items, media_parts, media_streams 
	where metadata_type = 10 and metadata_items.id = media_items.metadata_item_id and media_parts.media_item_id = media_items.id and media_parts.id = media_streams.media_part_id and (media_streams.codec = 'flac' or media_streams.codec = 'mp3' or media_streams.codec = 'aac')
) as B
on A.id = B.meta_id
where A.metadata_type = 10 and B.meta_id is null"""
    rows = PlexDBHandle.select(query)
    for idx, row in enumerate(rows):
        logger.warning(f"{idx}/{len(rows)} {row}")
        while True:
            if len(SupportSubprocess.get_list()) < COUNT:
                break
            time.sleep(1)
        PlexBinaryScanner.analyze(라이브러리번호, metadata_item_id=str(row['id']), join=False)
        time.sleep(1)


# 진입점
def run(*args, **kwargs):
    start()
    


########################################################################## 이 아래 고정
def main(*args, **kwargs):
    global logger
    if 'logger' in kwargs:
        logger = kwargs['logger']
    log('=========== SCRIPT START ===========')
    ret = run(*args, **kwargs)
    log('=========== SCRIPT END ===========')
    return ret

def log(*args):
    try:
        if logger is not None:
            logger.info(*args)
        if len(args) > 1:
            print(args[0] % tuple([str(x) for x in args[1:]]))
        else:
            print(str(args[0]))
        sys.stdout.flush()
    except Exception as e:
        print('Exception:%s', e)
        print(traceback.format_exc())


def d(data):
    if type(data) in [type({}), type([])]:
        import json
        return '\n' + json.dumps(data, indent=4, ensure_ascii=False)
    else:
        return str(data)


if __name__== "__main__":
    main()

