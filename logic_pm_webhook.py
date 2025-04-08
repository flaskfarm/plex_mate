import subprocess
import json
import threading
import time
import signal
import urllib.parse
from datetime import datetime, timedelta

from flask import abort
from sqlalchemy import Column, Integer, String, DateTime

from .setup import *
from .plex_db import PlexDBHandle

logger = P.logger
package_name = P.package_name
name = 'webhook'

#########################################################

IGNORED_NO_INTRO_SHOWS = set()
webhook_instance = None

# from .logic_pm_webhook import webhook_instance
# @F.celery.task(name='plex_mate.logic_pm_webhook.webhook_handler')
# def celery_handle_webhook(data):
#     try:
#         with F.app.app_context():
#             if webhook_instance is not None:
#                 webhook_instance.handle_webhook_async(data)
#             else:
#                 logger.error("[CeleryWebhook] webhook_instance is None. 초기화 안됨.")
#     except Exception as e:
#         logger.exception(f"[CeleryWebhook] 처리 실패: {e}")


class LogicPMWebhook(PluginModuleBase):

    db_default = {
        'webhook_use_discord': 'False',  
        'webhook_discord_events': '', 
        'webhook_discord_url': '',     
        'webhook_use_full': 'False',
        'webhook_use_preview': 'False',
        'webhook_use_intro_marker': 'False',
        'webhook_intro_match_similar': 'False',
        'webhook_intro_auto_copy': 'False',
        'cache_library_sections_full': '',
        'cache_library_sections_preview': '',
        'intro_library_sections': '',
        'intro_copy_sections': '',
        'plex_server_uuid': '',
        'directory_mapping': '',
        'webhook_db_version': '1',
        'intro_json_file_path': '',
        'intro_sync_auto_start': 'False',
        'intro_sync_interval': '60',
        'basic_db_delete_day': '30',
        'basic_db_auto_delete': 'False',
        }


    def __init__(self, P):
        super(LogicPMWebhook, self).__init__(P, name='webhook', first_menu='setting')
        global webhook_instance
        webhook_instance = self
        self.name = 'webhook'
        self.cleanup_old_ignored_entries()
        self.sqlite_bin = P.ModelSetting.get('base_bin_sqlite')
        self.plex_db = P.ModelSetting.get('base_path_db')
        self.cache_process_map = {}
        self._register_webhook_route()
        self.web_list_model = ModelWebhookIntroHistory
        raw = P.ModelSetting.get('directory_mapping') or ''
        self.directory_mapping = {}
        for line in raw.strip().splitlines():
            if ':' in line:
                src, dst = line.split(':', 1)
                self.directory_mapping[src.strip()] = dst.strip()

    def _register_webhook_route(self):
        logic_self = self

        @F.app.route('/plex_mate/webhook/plex', methods=['POST'])
        def webhook_plex():
            if F.SystemModelSetting.get_bool('use_apikey'):
                apikey = request.args.to_dict().get('apikey')
                if apikey != F.SystemModelSetting.get('apikey'):
                    abort(403)
            try:
                data = request.form.get('payload')
                if data:
                    data = json.loads(data)
                    uuid_list = P.ModelSetting.get_list('plex_server_uuid')
                    uuid = data.get('Server', {}).get('uuid')
                    if uuid_list and uuid not in uuid_list:
                        return jsonify({'status': 'invalid'})

                    # if F.config.get('use_celery'):
                    #     celery_handle_webhook.delay(data)
                    # else:
                    threading.Thread(
                        target=logic_self.handle_webhook_async,
                        args=(data,), daemon=True).start()

                    return jsonify({'status': 'ok'})
            except Exception as e:
                logger.error(f"[Webhook] 처리 오류: {e}")
            return jsonify({'status': 'invalid'})


    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        arg['sub2'] = sub
        ddns = F.SystemModelSetting.get("ddns")
        use_apikey = F.SystemModelSetting.get_bool("use_apikey")
        apikey = F.SystemModelSetting.get("apikey")
        arg['api_webhook'] = urllib.parse.urljoin(ddns, f'/plex_mate/webhook/plex' + f'?apikey={apikey}' if use_apikey else '')
        try:
            return render_template(f'{package_name}_{self.name}_{sub}.html', arg=arg)
        except Exception as e:
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return render_template('sample.html', title=f"{package_name}/{self.name}/{sub}")


    # def process_normal(self, sub, req):
    #     logger.error(sub)
    #     logger.error(req)
    #     #data = json.loads(req.form['payload'])
    #     #data = req.form
    #     #logger.error(d(data))

    #     # "\"start\":\"{file}\""
    #     # "mode=start|server_name={server_name}|server_machine_id={server_machine_id}|user={user}|media_type={media_type}|title={title}|file={file}|section_id={section_id}|rating_key={rating_key}|progress_percent={progress_percent}"
    #     if sub == 'tautulli':
    #         text = req.get_json()
    #         logger.warning(d(text))
            
    #         data = {}
    #         for tmp in text.split('|'):
    #             tmp2 = tmp.split('=', 1)
    #             logger.info(tmp2)
    #             data[tmp2[0]] = tmp2[1]
            

    #         #data = json.loads("{" + params + "}")
    #         logger.error(d(data))

    #         #if data['mode'] == 'start':
    #         self.start(data)
    #     elif sub == 'plex':
    #         data = json.loads(req.form['payload'])
    #         data = req.form
    #         logger.error(d(data))



    #     return "OK"

   

    def process_ajax(self, sub, req):
        try:
            if sub == 'library_sections':
                return jsonify(self._get_library_sections_via_sqlite())

            elif sub == 'intro_history':
                order = req.args.get('order', 'desc')
                page = int(req.args.get('page', 1))
                section_id = req.args.get('section_id', '').strip()
                status = req.args.get('status', '').strip()
                per_page = 20
                offset = (page - 1) * per_page

                query = db.session.query(ModelWebhookIntroHistory)

                if section_id:
                    query = query.filter(ModelWebhookIntroHistory.section_id == int(section_id))
                if status:
                    query = query.filter(ModelWebhookIntroHistory.status == status)

                query = query.order_by(
                    ModelWebhookIntroHistory.id.desc() if order == 'desc' else ModelWebhookIntroHistory.id.asc()
                )

                total = query.count()
                items = query.offset(offset).limit(per_page).all()

                data = [x.as_dict() for x in items]
                return jsonify({
                    'ret': 'success',
                    'data': data,
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'total_page': (total + per_page - 1) // per_page
                })

            elif sub == 'manual':
                DEFINE_DEV = False
                if os.path.exists(os.path.join(os.path.dirname(__file__), 'logic_pm_intro.py')):
                    DEFINE_DEV = True
                try:
                    if DEFINE_DEV:
                        from .logic_pm_intro import LogicIntroSync, celery_intro_sync
                    else:
                        from support import SupportSC
                        LogicIntroSync = SupportSC.load_module_P(P, 'logic_pm_intro').LogicIntroSync
                        celery_intro_sync = SupportSC.load_module_P(P, 'logic_pm_intro').celery_intro_sync
                except Exception as e:
                    P.logger.error(f'Exception:{str(e)}')
                    P.logger.error(traceback.format_exc())
                from sqlalchemy import func
                dry_run = req.form.get('dryrun', 'false') == 'true'
                cutoff = datetime.now() - timedelta(hours=1)
                exists = db.session.query(db.session.query(ModelWebhookIntroHistory).filter(ModelWebhookIntroHistory.status == 'MANUAL', ModelWebhookIntroHistory.created_time >= cutoff).exists()).scalar()
                if exists:
                    return jsonify({'ret': 'fail', 'msg': '최근 1시간 내 이미 동기화가 실행되었습니다.'})
                if F.config['use_celery']:
                    celery_intro_sync.delay(manual=True, dry_run=dry_run)
                    msg = '인트로 마커 동기화 작업을 백그라운드에서 시작했습니다.'
                else:
                    TaskIntroSync({'manual': True, 'dry_run': dry_run}).process()
                    msg = '인트로 마커 일괄 동기화 작업을 완료했습니다.'

                new_history = ModelWebhookIntroHistory(section_id=None, file_path='', status='MANUAL')
                db.session.add(new_history)
                db.session.commit()

                return jsonify({'ret': 'success', 'msg': msg})


        except Exception as e:
            logger.error(f"[Webhook] process_ajax Exception: {e}")
            logger.error(traceback.format_exc())
        return jsonify({'ret': 'fail'})


    def cleanup_old_ignored_entries(self):
        try:
            threshold = datetime.now() - timedelta(days=90)
            with F.app.app_context():
                deleted_count = db.session.query(ModelWebhookIntroIgnore).filter(ModelWebhookIntroIgnore.created_time < threshold).delete()
                db.session.commit()
            logger.debug(f"[Webhook] 90일 이상 지난 무시 항목 {deleted_count}건 삭제 완료")
        except Exception as e:
            logger.warning(f"[Webhook] 무시 항목 삭제 중 오류: {e}")


    def _get_library_sections_via_sqlite(self):
        try:
            rows = PlexDBHandle.select("SELECT id, name FROM library_sections ORDER BY id")
            return {'ret': 'success', 'data': rows}
        except Exception as e:
            logger.error(f"[Webhook] 라이브러리 섹션 조회 실패: {e}")
            return {'ret': 'fail', 'msg': str(e)}
        
    def _add_intro_history(self, section_id, file_path, status, file_hash=None, file_size=None):
        try:
            with app.app_context():
                history = ModelWebhookIntroHistory(
                    section_id=section_id,
                    file_path=file_path,
                    status=status,
                    file_hash=file_hash,
                    file_size=file_size
                )
                db.session.add(history)
                db.session.commit()
        except Exception as e:
            logger.error(f"[IntroHistory] 기록 실패: {e}")

    def is_ignored_show(self, show_rating_key):
        if show_rating_key in IGNORED_NO_INTRO_SHOWS:
            return True
        with app.app_context():
            row = db.session.query(ModelWebhookIntroIgnore).filter_by(show_rating_key=show_rating_key).first()
            if row:
                IGNORED_NO_INTRO_SHOWS.add(show_rating_key)
                return True
        return False

    def mark_show_as_ignored(self, show_rating_key, reason='no_intro'):
        if show_rating_key in IGNORED_NO_INTRO_SHOWS:
            return
        IGNORED_NO_INTRO_SHOWS.add(show_rating_key)
        with app.app_context():
            ignore = ModelWebhookIntroIgnore(show_rating_key=show_rating_key, reason=reason)
            db.session.merge(ignore)
            db.session.commit()

    def get_recent_episode_ids_if_valid(self, show_id):
        try:
            cutoff = int((datetime.now() - timedelta(minutes=3)).timestamp())
            query = f"""
                SELECT epi."index", epi.id
                FROM metadata_items AS show
                JOIN metadata_items AS season ON season.parent_id = show.id AND season.metadata_type = 3
                JOIN metadata_items AS epi ON epi.parent_id = season.id AND epi.metadata_type = 4
                WHERE show.id = {show_id}
                AND epi.added_at >= {cutoff};
            """
            rows = PlexDBHandle.select(query)
            indexes = [r["index"] for r in rows if isinstance(r["index"], int)]
            if any(i in [1, 2, 3] for i in indexes):
                return []  # 무시
            return [r["id"] for r in rows if isinstance(r["id"], int)]
        except Exception as e:
            logger.error(f"[Intro] 최근 회차 에피소드 ID 조회 오류: {e}")
            return []


    def stop_cache_process(self, rating_key):
        proc = self.cache_process_map.get(rating_key)
        if proc:
            try:
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    logger.info(f"[Cache] 프로세스 종료: rating_key={rating_key}, PID={proc.pid}")
            except Exception as e:
                logger.error(f"[Cache] 프로세스 종료 실패: {e}")
            finally:
                self.cache_process_map.pop(rating_key, None)

    def cache_video(self, session_id, rating_key, viewOffset, cache_type="full"):
        try:
            CacheDBHandler.add(session_id, rating_key, cache_type)

            result = PlexDBHandle.select_arg(
                """
                SELECT mp.file
                FROM media_parts mp
                JOIN media_items mi ON mp.media_item_id = mi.id
                WHERE mi.metadata_item_id = ?
                LIMIT 1
                """,
                (rating_key,)
            )
            if not result:
                logger.warning(f"[Cache] 경로 확인 실패: rating_key={rating_key}")
                return

            media_path = result[0]['file']
            if self.directory_mapping:
                for path in self.directory_mapping:
                    if path in media_path:
                        media_path = media_path.replace(path, self.directory_mapping[path])

            offset_seconds = int(viewOffset) // 1000 if viewOffset else 0
            offset_time = time.strftime('%-H:%M:%S', time.gmtime(offset_seconds))

            command = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
            if cache_type == "full" and viewOffset:
                command += ['-ss', offset_time]
            elif cache_type == "preview":
                command += ['-t', str(300)]
            command += ['-i', media_path, '-c', 'copy', '-f', 'null', '/dev/null']

            proc = subprocess.Popen(command, preexec_fn=os.setsid, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.cache_process_map[rating_key] = proc

            logger.info(
                f"Started caching session: {session_id}\n"
                f"Cache type: {cache_type}\n"
                f"Rating key: {rating_key}\n"
                f"Start time offset: {offset_time}"
            )

            proc.wait()
            if proc.returncode == 0:
                CacheDBHandler.update_status(rating_key, cache_type, 'completed')
                logger.info(f"Download completed for rating_key {rating_key} as {cache_type}")
            else:
                logger.warning(f"Caching process did not complete successfully for rating_key {rating_key}")

        except Exception as e:
            logger.error(f"[Cache] 캐싱 처리 오류: {e}")

    def get_next_episode_id_from_db(self, current_episode_guid):
        try:
            base_guid = current_episode_guid.split('?')[0]
            agent_prefix = base_guid.split('://')[0] + '://'
            guid_parts = base_guid.split('://', 1)[1].split('/')
            show_code, season, current_episode = guid_parts[0], *map(int, guid_parts[1:3])
            next_episode_guid = f"{agent_prefix}{show_code}/{season}/{current_episode + 1}"

            row = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE guid LIKE '{next_episode_guid.split('?')[0]}%' LIMIT 1")
            if not row:
                next_season_guid = f"{agent_prefix}//{show_code}/{int(season) + 1}/1"
                row = PlexDBHandle.select(f"SELECT id FROM metadata_items WHERE guid LIKE '{next_season_guid}%' LIMIT 1")

            if row and 'id' in row[0] and str(row[0]['id']).isdigit():
                return int(row[0]['id'])
        except Exception as e:
            logger.error(f"[NextEpisode] Plex DB 접근 오류: {e}")
        return None

    def insert_intro_marker_if_possible(self, rating_key):
        try:
            intro_tag_id = P.ModelSetting.get('intro_tag_id')
            if not intro_tag_id:
                rows = PlexDBHandle.select("SELECT tag_id FROM taggings WHERE text = 'intro' LIMIT 1")
                if rows and rows[0]['tag_id']:
                    intro_tag_id = rows[0]['tag_id']
                    with app.app_context():
                        P.ModelSetting.set('intro_tag_id', str(intro_tag_id))
                        db.session.commit()
                else:
                    logger.warning('[Intro] intro_tag_id 자동 탐색 실패')
                    return
            else:
                intro_tag_id = int(intro_tag_id)

            row = PlexDBHandle.select_arg(
                """
                SELECT md.library_section_id, md.id, md.guid, md."index", mp.file, md.parent_id, mp.hash, mp.size
                FROM media_parts mp
                JOIN media_items mi ON mp.media_item_id = mi.id
                JOIN metadata_items md ON mi.metadata_item_id = md.id
                WHERE md.id = ?
                """,
                (rating_key,)
            )
            if not row:
                return

            section_id, metadata_id, guid, ep_index, file_path, season_id, file_hash, file_size = list(row[0].values())

            existing = PlexDBHandle.select(
                f"SELECT 1 FROM taggings WHERE metadata_item_id = {metadata_id} AND text = 'intro' LIMIT 1"
            )
            if existing:
                return

            current_group = re.search(r'-([^-\\/]+)\.(mkv|mp4)$', file_path, re.IGNORECASE)
            if not current_group:
                return
            current_group = current_group.group(1).lower()

            rows = PlexDBHandle.select_arg(
                """
                SELECT md.id, t.time_offset, t.end_time_offset, mp.file
                FROM metadata_items md
                JOIN taggings t ON md.id = t.metadata_item_id
                JOIN media_items mi ON md.id = mi.metadata_item_id
                JOIN media_parts mp ON mi.id = mp.media_item_id
                WHERE md.parent_id = ?
                  AND md.metadata_type = 4
                  AND md."index" < ?
                  AND t.text = 'intro'
                  AND t.tag_id = ?
                ORDER BY md."index" DESC;
                """,
                (season_id, ep_index, intro_tag_id)
            )

            for row in rows:
                src_id, time_offset, end_time_offset, src_file = list(row.values())
                src_group = re.search(r'-([^-\\/]+)\.(mkv|mp4)$', src_file, re.IGNORECASE)
                if src_group and src_group.group(1).lower() == current_group:
                    now = int(time.time())
                    query = f"""
                        INSERT INTO taggings (
                            metadata_item_id, tag_id, "index", text,
                            time_offset, end_time_offset, thumb_url, created_at, extra_data
                        ) VALUES (
                            {metadata_id}, {intro_tag_id}, 0, 'intro',
                            {time_offset}, {end_time_offset}, '', {now}, NULL
                        );
                    """
                    PlexDBHandle.execute_query(query)
                    self._add_intro_history(section_id=section_id, file_path=file_path, status='AUTO', file_hash=file_hash, file_size=file_size)
                    logger.info(f"[Intro] 마커 삽입 완료: {file_path}")
                    return

            self.mark_show_as_ignored(show_rating_key=rating_key, reason='no_intro')
            return

        except Exception as e:
            logger.error(f"[Intro] 마커 삽입 오류: {e}")

    def get_int_list(self, key):
        raw = P.ModelSetting.get(key) or ''
        items = []
        for line in raw.strip().splitlines():
            for part in line.split(','):
                part = part.strip()
                if part.isdigit():
                    items.append(int(part))
        return items

    def send_discord_notification(self, data):
        try:
            webhook_url = P.ModelSetting.get('webhook_discord_url')
            if not webhook_url:
                logger.warning("[Discord] 웹훅 URL이 비어 있습니다.")
                return
                
            plex_base_url = P.ModelSetting.get('base_url')
            plex_token = P.ModelSetting.get('base_token')

            event_type = data.get('event', 'Unknown')
            event_dict = {
                "play": "media.play",
                "pause": "media.pause",
                "resume": "media.resume",
                "started": "playback.started",
                "scrobble": "media.scrobble",
                "stop": "media.stop",
                "new": "library.new",
            }
            allowed_events = P.ModelSetting.get_list('webhook_discord_events')
            if allowed_events:
                allowed_plex_events = [event_dict.get(e.strip().lower()) for e in allowed_events if e.strip().lower() in event_dict]
            if not allowed_events or event_type in allowed_plex_events:
                metadata = data.get("Metadata", {})
                library_title = data.get('Metadata', {}).get('librarySectionTitle', 'No Title')
                grandparent_media_title = data.get('Metadata', {}).get('grandparentTitle', 'No Title')
                media_title = data.get('Metadata', {}).get('title', 'No Title')
                summary = data.get('Metadata', {}).get('summary', 'No Title')
                user = data.get("Account", {}).get("title", "Unknown")
                poster_path = data.get("Metadata", {}).get("thumb")
                poster_url = f"{plex_base_url}{poster_path}?X-Plex-Token={plex_token}" if poster_path else None

                title = " - ".join(filter(lambda x: x != "No Title", [grandparent_media_title, media_title]))
                transcode_info = data.get("TranscodeSession", {})
                if transcode_info:
                    video_decision = transcode_info.get("videoDecision", "Unknown")
                    audio_decision = transcode_info.get("audioDecision", "Unknown")
                    if video_decision == "directplay" and audio_decision == "directplay":
                        playback_type = "✅ 직접 재생 (Direct Play)"
                    elif video_decision == "copy" or audio_decision == "copy":
                        playback_type = "🔄 직접 스트리밍 (Direct Stream)"
                    else:
                        playback_type = "🔥 트랜스코딩 (Transcoding)"
                else:
                    playback_type = "✅ 직접 재생 (Direct Play)"


                event_info = {
                    "media.play": ("▶", "재생했습니다!", 3447003),
                    "media.pause": ("⏸", "일시정지했습니다.", 15844367),
                    "media.resume": ("▶", "다시 재생했습니다.", 15844367),
                    "playback.started": ("▶", "다시 재생했습니다.", 15844367),
                    "media.scrobble": ("✅", "끝까지 시청했습니다! 🎉", 15844367),
                    "media.stop": ("⏹", "중지했습니다.", 15158332),
                    "library.new": ("🆕", "추가되었습니다!", 15158332),
                }
                emoji, action, color = event_info.get(event_type, ("🔔", "알 수 없는 이벤트 감지", 16711680))
                title_display = f"{emoji} **{user}**님이 `{title}`"
                season = metadata.get("parentIndex")
                episode = metadata.get("index")
                season_episode = f"S{int(season):02}E{int(episode):02}" if season and episode else ""
                if season_episode:
                    title_display += f" - {season_episode}"
                title_display += f" {action}"
                embed_data = {
                    "title": title_display,
                    "color": color,
                    "fields": [
                        {"name": "라이브러리명", "value": library_title, "inline": True},
                        {"name": "제목", "value": title, "inline": False},
                        {"name": "재생 방식", "value": playback_type, "inline": False}, 
                    ],
                }
                if event_type == "library.new":
                    embed_data["fields"].append({"name": "요약", "value": summary, "inline": True})


                season = metadata.get("parentIndex")
                episode = metadata.get("index")
                

                if poster_url:
                    embed_data["thumbnail"] = {"url": poster_url}

                discord_message = {
                    "username": "Plex Webhook",
                    "avatar_url": "https://i.imgur.com/huTelcm.png",
                    "embeds": [embed_data]
                }

                response = requests.post(webhook_url, json=discord_message)
                if response.status_code != 204:
                    logger.warning(f"[Discord] 웹훅 전송 실패: {response.status_code} {response.text}")
        except Exception as e:
            logger.exception(f"[Discord] 알림 전송 실패: {e}")


    def handle_webhook_async(self, data):
        try:
            if P.ModelSetting.get_bool('webhook_use_discord'):
                self.send_discord_notification(data)
            rating_key = data.get('Metadata', {}).get('ratingKey')
            library_section_id = int(data.get('Metadata', {}).get('librarySectionID', 0))  
            library_type = data.get('Metadata', {}).get('librarySectionType')
            type = data.get('Metadata', {}).get('type')
            use_cache_full = P.ModelSetting.get_bool(f'{name}_use_full')
            use_cache_preview = P.ModelSetting.get_bool(f'{name}_use_preview')
            cache_library_sections_full = self.get_int_list('cache_library_sections_full')
            cache_library_sections_preview = self.get_int_list('cache_library_sections_preview')
            session_id = data.get('Player', {}).get('uuid')
            use_intro_auto_copy = P.ModelSetting.get_bool(f'{name}_intro_auto_copy')
            state = data.get('event', '').strip()
            intro_copy_sections = self.get_int_list('intro_copy_sections')
            if use_cache_full and (not cache_library_sections_full or library_section_id in cache_library_sections_full) and state in ['media.play', 'media.stop']:
                CacheDBHandler.cleanup_older_than()
                view_offset = data.get('Metadata', {}).get('viewOffset', 0)
                if session_id or rating_key :
                    if state == 'media.play':
                        result = CacheDBHandler.is_cached(rating_key, 'full')
                        if not result:
                            logger.info(f"Media playing detected for rating_key {rating_key}, caching full video")
                            self.cache_video(session_id, rating_key, view_offset, 'full')
                        elif result[0] != session_id:
                            CacheDBHandler.add(session_id, rating_key, 'full')

                    elif state == 'media.stop':
                        logger.info(f"Media stopped for session {session_id}")
                        CacheDBHandler.delete(session_id, rating_key, 'full')
                        if not CacheDBHandler.is_cached(rating_key, 'full'):
                            self.stop_cache_process(rating_key)
            elif use_cache_preview and (not cache_library_sections_preview or library_section_id in cache_library_sections_preview) and state in ['media.scrobble'] and library_type == 'show':

                if not CacheDBHandler.is_cached(rating_key, 'preview'):
                    guid = data.get('Metadata', {}).get('guid')
                    next_rating_key = self.get_next_episode_id_from_db(guid)
                    if next_rating_key:
                        self.cache_video(session_id, next_rating_key, 0, 'preview')

            elif use_intro_auto_copy and state == 'library.new' and (not intro_copy_sections or library_section_id in intro_copy_sections) :
                try:
                    if type == 'show':
                        if self.is_ignored_show(rating_key):
                            return
                        episode_ids = self.get_recent_episode_ids_if_valid(rating_key)
                        for eid in episode_ids:
                            self.insert_intro_marker_if_possible(eid)

                    elif type == 'episode':
                        ep_index = data.get('Metadata', {}).get('index', 0)
                        show_id = data.get('Metadata', {}).get('grandparentRatingKey')
                        if int(ep_index) <= 3:
                            return
                        if show_id and self.is_ignored_show(int(show_id)):
                            return
                        self.insert_intro_marker_if_possible(int(rating_key))
                except Exception as e:
                    logger.error(f"[Intro] 최근 추가된 에피소드 마커 삽입 중 오류: {e}")

        except Exception as e:
            logger.error(f"[Webhook] 처리 오류: {e}")


class ModelWebhookCacheTrack(ModelBase):
    __tablename__ = 'webhook_cache'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = Column(Integer, primary_key=True)
    session_id = Column(String)
    rating_key = Column(String)
    cache_type = Column(String)  # full or preview
    status = Column(String)      # caching, completed, stopped
    timestamp = Column(DateTime, default=datetime.now)

    def as_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'rating_key': self.rating_key,
            'cache_type': self.cache_type,
            'status': self.status,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        }

class ModelWebhookIntroHistory(ModelBase):
    __tablename__ = 'webhook_intro_history'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = Column(Integer, primary_key=True)
    created_time = Column(DateTime, default=datetime.now)
    section_id = Column(Integer)
    file_path = Column(String)
    status = Column(String)  
    file_hash = Column(String)  
    file_size = Column(Integer) 

    def as_dict(self):
        return {
            'id': self.id,
            'created_time': self.created_time.strftime('%Y-%m-%d %H:%M:%S') if self.created_time else '',
            'section_id': self.section_id,
            'file_path': self.file_path,
            'status': self.status,
            'file_hash': self.file_hash,
            'file_size': self.file_size
        }

ModelWebhookIntroHistory.P = P

class ModelWebhookIntroIgnore(ModelBase):
    __tablename__ = 'webhook_intro_ignore'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = Column(Integer, primary_key=True)
    created_time = Column(DateTime, default=datetime.now)
    show_rating_key = Column(Integer, unique=True, index=True)  
    reason = Column(String)  

class CacheDBHandler:
    @staticmethod
    def add(session_id, rating_key, cache_type):
        with app.app_context():
            try:
                new_entry = ModelWebhookCacheTrack(
                    session_id=session_id,
                    rating_key=rating_key,
                    cache_type=cache_type,
                    status='caching',
                    timestamp=datetime.now()
                )
                db.session.merge(new_entry)
                db.session.commit()
                logger.debug(f"[CacheTrack] 기록 추가됨: session_id={session_id}, rating_key={rating_key}, type={cache_type}")
            except Exception as e:
                logger.error(f"[CacheTrack] 기록 추가 실패: {e}")

    @staticmethod
    def update_status(rating_key, cache_type, status):
        with app.app_context():
            try:
                target = ModelWebhookCacheTrack.query.filter_by(rating_key=rating_key, cache_type=cache_type).first()
                if target:
                    target.status = status
                    target.timestamp = datetime.now()
                    db.session.commit()
                    logger.debug(f"[CacheTrack] 상태 업데이트: rating_key={rating_key}, type={cache_type}, status={status}")
            except Exception as e:
                logger.error(f"[CacheTrack] 상태 업데이트 실패: {e}")

    @staticmethod
    def delete(session_id, rating_key, cache_type):
        with app.app_context():
            try:
                target = ModelWebhookCacheTrack.query.filter_by(
                    session_id=session_id,
                    rating_key=rating_key,
                    cache_type=cache_type
                ).first()
                if target and target.status != 'completed':
                    db.session.delete(target)
                    db.session.commit()
            except Exception as e:
                logger.error(f"[CacheTrack] 삭제 오류: {e}")


    @staticmethod
    def is_cached(rating_key, cache_type):
        with app.app_context():
            try:
                result = ModelWebhookCacheTrack.query.filter_by(rating_key=rating_key, cache_type=cache_type).first()
                return result.session_id if result else None
            except Exception as e:
                logger.error(f"[CacheTrack] 캐시 확인 오류: {e}")
                return None

    @staticmethod
    def cleanup_older_than(hours=4):
        with app.app_context():
            try:
                threshold = datetime.now() - timedelta(hours=hours)
                deleted = ModelWebhookCacheTrack.query.filter(ModelWebhookCacheTrack.timestamp < threshold).delete()
                db.session.commit()
            except Exception as e:
                logger.error(f"[CacheTrack] 오래된 기록 삭제 실패: {e}")


#     #########################################################

#     def start(self, data):
#         def func():
#             #TaskMakeCache.start()
#             #return
#             if app.config['config']['use_celery']:
#                 logger.debug(TaskMakeCache.start)
#                 result = TaskMakeCache.start.apply_async(tuple(), data)
#                 ret = result.get()
#             else:
#                 ret = TaskMakeCache.start()
#             logger.error("Start thread end")
#         t = threading.Thread(target=func, args=())
#         t.daemon = True
#         t.start()

# class TaskMakeCache:
    
#     @staticmethod
#     @celery.task()
#     def start(*args, **kwargs):
#         logger.debug(args)
#         logger.debug(kwargs)

#         TaskMakeCache(kwargs).process()


#     def __init__(self, data):
#         self.data = data


#     def process(self):
#         if self.data['mode'] == 'start':
#             self.fileread_start()
    
#     def fileread_start(self):

#         t = threading.Thread(target=self.fileread, args=())
#         t.daemon = True
#         t.start()


#     def fileread(self):

#         logger.error(d(self.data))
        
#         original_size = os.stat(self.data['file']).st_size
#         logger.warning(f"오리지널 크기: {original_size}")
#         logger.warning(f"오리지널 크기: {original_size}")
#         action_flag = True
#         if platform.system() != 'Windows':
#             cache_filepath = self.data['file'].replace("/mnt/gds", "/mnt/cache/vfs/gds{2O0mA}")
#             logger.debug(cache_filepath)
#             cache_size = os.stat(cache_filepath).st_size
#             logger.warning(f"캐시 크기: {cache_size}")

#             #tmp = os.system(f'du {cache_filepath}')
#             from support.base import SupportProcess
#             tmp = SupportProcess.execute(['du', '-B', '1', cache_filepath])
#             logger.error (tmp)
#             cache_size = tmp.split(' ')[0]
#             match = re.match(r'^\d+', tmp)
#             cache_size = match.group(0)
#             logger.info(cache_size)

#             cache_size = int(cache_size)
            
#             diff = abs(original_size-cache_size)
#             if diff < 1024 * 1024 * 10: # 10메가
#                 logger.warning("캐시 완료")
#                 action_flag = False
            
#         if action_flag:
#             f = open(self.data['file'], 'rb')
#             count = 0
#             while True:
#                 buf = f.read(1024*1024)
#                 count += 1
#                 current = f.tell()
#                 logger.debug(f"count : {count} {current} {int(current/original_size*100)}")
#                 if len(buf) == 0:
#                     break
