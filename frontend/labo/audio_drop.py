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
import re
import tempfile
import uuid
from typing import Callable

from PySide6.QtCore import QMimeData
import soundfile as sf

from backend.services.audio_metadata import normalize_audio_path
from frontend.right_panel.composer.composer_dnd import (
    has_audio_file_urls,
    has_slice,
    has_sample_card,
    parse_audio_file_urls,
    parse_slice_mime,
    parse_sample_card_mime,
)

from .artifact_store import ARTIFACT_MIME


def has_supported_audio_drop(mime: QMimeData) -> bool:
    """Vrai si le depot contient des fichiers audio ou une carte de sample."""
    return (
        has_audio_file_urls(mime)
        or has_sample_card(mime)
        or has_slice(mime)
        or mime.hasFormat(ARTIFACT_MIME)
    )


def can_accept_audio_drop(
    mime: QMimeData,
    *,
    sample_path_lookup: Callable[[int], str | None],
    artifact_path_lookup: Callable[[str], str | None] | None = None,
) -> bool:
    """Validation sans effet de bord pour les survols de drag-and-drop.

    Contrairement a resolve_audio_drop_paths(), cette fonction ne cree aucun
    fichier temporaire pour une slice ; elle sert aux dragEnter/dragMove.
    """
    if has_audio_file_urls(mime):
        return bool(parse_audio_file_urls(mime))

    if has_sample_card(mime):
        try:
            payload = parse_sample_card_mime(mime)
        except Exception:
            return False
        sample_path = sample_path_lookup(int(payload["sample_id"]))
        return bool(sample_path and os.path.isfile(sample_path))

    if has_slice(mime):
        try:
            payload = parse_slice_mime(mime)
        except Exception:
            return False
        audio = payload.get("audio")
        return getattr(audio, "size", 0) > 0 and int(payload.get("sample_rate", 0) or 0) > 0

    if mime.hasFormat(ARTIFACT_MIME) and artifact_path_lookup is not None:
        for artifact_id in _artifact_ids_from_mime(mime):
            path = artifact_path_lookup(artifact_id)
            if path and os.path.isfile(path):
                return True

    return False


def resolve_audio_drop_paths(
    mime: QMimeData,
    *,
    sample_path_lookup: Callable[[int], str | None],
    artifact_path_lookup: Callable[[str], str | None] | None = None,
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

    if not paths and has_slice(mime):
        try:
            payload = parse_slice_mime(mime)
            temp_path = _materialize_slice_payload(payload)
        except Exception:
            temp_path = ""
        if temp_path:
            paths.append(temp_path)

    if not paths and mime.hasFormat(ARTIFACT_MIME) and artifact_path_lookup is not None:
        for artifact_id in _artifact_ids_from_mime(mime):
            path = artifact_path_lookup(artifact_id)
            if path:
                paths.append(path)

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


def _artifact_ids_from_mime(mime: QMimeData) -> list[str]:
    try:
        raw = bytes(mime.data(ARTIFACT_MIME)).decode("utf-8", errors="ignore")
    except Exception:
        return []
    artifact_id = raw.strip()
    if not artifact_id:
        return []
    return [artifact_id]


def _materialize_slice_payload(payload: dict) -> str:
    """Ecrit une slice draggee dans un WAV temporaire reutilisable par le Labo."""
    audio = payload["audio"]
    sample_rate = int(payload["sample_rate"])
    label = _sanitize_slice_label(str(payload.get("label") or "slice"))

    folder = os.path.join(tempfile.gettempdir(), "SampleRod", "drag_slices")
    os.makedirs(folder, exist_ok=True)
    filename = f"{label}_{uuid.uuid4().hex[:8]}.wav"
    path = os.path.join(folder, filename)
    # La slice vient de la waveform editee en memoire (float32). Un WAV FLOAT
    # evite la quantification PCM16 au moment ou une cible exige un chemin.
    sf.write(path, audio, sample_rate, subtype="FLOAT")
    return path


def _sanitize_slice_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", label.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "slice"
