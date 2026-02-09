"""
------------------------------------------------------------------------------
Sample Composer - Drag & Drop helpers
------------------------------------------------------------------------------
Role
----
Centralise la logique de "decodage" des drops pour le Compositeur.

On suit le meme pattern que DirectoryWidget:
- l'UI (widget) decide d'accepter ou non le drop
- ce module extrait/valide les donnees du QMimeData (payload pickled)

MIME supporte (MVP)
------------------
- application/x-sample-slice-data
  Payload (pickle dict):
  - audio_data: np.ndarray float32 (mono (n,) ou stereo (n,2))
  - sample_rate: int
  - name: str (nom du sample source)

Note securite
-------------
On utilise pickle uniquement parce que le drag & drop est interne a l'app.
Ne pas accepter ce MIME depuis une source non fiable (ex: navigateur, fichier).
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import pickle
from typing import Any

import numpy as np
from PyQt6.QtCore import QMimeData

logger = logging.getLogger("sample_composer_dnd")

MIME_SAMPLE_SLICE = "application/x-sample-slice-data"
MIME_SAMPLE_CARD = "application/x-sample-card"


def has_slice(mime: QMimeData) -> bool:
    return mime.hasFormat(MIME_SAMPLE_SLICE)


def has_sample_card(mime: QMimeData) -> bool:
    return mime.hasFormat(MIME_SAMPLE_CARD)


def parse_slice_mime(mime: QMimeData) -> dict[str, Any]:
    """
    Decode le payload du MIME slice et renvoie un dict normalise:
    - audio: np.ndarray float32
    - sample_rate: int
    - label: str
    - source: dict (payload original, sans l'audio si besoin)
    """
    raw_bytes = bytes(mime.data(MIME_SAMPLE_SLICE))
    payload = pickle.loads(raw_bytes)

    if not isinstance(payload, dict):
        raise ValueError("Invalid slice payload: expected dict.")

    audio = payload.get("audio_data")
    sr = payload.get("sample_rate")
    name = payload.get("name") or "slice"

    if audio is None:
        raise ValueError("Invalid slice payload: missing audio_data.")

    audio_arr = np.asarray(audio, dtype=np.float32)
    audio_arr = np.ascontiguousarray(audio_arr, dtype=np.float32)

    try:
        sr_int = int(sr)
    except Exception as e:
        raise ValueError(f"Invalid slice payload: sample_rate={sr!r}") from e

    if sr_int <= 0:
        raise ValueError(f"Invalid slice payload: sample_rate={sr_int}")

    label = str(name)
    # Source: on garde le payload original pour debug/telemetrie.
    source = dict(payload)
    # Evite de dupliquer une reference potentiellement lourde dans `source`.
    source.pop("audio_data", None)

    return {
        "audio": audio_arr,
        "sample_rate": sr_int,
        "label": label,
        "source": source,
    }


def parse_sample_card_mime(mime: QMimeData) -> dict[str, Any]:
    """
    Decode le payload du MIME sample-card.
    Payload attendue (pickle dict): { "sample_id": int }
    """
    raw_bytes = bytes(mime.data(MIME_SAMPLE_CARD))
    payload = pickle.loads(raw_bytes)
    if not isinstance(payload, dict):
        raise ValueError("Invalid sample-card payload: expected dict.")

    sample_id = payload.get("sample_id")
    try:
        sample_id = int(sample_id)
    except Exception as e:
        raise ValueError(f"Invalid sample-card payload: sample_id={sample_id!r}") from e

    return {"sample_id": sample_id, "source": dict(payload)}
