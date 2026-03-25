"""Standalone drum detector prototype for SampleRod."""

from .analyzer import (
    DEFAULT_SPLIT_DENSITY,
    DrumCandidate,
    DrumDetectionResult,
    TransientHit,
    analyze_file,
    analyze_file_from_markers,
    detect_drum_from_audio,
    detect_drum_from_markers,
)
from .preview import RetimedPreview, RetimedPreviewSegment, build_retimed_preview

__all__ = [
    "DrumCandidate",
    "DrumDetectionResult",
    "RetimedPreview",
    "RetimedPreviewSegment",
    "TransientHit",
    "analyze_file",
    "analyze_file_from_markers",
    "build_retimed_preview",
    "DEFAULT_SPLIT_DENSITY",
    "detect_drum_from_audio",
    "detect_drum_from_markers",
]
