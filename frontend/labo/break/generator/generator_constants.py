# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe les constantes partagees par la facade et les controleurs du
#   generateur de break.
# - Evite les imports circulaires entre widget, UI builder et controleurs.
# -----------------------------------------------------------------------------

from __future__ import annotations

from backend.services.drum_analysis_service import (
    PATTERN_TAIL_MODE_CUT,
    PATTERN_TAIL_MODE_PING_PONG,
    PATTERN_TAIL_MODE_REVERSE,
)

GENERATOR_MODE_CLASSIC = "classic"
GENERATOR_MODE_HYBRID = "hybrid"
GENERATOR_MODE_LABELS: dict[str, str] = {
    GENERATOR_MODE_CLASSIC: "Classic",
    GENERATOR_MODE_HYBRID: "Hybrid",
}

GENERATION_PROFILE_LABELS: dict[str, str] = {
    "safe": "Safe",
    "musical": "Musical",
    "destructive": "Destructive",
}

FILL_STYLE_LABELS: dict[str, str] = {
    "auto": "Auto",
    "ghost_hat": "Ghost + Hat",
    "ruff": "Ruff",
    "crash_open": "Crash / Open",
    "double_kick": "Double kick",
    "dense": "Dense",
    "perc_burst": "Perc burst",
    "kick_snare_alternance": "Kick / Snare alt.",
    "silence_drop": "Silence drop",
}

PITCH_MODE_OPTIONS: tuple[str, ...] = ("off", "random", "sequence", "curve")
PITCH_SCOPE_OPTIONS: tuple[str, ...] = ("snare", "snare+clap", "all_pillar", "all")
PITCH_SCALE_OPTIONS: tuple[str, ...] = (
    "chromatic",
    "minor",
    "major",
    "pentatonic",
    "diminished",
)
PITCH_RATE_OPTIONS: tuple[str, ...] = ("every_hit", "every_2", "every_bar")
PITCH_CURVE_OPTIONS: tuple[str, ...] = ("up", "down", "bell", "inv_bell")
SNARE_STRETCH_CURVE_OPTIONS: tuple[str, ...] = ("flat", "decay", "crescendo", "random")
PITCH_NOTE_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)

STEP_SHORT_LABELS: dict[str, str] = {
    "kick": "K",
    "kick_ghost": "Kg",
    "snare": "S",
    "snare_ghost": "Sg",
    "snare_ruff": "Rf",
    "clap": "C",
    "closed_hat": "HC",
    "open_hat": "HO",
    "crash": "Cr",
    "ride": "Rd",
    "tom": "T",
    "perc": "P",
    "silence": "-",
}

STEP_COLORS: dict[str, str] = {
    "kick": "#d46666",
    "kick_ghost": "#b35f5f",
    "snare": "#d89747",
    "snare_ghost": "#b68553",
    "snare_ruff": "#c0a06d",
    "clap": "#d0b04a",
    "closed_hat": "#4bb6b7",
    "open_hat": "#30c9ca",
    "crash": "#8d6ad8",
    "ride": "#7960ba",
    "tom": "#5a93db",
    "perc": "#76afd8",
}

GENERATOR_STEP_ANCHOR_ORDER: tuple[str | None, ...] = (
    None,
    "kick",
    "snare",
    "clap",
    "hat",
    "ghost",
    "other",
    "silence",
)
GENERATOR_STEP_ANCHOR_SHORT_LABELS: dict[str | None, str] = {
    None: ".",
    "kick": "K",
    "snare": "S",
    "clap": "C",
    "hat": "H",
    "ghost": "G",
    "other": "O",
    "silence": "-",
}
GENERATOR_STEP_ANCHOR_LABELS: dict[str | None, str] = {
    None: "auto",
    "kick": "kick",
    "snare": "snare",
    "clap": "clap",
    "hat": "hat",
    "ghost": "ghost",
    "other": "other",
    "silence": "silence",
}

DEFAULT_PITCH_SEQUENCE = "0, 3, -2, 7"
PATTERN_TAIL_MODE_LABELS: dict[str, str] = {
    PATTERN_TAIL_MODE_CUT: "Cut",
    PATTERN_TAIL_MODE_REVERSE: "Reverse",
    PATTERN_TAIL_MODE_PING_PONG: "Ping-pong",
}
