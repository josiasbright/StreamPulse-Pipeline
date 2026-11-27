import asyncio
import time


class ClipManager:
    def __init__(
        self,
        pre_seconds: int = 95,
        post_seconds: int = 30,
        recorder=None,
        viewer_counts: dict[str, int] | None = None,
        continuation_window_seconds: float = 150.0,
        continuation_extra_post: int = 20,
    ):
        self.pre_seconds = pre_seconds
        self.post_seconds = post_seconds
        self.recorder = recorder
        self.viewer_counts = viewer_counts if viewer_counts is not None else {}
        self.continuation_window_seconds = continuation_window_seconds
        self.continuation_extra_post = continuation_extra_post
        self._last_highlight_epoch: dict[str, float] = {}

    def handle_highlight(self, highlight: dict):
        streamer = highlight.get("streamer")
        timestamp = highlight.get("timestamp")
        reason = highlight.get("reason") or ""
        epoch = highlight.get("epoch")

        if not streamer or epoch is None:
            return

        now = time.time()
        prev_epoch = self._last_highlight_epoch.get(streamer)
        is_continuation = (
            prev_epoch is not None and (now - prev_epoch) <= self.continuation_window_seconds
        )
        self._last_highlight_epoch[streamer] = now

        extra_post = self.continuation_extra_post if is_continuation else 0
        effective_post = self.post_seconds + extra_post
        current_viewers = self.viewer_counts.get(streamer)

        start_epoch = epoch - self.pre_seconds
        end_epoch = epoch + effective_post

        mode_txt = "CONTINUITE (+20s)" if is_continuation else "NOUVEAU CLIP"
        print(
            f"[CLIP PLANIFIE - {mode_txt}] @{streamer} à {timestamp} | "
            f"Fenêtre cible: -{self.pre_seconds}s / +{effective_post}s "
            f"(timestamp début: {start_epoch:.0f}, fin: {end_epoch:.0f}) | "
            f"Raison: {reason}"
        )

        if self.recorder is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.recorder.schedule_clip(
                        username=streamer,
                        center_epoch=epoch,
                        pre_seconds=self.pre_seconds,
                        post_seconds=self.post_seconds,
                        extra_post_seconds=extra_post,
                        reason=reason,
                        viewers=current_viewers,
                    )
                )
            except RuntimeError:
                self.recorder.create_clip_from_buffer(
                    username=streamer,
                    center_epoch=epoch,
                    pre_seconds=self.pre_seconds,
                    post_seconds=effective_post,
                    reason=reason,
                    viewers=current_viewers,
                )