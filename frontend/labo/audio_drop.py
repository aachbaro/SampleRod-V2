# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Petit utilitaire partage par les outils du Labo pour accepter les
#   glisser-deposer audio, quels qu'ils soient : fichiers venant de
#   l'explorateur Windows OU cartes de samples venant de l'application.
#
# FONCTIONS (sommaire)
# - has_supported_audio_drop()  : ce depot contient-il de l'audio exploitable ?
#   (utilise pour accepter/refuser le survol pendant le drag).
# - resolve_audio_drop_paths()  : transforme le depot en liste de chemins de
#   fichiers valides — les cartes de samples sont converties en chemins via
#   la fonction sample_path_lookup fournie par l'appelant ; doublons et
#   fichiers inexistants sont elimines.
#
# LIENS CLES
# - frontend/right_panel/composer/composer_dnd.py : decodage des formats MIME.
# - frontend/labo/* : les outils qui acceptent ces depots.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QMimeData

from backend.services.audio_metadata import normalize_audio_path
from frontend.right_panel.composer.composer_dnd import (
    has_audio_file_urls,
    has_sample_card,
    parse_audio_file_urls,
    parse_sample_card_mime,
)


def has_supported_audio_drop(mime: QMimeData) -> bool:
    """Vrai si le depot contient des fichiers audio ou une carte de sample."""
    return has_audio_file_urls(mime) or has_sample_card(mime)


def resolve_audio_drop_paths(
    mime: QMimeData,
    *,
    sample_path_lookup: Callable[[int], str | None],
) -> list[str]:
    """Convertit un depot en liste de chemins audio valides et uniques."""
    paths: list[str] = []

    if has_audio_file_urls(mime):
        paths.extend(parse_audio_file_urls(mime))

    if not paths and has_sample_card(mime):
        payload = parse_sample_card_mime(mime)
        sample_path = sample_path_lookup(int(payload["sample_id"]))
        if sample_path:
            paths.append(sample_path)

    normalized_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_audio_path(path)
        if not normalized or normalized in seen:
            continue
        if not os.path.isfile(normalized):
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    return normalized_paths
