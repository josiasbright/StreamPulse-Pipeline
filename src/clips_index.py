import json
import os
import time


DEFAULT_INDEX_PATH = os.path.join("output", "clips_index.json")


def load_clips_index(index_path: str = DEFAULT_INDEX_PATH) -> list[dict]:
    if not os.path.exists(index_path):
        return []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_clips_index(records: list[dict], index_path: str = DEFAULT_INDEX_PATH):
    parent = os.path.dirname(index_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def get_next_clip_number(records: list[dict] | None = None, index_path: str = DEFAULT_INDEX_PATH) -> int:
    if records is None:
        records = load_clips_index(index_path)
    max_num = 0
    for rec in records:
        val = rec.get("clip_number")
        if isinstance(val, int) and val > max_num:
            max_num = val
    return max_num + 1


def _build_publish_suggestion(
    streamer: str,
    reason: str,
    approx_duration_s: int,
    clip_number: int,
) -> tuple[str, list[str]]:
    clean_user = streamer.lstrip("@").replace(".", "_").replace("-", "_")
    minutes, seconds = divmod(approx_duration_s, 60)
    duration_txt = f"{minutes}m{seconds:02d}s"
    reason_short = (reason or "Moment fort du live").strip()
    if len(reason_short) > 70:
        reason_short = reason_short[:67].rstrip() + "..."

    title = f"#{clip_number:03d} @{streamer} — {reason_short} ({duration_txt})"
    hashtags = [
        "#tiktoklive",
        "#clipstiktok",
        "#momentfort",
        "#buzz",
        f"#{clean_user}",
    ]
    return title, hashtags


def record_clip_created(
    clip_path: str,
    streamer: str,
    approx_duration_s: int,
    clip_number: int | None = None,
    reason: str = "",
    viewers: int | None = None,
    mean_volume_db: float | None = None,
    vertical_9_16: bool = True,
    index_path: str = DEFAULT_INDEX_PATH,
):
    records = load_clips_index(index_path)
    assigned_number = clip_number if isinstance(clip_number, int) and clip_number > 0 else get_next_clip_number(records)
    abs_clip = os.path.abspath(clip_path)
    suggested_title, suggested_hashtags = _build_publish_suggestion(
        streamer=streamer,
        reason=reason,
        approx_duration_s=approx_duration_s,
        clip_number=assigned_number,
    )

    entry = {
        "id": f"clip_{int(time.time() * 1000)}",
        "clip_number": assigned_number,
        "clip_code": f"{assigned_number:03d}",
        "streamer": streamer,
        "account_folder": os.path.dirname(abs_clip),
        "file_path": abs_clip,
        "file_name": os.path.basename(abs_clip),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "approx_duration_s": approx_duration_s,
        "vertical_9_16": vertical_9_16,
        "viewers": viewers,
        "mean_volume_db": round(mean_volume_db, 1) if mean_volume_db is not None else None,
        "reason": reason,
        "suggested_title": suggested_title,
        "suggested_hashtags": suggested_hashtags,
        "posted": False,
        "posted_at": None,
        "deleted_from_disk": False,
    }

    records.append(entry)
    save_clips_index(records, index_path)
    return entry


def mark_clip_as_posted(target: str, index_path: str = DEFAULT_INDEX_PATH) -> tuple[bool, str]:
    records = load_clips_index(index_path)
    clean_target = target.strip().lstrip("#")
    norm_target = os.path.normcase(os.path.abspath(clean_target)) if os.path.exists(clean_target) else clean_target.lower()

    matched = False
    for rec in records:
        rec_path = os.path.normcase(os.path.abspath(rec.get("file_path", "")))
        rec_name = str(rec.get("file_name", "")).lower()
        rec_code = str(rec.get("clip_code", "")).lower()
        rec_num = str(rec.get("clip_number", ""))

        if (
            norm_target in (rec_path, rec_name, rec_code, rec_num)
            or (len(clean_target) >= 4 and clean_target.lower() in rec_name)
        ):
            rec["posted"] = True
            if not rec.get("posted_at"):
                rec["posted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            matched = True

    if matched:
        save_clips_index(records, index_path)
        return True, f"Clip marqué comme posté : {target} (sera supprimé à la fermeture de session)."

    return False, f"Aucun clip trouvé dans l'index pour : {target}"


def cleanup_posted_clips(index_path: str = DEFAULT_INDEX_PATH) -> int:
    """Supprime du disque les fichiers marqués posted=True sans toucher aux clips non postés."""
    records = load_clips_index(index_path)
    if not records:
        return 0

    deleted_count = 0
    changed = False

    for rec in records:
        if rec.get("posted") is True:
            file_path = rec.get("file_path") or ""
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                    changed = True
                    print(f"[NETTOYAGE POSTE] Clip supprimé du PC : {file_path}")
                except OSError as e:
                    print(f"[ERREUR SUPPRESSION] Impossible de supprimer {file_path} : {e}")
            if not rec.get("deleted_from_disk"):
                rec["deleted_from_disk"] = True
                changed = True

    if changed:
        save_clips_index(records, index_path)

    return deleted_count