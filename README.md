# StreamPulse-Pipeline

Pipeline Python asynchrone de surveillance de diffusions en direct, de détection de pics d'engagement en temps réel et de traitement vidéo automatisé (`1080x1920` / `9:16`) via **FFmpeg**, conçu autour d'un flux de publication semi-automatisé avec indexation séquentielle et gestion automatique du stockage.

---

## Aperçu et choix d'architecture

La conception repose sur une approche pragmatique de **semi-automatisation maîtrisée** :

- **Exécution technique automatisée :** écoute asynchrone des diffusions en direct (`asyncio` + `TikTokLive`), capture segmentée avec rétention disque bornée, détection des pics d'activité et de continuité, contrôle audio, encodage vertical `9:16` avec arrière-plan flouté, génération de métadonnées éditoriales (titre et hashtags) et purge automatique des fichiers publiés à la fermeture de session.
- **Validation humaine finale :** la mise en ligne finale et le choix de l'habillage sonore restent sous contrôle manuel, garantissant la stabilité du flux de travail et évitant les blocages liés à l'automatisation non officielle de publication.

---

## Architecture du projet

```text
StreamPulse-Pipeline/
├── src/
│   ├── monitor.py            # Orchestrateur principal, gestion des reconnexions et cycle de vie
│   ├── highlight_detector.py # Analyse temps réel des commentaires et détection des pics d'activité
│   ├── clip_manager.py       # Calcul des fenêtres temporelles et gestion de la continuité
│   ├── stream_recorder.py    # Capture FFmpeg, arbitrage de concurrence et encodage 1080x1920
│   ├── clips_index.py        # Numérotation séquentielle, indexation JSON et nettoyage disque
│   ├── publish_helper.py     # Interface CLI interactive de consultation et validation par numéro
│   └── mark_posted.py        # Utilitaire CLI de suivi d'état et de marquage des publications
├── config.example.json       # Modèle de configuration des créateurs surveillés
├── requirements.txt          # Dépendances Python du projet
├── .gitignore                # Exclusion des médias générés, tampons et configurations locales
└── README.md

Fonctionnalités clés
1. Surveillance asynchrone et gestion de concurrence
Écoute simultanée de plusieurs créateurs configurés dans config.json.

Plafonnement des captures actives (max_concurrent_recordings = 3) avec arbitrage dynamique basé sur l'audience (priorisation des diffusions à plus forte affluence).

Gestion des déconnexions avec période de temporisation (cooldown) pour éviter les boucles de reconnexion agressives.

2. Détection de moments forts et continuité
Analyse glissante du débit de messages du chat pour identifier les pics d'engagement.

Prolongation dynamique de la fenêtre de capture (extra_post_seconds) lorsque l'activité reste soutenue après un pic afin d'éviter les coupures brutales en pleine action.

Contrôle optionnel du niveau sonore moyen (volumedetect / dBFS) avant validation du rendu final.

3. Encodage vertical prêt pour la diffusion (9:16)
Assemblage des segments .ts du tampon circulaire en séquences bornées entre 1 min 20 s (80s) et 2 min 45 s (165s).

Conversion au format 1080×1920 (H.264 / AAC, 30 fps) avec arrière-plan flouté (boxblur) pour préserver l'intégralité du cadrage original sans recadrage destructif.

4. Indexation séquentielle et hygiène du stockage
Attribution d'un identifiant numérique séquentiel (001, 002, 003...) et classement isolé par créateur dans output/clips/<createur>/.

Centralisation des métadonnées (durée, audience, volume, titre et hashtags suggérés, statut de publication) dans output/clips_index.json.

Suppression automatique des fichiers .mp4 marqués posted: true à l'arrêt propre de la session, tout en conservant les clips en attente.

Prérequis
Python 3.13 ou supérieur

FFmpeg installé et accessible dans la variable d'environnement PATH

Git