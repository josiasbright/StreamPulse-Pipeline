import os
from clips_index import DEFAULT_INDEX_PATH, load_clips_index, mark_clip_as_posted


def _resolve_clip_record(pending: list[dict], raw_input: str) -> dict | None:
    cleaned = raw_input.strip().lstrip("#")
    if not cleaned:
        return None

    # 1. Correspondance directe par clip_number ou clip_code (ex: "1", "001")
    if cleaned.isdigit():
        num_val = int(cleaned)
        for rec in pending:
            if rec.get("clip_number") == num_val or str(rec.get("clip_code", "")).lstrip("0") == str(num_val):
                return rec
        # 2. Sinon index d'affichage 1..N dans la liste pending
        if 1 <= num_val <= len(pending):
            return pending[num_val - 1]

    # 3. Correspondance par nom ou chemin de fichier
    lower = cleaned.lower()
    for rec in pending:
        file_name = str(rec.get("file_name", "")).lower()
        file_path = str(rec.get("file_path", "")).lower()
        if lower == file_name or lower == file_path or (len(lower) >= 4 and lower in file_name):
            return rec

    return None


def main():
    records = load_clips_index(DEFAULT_INDEX_PATH)
    pending = [
        r for r in records
        if not r.get("posted") and not r.get("deleted_from_disk")
    ]

    if not pending:
        print("Aucun clip en attente de publication.")
        return

    print("\n=== CLIPS PRETS A POSTER (PAR COMPTE) ===")
    for r in pending:
        clip_num = r.get("clip_number")
        code = str(r.get("clip_code") or (f"{clip_num:03d}" if isinstance(clip_num, int) else "???"))
        streamer = str(r.get("streamer") or "").lstrip("@")
        file_name = r.get("file_name", "")
        file_path = r.get("file_path", "")
        account_folder = r.get("account_folder") or (os.path.dirname(file_path) if file_path else os.path.join("output", "clips", streamer))
        title = r.get("suggested_title") or ""
        tags = " ".join(r.get("suggested_hashtags") or [])
        duration_s = r.get("approx_duration_s", 0)
        mins, secs = divmod(int(duration_s or 0), 60)

        print(f"\n[{code}] Compte : @{streamer} | Durée : ~{mins}m{secs:02d}s")
        print(f"      Dossier : {account_folder}")
        print(f"      Fichier : {file_name}")
        print(f"      Titre   : {title}")
        print(f"      Tags    : {tags}")

    choice = input("\nEntre le numéro du clip posté (ex. 001 ou 1, ou Entrée pour quitter) : ").strip()
    if not choice:
        return

    selected = _resolve_clip_record(pending, choice)
    if not selected:
        print("Numéro ou clip introuvable dans la liste en attente.")
        return

    target_id = selected.get("clip_code") or selected.get("file_name") or ""
    ok, msg = mark_clip_as_posted(str(target_id), DEFAULT_INDEX_PATH)
    print(msg)


if __name__ == "__main__":
    main()