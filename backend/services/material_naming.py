from __future__ import annotations

import os
import re


_TECH_TOKEN = re.compile(r"^[0-9a-f]{8}$", re.IGNORECASE)
_AUDIO_TOKEN = {"wav", "flac", "aif", "aiff", "mp3", "ogg"}


def human_material_base(value: str, fallback: str = "Audio") -> str:
    """Retire les extensions encodées et UUID techniques accumulés."""
    stem = os.path.splitext(os.path.basename(str(value or "")))[0]
    tokens = [token for token in stem.split("_") if token]
    while tokens and (_TECH_TOKEN.match(tokens[-1]) or tokens[-1].lower() in _AUDIO_TOKEN):
        tokens.pop()
    return "_".join(tokens).strip(" _-") or fallback


def material_display_name(
    source_path: str,
    *,
    kind: str = "",
    detail: str = "",
) -> str:
    base = human_material_base(source_path)
    suffix = str(detail or "").strip()
    if not suffix:
        suffix = {
            "audio_selection": "sélection",
            "slice": "sélection",
            "stem": "stem",
            "current_file": "édition",
        }.get(str(kind or ""), "")
    return f"{base} · {suffix}" if suffix else base


def promoted_file_stem(source_path: str, previous_kind: str) -> str:
    base = human_material_base(source_path, "source")
    suffix = {
        "audio_selection": "selection",
        "stem": "stem",
    }.get(str(previous_kind or ""), "derive")
    return f"{base}_{suffix}"
