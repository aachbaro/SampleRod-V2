from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .analyzer import TransientHit


@dataclass(frozen=True)
class RetimedPreviewSegment:
    index: int
    source_start_s: float
    source_end_s: float
    preview_start_s: float
    preview_end_s: float
    label: str


@dataclass(frozen=True)
class RetimedPreview:
    audio: np.ndarray
    sample_rate: int
    source_bpm: float
    target_bpm: float
    speed_ratio: float
    duration_s: float
    segment_count: int
    segments: tuple[RetimedPreviewSegment, ...]


def build_retimed_preview(
    samples: np.ndarray,
    sample_rate: int,
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    fade_in_ms: float = 0.75,
    fade_out_ms: float = 5.0,
) -> RetimedPreview:
    if sample_rate <= 0:
        raise ValueError("Sample rate must be strictly positive")
    if source_bpm <= 1.0 or target_bpm <= 1.0:
        raise ValueError("Source and target BPM must be strictly positive")

    ordered_hits = sorted(hits, key=lambda hit: float(hit.start_s))
    if len(ordered_hits) < 2:
        raise ValueError("Need at least two transient hits to build a retimed preview")

    normalized, was_mono = _normalize_audio_shape(samples)
    if normalized.size == 0:
        raise ValueError("Audio buffer is empty")

    speed_ratio = float(source_bpm / target_bpm)
    base_time = float(ordered_hits[0].start_s)
    channel_count = normalized.shape[1]

    rendered_segments: list[tuple[int, np.ndarray]] = []
    segment_schedule: list[RetimedPreviewSegment] = []
    output_length = 0
    for index, hit in enumerate(ordered_hits, start=1):
        start_time = float(hit.start_s)
        end_time = max(float(hit.end_s), start_time + 0.012)
        start_index = int(np.clip(round(start_time * sample_rate), 0, max(normalized.shape[0] - 1, 0)))
        end_index = int(np.clip(round(end_time * sample_rate), start_index + 1, normalized.shape[0]))
        if end_index <= start_index:
            continue

        segment = normalized[start_index:end_index].copy()
        _apply_edge_fades(
            segment,
            sample_rate=sample_rate,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

        new_start_s = max(0.0, (start_time - base_time) * speed_ratio)
        segment_duration_s = float(segment.shape[0]) / float(sample_rate)
        preview_end_s = new_start_s + segment_duration_s
        new_start = int(round(new_start_s * sample_rate))
        rendered_segments.append((new_start, segment))
        segment_schedule.append(
            RetimedPreviewSegment(
                index=index,
                source_start_s=start_time,
                source_end_s=end_time,
                preview_start_s=new_start_s,
                preview_end_s=preview_end_s,
                label=hit.label,
            )
        )
        output_length = max(output_length, new_start + segment.shape[0])

    if not rendered_segments or output_length <= 0:
        raise ValueError("Could not build a retimed preview from the detected hits")

    output = np.zeros((output_length, channel_count), dtype=np.float32)
    for new_start, segment in rendered_segments:
        new_end = min(output.shape[0], new_start + segment.shape[0])
        output[new_start:new_end] += segment[: new_end - new_start]

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.98:
        output *= np.float32(0.98 / peak)

    restored = output[:, 0] if was_mono else output
    duration_s = float(output.shape[0]) / float(sample_rate)
    return RetimedPreview(
        audio=restored.astype(np.float32, copy=False),
        sample_rate=int(sample_rate),
        source_bpm=float(source_bpm),
        target_bpm=float(target_bpm),
        speed_ratio=speed_ratio,
        duration_s=duration_s,
        segment_count=len(rendered_segments),
        segments=tuple(segment_schedule),
    )


def _normalize_audio_shape(samples: np.ndarray) -> tuple[np.ndarray, bool]:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        return audio[:, np.newaxis], True
    if audio.ndim != 2:
        raise ValueError("Audio samples must be mono or multi-channel")

    if audio.shape[0] <= 8 and audio.shape[1] > audio.shape[0]:
        audio = audio.T
    if audio.shape[1] <= 0:
        raise ValueError("Audio buffer has no channels")
    return audio, bool(audio.shape[1] == 1)


def _apply_edge_fades(
    segment: np.ndarray,
    *,
    sample_rate: int,
    fade_in_ms: float,
    fade_out_ms: float,
) -> None:
    if segment.ndim != 2 or segment.shape[0] <= 2:
        return

    fade_in = int(round(sample_rate * max(fade_in_ms, 0.0) / 1000.0))
    fade_out = int(round(sample_rate * max(fade_out_ms, 0.0) / 1000.0))
    max_fade = max(1, segment.shape[0] // 3)
    fade_in = min(fade_in, max_fade)
    fade_out = min(fade_out, max_fade)

    if fade_in > 1:
        ramp_in = np.linspace(0.0, 1.0, fade_in, endpoint=True, dtype=np.float32)[:, np.newaxis]
        segment[:fade_in] *= ramp_in
    if fade_out > 1:
        ramp_out = np.linspace(1.0, 0.0, fade_out, endpoint=True, dtype=np.float32)[:, np.newaxis]
        segment[-fade_out:] *= ramp_out
