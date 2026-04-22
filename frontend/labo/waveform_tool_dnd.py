from __future__ import annotations

from .audio_drop import has_supported_audio_drop, resolve_audio_drop_paths


def has_supported_waveform_drop(mime):
    return has_supported_audio_drop(mime)


def resolve_waveform_drop_paths(mime, *, sample_path_lookup):
    return resolve_audio_drop_paths(mime, sample_path_lookup=sample_path_lookup)
