import time
from src.highlight_detector import HighlightDetector
from src.clip_manager import ClipManager


def run_simulation():
    print("=== Debut de la simulation hors ligne ===\n")

    clip_manager = ClipManager(pre_seconds=15, post_seconds=10)
    detector = HighlightDetector(
        window_seconds=10,
        message_spike_threshold=6,
        cooldown_seconds=5,
        on_highlight=clip_manager.handle_highlight,
    )

    print("--- Test 1 : Pic de messages ---")
    for i in range(1, 7):
        detector.process_message(
            username="steuplai_spam",
            author=f"Viewer_{i}",
            comment=f"Message rapide numero {i}",
        )
        time.sleep(0.2)

    print("\n--- Test 2 : Cooldown actif ---")
    detector.process_message(
        username="steuplai_spam",
        author="Viewer_7",
        comment="dinguerie totale",
    )

    print("\n--- Test 3 : Apres cooldown + mot-cle ---")
    time.sleep(5.5)
    detector.process_message(
        username="deveen_off",
        author="Fan_1",
        comment="incroyable ce move, clip ca !",
    )

    print(f"\nTotal moments forts enregistres : {len(detector.highlights)}")
    print("Fichier de sortie attendu : output\\highlights.json")


if __name__ == "__main__":
    run_simulation()