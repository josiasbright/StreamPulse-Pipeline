import json
import os
import time
from collections import defaultdict, deque


class HighlightDetector:
    def __init__(
        self,
        keywords=None,
        window_seconds: int = 10,
        message_spike_threshold: int = 25,
        cooldown_seconds: int = 90,
        output_file: str = os.path.join("output", "highlights.json"),
        on_highlight=None,
    ):
        # Mots-clés plus sélectifs (évite les mots du quotidien comme "quoi", "gg", "mdr", "lol")
        self.keywords = keywords or [
            "clip",
            "dinguerie",
            "incroyable",
            "no way",
            "omg",
            "ptdr",
            "fou",
        ]
        self.window_seconds = window_seconds
        self.message_spike_threshold = message_spike_threshold
        self.cooldown_seconds = cooldown_seconds
        self.output_file = output_file
        self.on_highlight = on_highlight

        self._message_times = defaultdict(deque)
        self._recent_comments = defaultdict(lambda: deque(maxlen=15))
        self._last_trigger = defaultdict(float)
        self.highlights = self._load_existing()

    def _load_existing(self):
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _save_to_disk(self):
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(self.highlights, f, ensure_ascii=False, indent=2)

    def _is_repetitive_spam(self, username: str, lower_text: str) -> bool:
        """Évite de déclencher un clip uniquement sur un message copié-collé en boucle."""
        recent = self._recent_comments[username]
        recent.append(lower_text)
        same_count = sum(1 for m in recent if m == lower_text)
        return same_count >= 5

    def process_message(self, username: str, author: str, comment: str):
        now = time.time()
        text = comment.strip()
        if not text:
            return None

        lower_text = text.lower()

        times = self._message_times[username]
        times.append(now)

        while times and (now - times[0]) > self.window_seconds:
            times.popleft()

        if self._is_repetitive_spam(username, lower_text):
            return None

        matched_keywords = [kw for kw in self.keywords if kw in lower_text]
        msg_count = len(times)
        is_spike = msg_count >= self.message_spike_threshold

        # Un mot-clé seul ne suffit que s'il y a aussi un minimum d'activité (ex. au moins 5 msgs / 10s)
        has_strong_keyword = bool(matched_keywords) and msg_count >= 5

        reasons = []
        if is_spike:
            reasons.append(f"pic de {msg_count} msgs / {self.window_seconds}s")
        if has_strong_keyword:
            reasons.append(f"mots-clés: {', '.join(matched_keywords)}")

        if reasons and (now - self._last_trigger[username]) >= self.cooldown_seconds:
            self._last_trigger[username] = now
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            reason_str = " + ".join(reasons)

            highlight = {
                "timestamp": timestamp_str,
                "epoch": now,
                "streamer": username,
                "author": author,
                "comment": text,
                "reason": reason_str,
            }
            self.highlights.append(highlight)
            self._save_to_disk()

            print(
                f"\n[MOMENT FORT] @{username} | {timestamp_str} | "
                f"{reason_str} | Dernier msg ({author}): {text}\n"
            )

            if callable(self.on_highlight):
                self.on_highlight(highlight)

            return highlight

        return None