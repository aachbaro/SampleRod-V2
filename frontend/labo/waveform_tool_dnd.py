# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Mini-module de compatibilite : l'outil Waveform du Labo utilisait ses
#   propres fonctions de glisser-deposer ; elles sont desormais de simples
#   alias vers les utilitaires communs de audio_drop.py.
#
# FONCTIONS (sommaire)
# - has_supported_waveform_drop()  : alias de has_supported_audio_drop().
# - resolve_waveform_drop_paths()  : alias de resolve_audio_drop_paths().
# -----------------------------------------------------------------------------

from __future__ import annotations

from .audio_drop import has_supported_audio_drop, resolve_audio_drop_paths


def has_supported_waveform_drop(mime):
    """Alias : le depot contient-il de l'audio exploitable ?"""
    return has_supported_audio_drop(mime)


def resolve_waveform_drop_paths(mime, *, sample_path_lookup):
    """Alias : convertit le depot en liste de chemins audio valides."""
    return resolve_audio_drop_paths(mime, sample_path_lookup=sample_path_lookup)
