import asyncio
import json
import os
import time
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, CommentEvent, RoomUserSeqEvent
from highlight_detector import HighlightDetector
from clip_manager import ClipManager
from clips_index import cleanup_posted_clips
from stream_recorder import StreamRecorder, extract_stream_url


MIN_VIEWERS = 200
MIN_VOLUME_DB = -22.0
MAX_CONCURRENT_RECORDINGS = 3
VERTICAL_9_16 = True


def load_streamers():
    if not os.path.exists("config.json"):
        return []
    with open("config.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("streamers", [])


def get_comment_author(event: CommentEvent) -> str:
    """Récupère le nom de l'auteur sans déclencher le bug ExtendedUser.from_user."""
    user_info = getattr(event, "user_info", None)
    if user_info is not None:
        for attr in ("nick_name", "nickname", "unique_id", "display_id", "user_id", "id"):
            val = getattr(user_info, attr, None)
            if val:
                return str(val)
    return "inconnu"


def extract_viewer_count(event: RoomUserSeqEvent) -> int | None:
    """Extrait le nombre total de spectateurs depuis RoomUserSeqEvent."""
    for attr in ("total_user", "viewer_count", "m_total_user"):
        val = getattr(event, attr, None)
        if isinstance(val, int) and val >= 0:
            return val
    return None


async def listen_live(
    username: str,
    detector: HighlightDetector,
    recorder: StreamRecorder,
    active_streams: set,
    reconnect_cooldowns: dict,
    viewer_counts: dict,
    min_viewers: int = MIN_VIEWERS,
    reconnect_delay: float = 25.0,
):
    client = TikTokLiveClient(unique_id=username)
    cached_stream_url: str | None = None

    async def ensure_recording():
        nonlocal cached_stream_url
        if recorder.is_recording(username):
            return True
        if cached_stream_url is None:
            cached_stream_url = await extract_stream_url(client)
        if cached_stream_url:
            started = recorder.start_recording(
                username=username,
                stream_url=cached_stream_url,
                viewer_counts=viewer_counts,
            )
            if started:
                print(f"[FLUX TROUVE] Capture vidéo démarrée pour @{username}.")
            return started
        return False

    @client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent):
        print(f"[CONNECTE] En direct sur @{username} - Analyse du chat active.")
        if not await ensure_recording():
            await asyncio.sleep(2)
            if not await ensure_recording() and cached_stream_url is None:
                print(f"[AVERTISSEMENT] URL de flux introuvable pour @{username} (chat uniquement).")

    @client.on(RoomUserSeqEvent)
    async def on_room_user_seq(event: RoomUserSeqEvent):
        count = extract_viewer_count(event)
        if count is not None:
            viewer_counts[username] = count
            if count >= min_viewers and not recorder.is_recording(username):
                await ensure_recording()

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        current_viewers = viewer_counts.get(username, 0)
        if current_viewers < min_viewers:
            return
        if not recorder.is_recording(username):
            await ensure_recording()
        if not recorder.is_recording(username):
            return
        author = get_comment_author(event)
        comment = getattr(event, "comment", "") or ""
        detector.process_message(username=username, author=author, comment=comment)

    @client.on(DisconnectEvent)
    async def on_disconnect(event: DisconnectEvent):
        print(f"[DECONNECTE] Le live de @{username} s'est termine.")

    try:
        await client.start()
    except Exception as e:
        print(f"[ERREUR LIVE] @{username}: {e}")
    finally:
        recorder.stop_recording(username)
        active_streams.discard(username)
        viewer_counts.pop(username, None)
        reconnect_cooldowns[username] = time.time() + reconnect_delay
        print(
            f"[LIBERE] @{username} en pause de reconnexion pendant {int(reconnect_delay)}s."
        )


async def main():
    streamers = load_streamers()
    if not streamers:
        print("Aucun streamer configure dans config.json")
        return

    viewer_counts = {}
    recorder = StreamRecorder(
        base_output_dir="output",
        segment_seconds=2,
        min_clip_seconds=80,
        max_clip_seconds=165,
        buffer_retention_seconds=240,
        min_volume_db=MIN_VOLUME_DB,
        max_concurrent_recordings=MAX_CONCURRENT_RECORDINGS,
        vertical_9_16=VERTICAL_9_16,
    )
    clip_manager = ClipManager(
        pre_seconds=95,
        post_seconds=30,
        recorder=recorder,
        viewer_counts=viewer_counts,
    )
    detector = HighlightDetector(
        window_seconds=10,
        message_spike_threshold=25,
        cooldown_seconds=120,
        on_highlight=clip_manager.handle_highlight,
    )
    active_streams = set()
    reconnect_cooldowns = {}
    tasks = {}
    reconnect_delay = 25.0

    print(
        f"Surveillance de {len(streamers)} comptes en cours "
        f"(max_captures={MAX_CONCURRENT_RECORDINGS}, min_viewers={MIN_VIEWERS}, "
        f"durée_clip=1m20..2m45, 9:16={VERTICAL_9_16}, min_volume_db={MIN_VOLUME_DB} dB)..."
    )

    try:
        while True:
            now = time.time()
            for streamer in streamers:
                if streamer in active_streams:
                    continue

                cooldown_until = reconnect_cooldowns.get(streamer, 0.0)
                if now < cooldown_until:
                    remaining = int(cooldown_until - now)
                    print(f"Pause reconnexion pour @{streamer} ({remaining}s restantes)...")
                    continue

                print(f"Verification de @{streamer}...")
                client = TikTokLiveClient(unique_id=streamer)
                try:
                    is_live = await client.is_live()
                    if is_live:
                        print(f"@{streamer} est en live ! Lancement de l'ecoute...")
                        active_streams.add(streamer)
                        tasks[streamer] = asyncio.create_task(
                            listen_live(
                                streamer,
                                detector,
                                recorder,
                                active_streams,
                                reconnect_cooldowns,
                                viewer_counts,
                                min_viewers=MIN_VIEWERS,
                                reconnect_delay=reconnect_delay,
                            )
                        )
                    else:
                        print(f"@{streamer} est hors ligne.")
                except Exception as e:
                    print(f"Impossible de verifier @{streamer} : {e}")

            await asyncio.sleep(30)
    finally:
        recorder.stop_all()
        deleted = cleanup_posted_clips()
        print(f"[FIN DE SESSION] {deleted} clip(s) marqué(s) 'posté' supprimé(s) du disque.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé par l'utilisateur.")