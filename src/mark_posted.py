import argparse
import os
from clips_index import DEFAULT_INDEX_PATH, load_clips_index, mark_clip_as_posted


def main():
    parser = argparse.ArgumentParser(
        description="Affiche les clips par numéro et compte, ou marque un clip comme posté."
    )
    parser.add_argument(
        "clip",
        nargs="?",
        help="Numéro du clip (ex. 001 ou 1), nom ou chemin du fichier .mp4 posté",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Affiche les clips enregistrés avec leur numéro, dossier du compte, titre et hashtags",
    )
    args = parser.parse_args()

    if args.list or not args.clip:
        records = load_clips_index(DEFAULT_INDEX_PATH)
        if not records:
            print("Aucun clip dans output\\clips_index.json.")
            return

        for r in records:
            clip_num = r.get("clip_number")
            code = str(r.get("clip_code") or (f"{clip_num:03d}" if isinstance(clip_num, int) else "???"))
            streamer = str(r.get("streamer") or "").lstrip("@")
            file_name = r.get("file_name", "")
            file_path = r.get("file_path", "")
            account_folder = r.get("account_folder") or (
                os.path.dirname(file_path) if file_path else os.path.join("output", "clips", streamer)
            )

            status = "POSTE (à supprimer)" if r.get("posted") else "A POSTER"
            if r.get("deleted_from_disk"):
                status = "SUPPRIME"

            title = r.get("suggested_title") or ""
            tags = " ".join(r.get("suggested_hashtags") or [])

            print(f"[{code}] [{status}] @{streamer} | {file_name}")
            print(f"      Dossier : {account_folder}")
            if not r.get("deleted_from_disk") and (title or tags):
                print(f"      Titre   : {title}")
                print(f"      Tags    : {tags}")
        return

    ok, msg = mark_clip_as_posted(args.clip, DEFAULT_INDEX_PATH)
    print(msg)


if __name__ == "__main__":
    main()