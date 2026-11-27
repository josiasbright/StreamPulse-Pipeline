import asyncio
import glob
import os
import re
import subprocess
import time
from clips_index import get_next_clip_number, load_clips_index, record_clip_created


MIN_CLIP_SECONDS = 80       # 1 min 20
MAX_CLIP_SECONDS = 165      # 2 min 45
DEFAULT_PRE_SECONDS = 95    # 1 min 35 avant le pic
DEFAULT_POST_SECONDS = 30   # 30s après le pic -> 125s (2 min 05) par défaut
DEFAULT_MIN_VOLUME_DB = -22.0


def _find_stream_url_recursive(obj, depth: int = 0, seen: set | None = None) -> str | None:
    """Recherche récursivement une URL de flux vidéo (.flv / .m3u8 ou pull)."""
    if depth > 8 or obj is None:
        return None

    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return None

    if isinstance(obj, str):
        lower = obj.lower()
        if lower.startswith("http") and (
            ".flv" in lower
            or ".m3u8" in lower
            or "pull_url" in lower
            or "flv_pull" in lower
            or "hls_pull" in lower
            or "/live/" in lower
        ):
            return obj
        return None

    if not isinstance(obj, (int, float, bool)):
        seen.add(obj_id)

    if isinstance(obj, dict):
        priority_keys = []
        other_keys = []
        for k, v in obj.items():
            k_str = str(k).lower()
            if (
                "flv" in k_str
                or "hls" in k_str
                or "m3u8" in k_str
                or "pull" in k_str
                or "stream" in k_str
            ):
                priority_keys.append((k, v))
            else:
                other_keys.append((k, v))

        for _, v in priority_keys + other_keys:
            found = _find_stream_url_recursive(v, depth + 1, seen)
            if found:
                return found
        return None

    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            found = _find_stream_url_recursive(item, depth + 1, seen)
            if found:
                return found
        return None

    if hasattr(obj, "__dict__"):
        return _find_stream_url_recursive(vars(obj), depth + 1, seen)

    return None


async def extract_stream_url(client) -> str | None:
    """Récupère l'URL du flux vidéo via room_info ou client.web.fetch_room_info()."""
    candidates = [
        getattr(client, "room_info", None),
        getattr(client, "_room_info", None),
    ]

    if hasattr(client, "web") and hasattr(client.web, "fetch_room_info"):
        try:
            fetched = await client.web.fetch_room_info()
            candidates.insert(0, fetched)
        except Exception:
            pass

    for candidate in candidates:
        if candidate is not None:
            found = _find_stream_url_recursive(candidate)
            if found:
                return found

    return None


def get_audio_loudness_db(segment_paths: list[str]) -> float | None:
    """Mesure le volume moyen (mean_volume en dBFS) sur un échantillon de segments .ts récents."""
    if not segment_paths:
        return None

    sample = [p for p in segment_paths[-5:] if os.path.exists(p)]
    if not sample:
        return None

    target = sample[-1]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i", os.path.abspath(target),
        "-af", "volumedetect",
        "-vn",
        "-f", "null",
        "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = res.stderr or ""
        match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None


class StreamRecorder:
    def __init__(
        self,
        base_output_dir: str = "output",
        segment_seconds: int = 2,
        min_clip_seconds: int = MIN_CLIP_SECONDS,
        max_clip_seconds: int = MAX_CLIP_SECONDS,
        buffer_retention_seconds: int = 240,
        min_volume_db: float | None = DEFAULT_MIN_VOLUME_DB,
        max_concurrent_recordings: int = 3,
        vertical_9_16: bool = True,
    ):
        self.base_output_dir = base_output_dir
        self.segment_seconds = segment_seconds
        self.min_clip_seconds = min_clip_seconds
        self.max_clip_seconds = max_clip_seconds
        self.buffer_retention_seconds = buffer_retention_seconds
        self.min_volume_db = min_volume_db
        self.max_concurrent_recordings = max_concurrent_recordings
        self.vertical_9_16 = vertical_9_16
        self.processes: dict[str, subprocess.Popen] = {}
        self.stream_urls: dict[str, str] = {}

    def _buffer_dir(self, username: str) -> str:
        return os.path.join(self.base_output_dir, "buffers", username)

    def _clips_dir(self, username: str) -> str:
        safe_user = username.strip().lstrip("@")
        return os.path.join(self.base_output_dir, "clips", safe_user)

    def active_recording_usernames(self) -> list[str]:
        """Retourne la liste des streamers dont le processus FFmpeg est actuellement actif."""
        active = []
        for user, proc in list(self.processes.items()):
            if proc.poll() is None:
                active.append(user)
            else:
                self.processes.pop(user, None)
        return active

    def is_recording(self, username: str) -> bool:
        proc = self.processes.get(username)
        return proc is not None and proc.poll() is None

    def cleanup_old_segments(self, username: str, max_age_seconds: int | None = None):
        """Supprime les segments .ts plus anciens que max_age_seconds pour libérer le disque."""
        buf_dir = self._buffer_dir(username)
        if not os.path.exists(buf_dir):
            return

        retention = max_age_seconds if max_age_seconds is not None else self.buffer_retention_seconds
        cutoff = time.time() - retention
        pattern = os.path.join(buf_dir, "seg_*.ts")

        for path in glob.glob(pattern):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue

    def start_recording(
        self,
        username: str,
        stream_url: str,
        viewer_counts: dict[str, int] | None = None,
    ) -> bool:
        """Lance FFmpeg en respectant la limite max_concurrent_recordings (priorité aux plus gros viewers)."""
        if self.is_recording(username):
            return True

        active = self.active_recording_usernames()
        if len(active) >= self.max_concurrent_recordings:
            if not viewer_counts:
                return False

            candidate_viewers = viewer_counts.get(username, 0)
            lowest_user = min(active, key=lambda u: viewer_counts.get(u, 0))
            lowest_viewers = viewer_counts.get(lowest_user, 0)

            if candidate_viewers > lowest_viewers + 50:
                print(
                    f"[PRIORITE VIEWERS] Remplacement de @{lowest_user} ({lowest_viewers} viewers) "
                    f"par @{username} ({candidate_viewers} viewers)."
                )
                self.stop_recording(lowest_user)
            else:
                return False

        buf_dir = self._buffer_dir(username)
        os.makedirs(buf_dir, exist_ok=True)
        self.stream_urls[username] = stream_url

        out_pattern = os.path.join(buf_dir, "seg_%Y%m%d_%H%M%S.ts")

        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-user_agent", "Mozilla/5.0",
            "-i", stream_url,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.segment_seconds),
            "-strftime", "1",
            "-reset_timestamps", "1",
            out_pattern,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self.processes[username] = proc
            active_now = len(self.active_recording_usernames())
            print(
                f"[ENREGISTREMENT] Capture démarrée pour @{username} "
                f"({active_now}/{self.max_concurrent_recordings} slots actifs, segments {self.segment_seconds}s)."
            )
            return True
        except Exception as e:
            print(f"[ERREUR FFMPEG] Impossible de démarrer l'enregistrement de @{username}: {e}")
            return False

    def stop_recording(self, username: str):
        """Arrête proprement le processus FFmpeg d'un streamer et nettoie ses vieux segments."""
        proc = self.processes.pop(username, None)
        if proc:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if proc.stderr:
                err_output = proc.stderr.read().decode("utf-8", errors="replace").strip()
                if err_output:
                    print(f"[FFMPEG STDERR @{username}] {err_output}")
            print(f"[ENREGISTREMENT] Capture arrêtée pour @{username}.")

        self.cleanup_old_segments(username, max_age_seconds=0)

    def stop_all(self):
        """Arrête tous les processus FFmpeg actifs en fin de session."""
        for user in list(self.processes.keys()):
            self.stop_recording(user)

    def _select_bounded_segments(
        self,
        buf_dir: str,
        center_epoch: float,
        pre_seconds: int,
        post_seconds: int,
    ) -> list[str]:
        """Sélectionne les segments en garantissant une durée comprise entre 1m20 (80s) et 2m45 (165s)."""
        now = time.time()
        pattern = os.path.join(buf_dir, "seg_*.ts")
        all_files = sorted(glob.glob(pattern))

        stable_files = []
        for path in all_files:
            if not os.path.exists(path):
                continue
            try:
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if size >= 1024 and (now - mtime) >= 0.5:
                stable_files.append((path, mtime))

        if not stable_files:
            return []

        min_segs = max(1, self.min_clip_seconds // self.segment_seconds)
        max_segs = max(min_segs, self.max_clip_seconds // self.segment_seconds)

        start_t = center_epoch - pre_seconds
        end_t = center_epoch + post_seconds + 1.0

        selected = [p for p, mtime in stable_files if start_t <= mtime <= end_t]

        if not selected:
            selected = [p for p, _ in stable_files[-min_segs:]]

        if len(selected) < min_segs and len(stable_files) > len(selected):
            stable_paths = [p for p, _ in stable_files]
            last_path = selected[-1]
            last_idx = stable_paths.index(last_path)
            start_idx = max(0, last_idx - min_segs + 1)
            selected = stable_paths[start_idx : last_idx + 1]

        if len(selected) > max_segs:
            selected = selected[-max_segs:]

        return selected

    def _build_ffmpeg_clip_cmd(self, concat_list_path: str, clip_path: str) -> list[str]:
        """Construit la commande FFmpeg : vertical 1080x1920 avec fond flouté ou copie directe."""
        base = [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", os.path.abspath(concat_list_path),
        ]

        if self.vertical_9_16:
            vf_graph = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=20:10[bg];"
                "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[vout]"
            )
            return base + [
                "-filter_complex", vf_graph,
                "-map", "[vout]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "48000",
                "-ac", "2",
                "-movflags", "+faststart",
                os.path.abspath(clip_path),
            ]

        return base + [
            "-c", "copy",
            os.path.abspath(clip_path),
        ]

    def create_clip_from_buffer(
        self,
        username: str,
        center_epoch: float,
        pre_seconds: int = DEFAULT_PRE_SECONDS,
        post_seconds: int = DEFAULT_POST_SECONDS,
        reason: str = "",
        viewers: int | None = None,
    ) -> str | None:
        """Assemble les segments récents dans un MP4 (1m20 à 2m45) en 9:16 et l'indexe."""
        buf_dir = self._buffer_dir(username)
        clips_dir = self._clips_dir(username)
        os.makedirs(clips_dir, exist_ok=True)

        proc = self.processes.get(username)
        if proc and proc.poll() is not None and proc.stderr:
            err_output = proc.stderr.read().decode("utf-8", errors="replace").strip()
            if err_output:
                print(f"[FFMPEG ERREUR @{username}] {err_output}")

        selected_segments = self._select_bounded_segments(
            buf_dir=buf_dir,
            center_epoch=center_epoch,
            pre_seconds=pre_seconds,
            post_seconds=post_seconds,
        )

        if not selected_segments:
            print(f"[CLIP IGNORE] Aucun segment prêt dans {buf_dir} pour @{username}.")
            return None

        mean_db: float | None = None
        if self.min_volume_db is not None:
            mean_db = get_audio_loudness_db(selected_segments)
            if mean_db is not None and mean_db < self.min_volume_db:
                print(
                    f"[CLIP IGNORE] @{username} : niveau sonore trop calme "
                    f"({mean_db:.1f} dB < {self.min_volume_db:.1f} dB)."
                )
                self.cleanup_old_segments(username)
                return None

        index_path = os.path.join(self.base_output_dir, "clips_index.json")
        records = load_clips_index(index_path)
        clip_number = get_next_clip_number(records)

        approx_duration = len(selected_segments) * self.segment_seconds
        minutes, seconds = divmod(approx_duration, 60)
        concat_list_path = os.path.join(buf_dir, f"concat_{int(center_epoch)}.txt")
        suffix = "_9x16" if self.vertical_9_16 else ""
        safe_user = username.strip().lstrip("@")
        clip_name = (
            f"{clip_number:03d}_clip_{safe_user}_"
            f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(center_epoch))}{suffix}.mp4"
        )
        clip_path = os.path.join(clips_dir, clip_name)

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for seg_path in selected_segments:
                abs_path = os.path.abspath(seg_path).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{abs_path}'\n")

        cmd = self._build_ffmpeg_clip_cmd(concat_list_path, clip_path)

        try:
            subprocess.run(cmd, check=True)
            mode_label = "9:16 vertical" if self.vertical_9_16 else "original"
            print(f"[CLIP PRET #{clip_number:03d}] ({mode_label}, ~{minutes}m{seconds:02d}s) : {clip_path}")
            record_clip_created(
                clip_path=clip_path,
                streamer=username,
                approx_duration_s=approx_duration,
                clip_number=clip_number,
                reason=reason,
                viewers=viewers,
                mean_volume_db=mean_db,
                vertical_9_16=self.vertical_9_16,
                index_path=index_path,
            )
            return clip_path
        except subprocess.CalledProcessError as e:
            print(f"[ERREUR CLIP] Échec du découpage FFmpeg pour @{username}: {e}")
            return None
        finally:
            if os.path.exists(concat_list_path):
                os.remove(concat_list_path)
            self.cleanup_old_segments(username)

    async def schedule_clip(
        self,
        username: str,
        center_epoch: float,
        pre_seconds: int = DEFAULT_PRE_SECONDS,
        post_seconds: int = DEFAULT_POST_SECONDS,
        extra_post_seconds: int = 0,
        reason: str = "",
        viewers: int | None = None,
    ):
        """Attend la fin de la scène (avec prolongation optionnelle de continuité), puis génère le clip."""
        total_post = max(0, post_seconds + extra_post_seconds)
        if total_post > 0:
            await asyncio.sleep(total_post)
        self.create_clip_from_buffer(
            username=username,
            center_epoch=center_epoch,
            pre_seconds=pre_seconds,
            post_seconds=total_post,
            reason=reason,
            viewers=viewers,
        )