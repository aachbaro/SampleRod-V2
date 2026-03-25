from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .analyzer import TransientHit
from .pattern_generator import GeneratedBreakPattern


PREVIEW_MODE_RETIME = "retime"
PREVIEW_MODE_QUANTIZE = "quantize"
PREVIEW_MODE_PATTERN = "pattern"
QUANTIZE_GRID_DIVISIONS: tuple[int, ...] = (8, 16, 32)
DEFAULT_QUANTIZE_GRID_DIVISION = 16
DEFAULT_QUANTIZE_STRENGTH = 0.7
_GRID_LABELS = {8: "1/8", 16: "1/16", 32: "1/32"}


@dataclass(frozen=True)
class RetimedPreviewSegment:
    index: int
    source_start_s: float
    source_end_s: float
    preview_start_s: float
    preview_end_s: float
    label: str
    step_index: int | None = None
    source_index: int | None = None
    velocity: int | None = None


@dataclass(frozen=True)
class RetimedPreview:
    audio: np.ndarray
    loop_audio: np.ndarray | None
    sample_rate: int
    source_bpm: float
    target_bpm: float
    speed_ratio: float
    duration_s: float
    loop_duration_s: float
    segment_count: int
    segments: tuple[RetimedPreviewSegment, ...]
    mode: str = PREVIEW_MODE_RETIME
    quantize_grid_division: int | None = None
    quantize_strength: float = 0.0
    pattern: GeneratedBreakPattern | None = None


def build_retimed_preview(
    samples: np.ndarray,
    sample_rate: int,
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str = PREVIEW_MODE_RETIME,
    quantize_grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = 0.0,
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

    resolved_mode = _resolve_preview_mode(mode)
    resolved_grid = _resolve_quantize_grid_division(quantize_grid_division)
    resolved_strength = _resolve_quantize_strength(quantize_strength)
    speed_ratio = float(source_bpm / target_bpm)
    channel_count = normalized.shape[1]
    segment_schedule = _build_segment_schedule(
        ordered_hits,
        source_bpm=source_bpm,
        target_bpm=target_bpm,
        mode=resolved_mode,
        quantize_grid_division=resolved_grid,
        quantize_strength=resolved_strength,
    )

    rendered_segments: list[tuple[int, np.ndarray]] = []
    output_length = 0
    for hit, scheduled_segment in zip(ordered_hits, segment_schedule):
        start_time = float(scheduled_segment.source_start_s)
        end_time = float(scheduled_segment.source_end_s)
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

        new_start = int(round(float(scheduled_segment.preview_start_s) * sample_rate))
        rendered_segments.append((new_start, segment))
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
    source_duration_s = float(normalized.shape[0]) / float(sample_rate)
    loop_duration_s = max(
        source_duration_s * speed_ratio,
        max(float(segment.preview_start_s) for segment in segment_schedule) + (1.0 / float(sample_rate)),
    )
    loop_audio = _build_loop_audio(output, sample_rate=sample_rate, loop_duration_s=loop_duration_s, was_mono=was_mono)
    return RetimedPreview(
        audio=restored.astype(np.float32, copy=False),
        loop_audio=loop_audio,
        sample_rate=int(sample_rate),
        source_bpm=float(source_bpm),
        target_bpm=float(target_bpm),
        speed_ratio=speed_ratio,
        duration_s=duration_s,
        loop_duration_s=loop_duration_s,
        segment_count=len(rendered_segments),
        segments=tuple(segment_schedule),
        mode=resolved_mode,
        quantize_grid_division=resolved_grid if resolved_mode == PREVIEW_MODE_QUANTIZE else None,
        quantize_strength=resolved_strength if resolved_mode == PREVIEW_MODE_QUANTIZE else 0.0,
        pattern=None,
    )


def estimate_retimed_preview_duration(
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str = PREVIEW_MODE_RETIME,
    quantize_grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = 0.0,
) -> float:
    if source_bpm <= 1.0 or target_bpm <= 1.0:
        return 0.0
    ordered_hits = sorted(hits, key=lambda hit: float(hit.start_s))
    if len(ordered_hits) < 2:
        return 0.0
    segment_schedule = _build_segment_schedule(
        ordered_hits,
        source_bpm=source_bpm,
        target_bpm=target_bpm,
        mode=mode,
        quantize_grid_division=quantize_grid_division,
        quantize_strength=quantize_strength,
    )
    if not segment_schedule:
        return 0.0
    return max(float(segment.preview_end_s) for segment in segment_schedule)


def format_quantize_grid_label(grid_division: int | None) -> str:
    if grid_division is None:
        return "-"
    return _GRID_LABELS.get(int(grid_division), f"1/{int(grid_division)}")


def build_pattern_preview(
    samples: np.ndarray,
    sample_rate: int,
    pattern: GeneratedBreakPattern,
    *,
    target_bpm: float,
    fade_in_ms: float = 0.75,
    fade_out_ms: float = 5.0,
) -> RetimedPreview:
    if sample_rate <= 0:
        raise ValueError("Sample rate must be strictly positive")
    if target_bpm <= 1.0:
        raise ValueError("Target BPM must be strictly positive")

    normalized, was_mono = _normalize_audio_shape(samples)
    if normalized.size == 0:
        raise ValueError("Audio buffer is empty")

    scheduled_segments: list[RetimedPreviewSegment] = []
    rendered_segments: list[tuple[int, np.ndarray]] = []
    step_duration_s = (60.0 / float(target_bpm)) / 4.0
    channel_count = normalized.shape[1]
    output_length = 0

    for row_index, step in enumerate(pattern.steps, start=1):
        if step.source_start_s is None or step.source_end_s is None or step.label == "silence":
            continue
        start_time = float(step.source_start_s)
        end_time = max(float(step.source_end_s), start_time + 0.012)
        start_index = int(np.clip(round(start_time * sample_rate), 0, max(normalized.shape[0] - 1, 0)))
        end_index = int(np.clip(round(end_time * sample_rate), start_index + 1, normalized.shape[0]))
        if end_index <= start_index:
            continue

        segment = normalized[start_index:end_index].copy()
        gain = float(np.clip(step.velocity / 100.0, 0.12, 1.2)) if step.velocity is not None else 1.0
        segment *= np.float32(gain)
        _apply_edge_fades(
            segment,
            sample_rate=sample_rate,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

        preview_start_s = _pattern_step_start_seconds(
            step.step_index,
            step_duration_s=step_duration_s,
            swing=pattern.swing,
        )
        preview_end_s = preview_start_s + (float(segment.shape[0]) / float(sample_rate))
        scheduled_segments.append(
            RetimedPreviewSegment(
                index=row_index,
                source_start_s=start_time,
                source_end_s=end_time,
                preview_start_s=preview_start_s,
                preview_end_s=preview_end_s,
                label=step.label,
                step_index=step.step_index,
                source_index=step.source_hit_index,
                velocity=step.velocity,
            )
        )
        new_start = int(round(preview_start_s * sample_rate))
        rendered_segments.append((new_start, segment))
        output_length = max(output_length, new_start + segment.shape[0])

    if not rendered_segments or output_length <= 0:
        raise ValueError("Need at least one generated event with a valid source slice to build a preview")

    output = np.zeros((output_length, channel_count), dtype=np.float32)
    for new_start, segment in rendered_segments:
        new_end = min(output.shape[0], new_start + segment.shape[0])
        output[new_start:new_end] += segment[: new_end - new_start]

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.98:
        output *= np.float32(0.98 / peak)

    restored = output[:, 0] if was_mono else output
    duration_s = float(output.shape[0]) / float(sample_rate)
    loop_duration_s = float(pattern.step_count) * float(step_duration_s)
    loop_audio = _build_loop_audio(output, sample_rate=sample_rate, loop_duration_s=loop_duration_s, was_mono=was_mono)
    return RetimedPreview(
        audio=restored.astype(np.float32, copy=False),
        loop_audio=loop_audio,
        sample_rate=int(sample_rate),
        source_bpm=float(target_bpm),
        target_bpm=float(target_bpm),
        speed_ratio=1.0,
        duration_s=duration_s,
        loop_duration_s=loop_duration_s,
        segment_count=len(scheduled_segments),
        segments=tuple(scheduled_segments),
        mode=PREVIEW_MODE_PATTERN,
        quantize_grid_division=None,
        quantize_strength=0.0,
        pattern=pattern,
    )


def _build_segment_schedule(
    ordered_hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str,
    quantize_grid_division: int,
    quantize_strength: float,
) -> list[RetimedPreviewSegment]:
    resolved_mode = _resolve_preview_mode(mode)
    resolved_grid = _resolve_quantize_grid_division(quantize_grid_division)
    resolved_strength = _resolve_quantize_strength(quantize_strength)
    speed_ratio = float(source_bpm / target_bpm)
    base_time = float(ordered_hits[0].start_s)
    schedule: list[RetimedPreviewSegment] = []

    for index, hit in enumerate(ordered_hits, start=1):
        start_time = float(hit.start_s)
        end_time = max(float(hit.end_s), start_time + 0.012)
        segment_duration_s = end_time - start_time
        scaled_start_s = max(0.0, (start_time - base_time) * speed_ratio)
        preview_start_s = scaled_start_s
        if resolved_mode == PREVIEW_MODE_QUANTIZE:
            preview_start_s = _quantize_preview_start(
                scaled_start_s,
                target_bpm=target_bpm,
                grid_division=resolved_grid,
                strength=resolved_strength,
            )
        preview_end_s = preview_start_s + segment_duration_s
        schedule.append(
            RetimedPreviewSegment(
                index=index,
                source_start_s=start_time,
                source_end_s=end_time,
                preview_start_s=preview_start_s,
                preview_end_s=preview_end_s,
                label=hit.label,
            )
        )
    return schedule


def _resolve_preview_mode(mode: str) -> str:
    value = str(mode).lower()
    if value == PREVIEW_MODE_QUANTIZE:
        return PREVIEW_MODE_QUANTIZE
    if value == PREVIEW_MODE_PATTERN:
        return PREVIEW_MODE_PATTERN
    return PREVIEW_MODE_RETIME


def _resolve_quantize_grid_division(grid_division: int) -> int:
    try:
        value = int(grid_division)
    except (TypeError, ValueError):
        return DEFAULT_QUANTIZE_GRID_DIVISION
    if value in QUANTIZE_GRID_DIVISIONS:
        return value
    return DEFAULT_QUANTIZE_GRID_DIVISION


def _resolve_quantize_strength(strength: float) -> float:
    try:
        value = float(strength)
    except (TypeError, ValueError):
        return 0.0
    return float(np.clip(value, 0.0, 1.0))


def _quantize_preview_start(
    scaled_start_s: float,
    *,
    target_bpm: float,
    grid_division: int,
    strength: float,
) -> float:
    if target_bpm <= 1.0:
        return scaled_start_s
    beat_duration_s = 60.0 / float(target_bpm)
    grid_step_s = beat_duration_s * (4.0 / float(grid_division))
    if grid_step_s <= 1e-9:
        return scaled_start_s
    nearest_grid_index = np.floor((scaled_start_s / grid_step_s) + 0.5)
    quantized_start_s = max(0.0, float(nearest_grid_index * grid_step_s))
    return max(0.0, scaled_start_s + ((quantized_start_s - scaled_start_s) * strength))


def _pattern_step_start_seconds(step_index: int, *, step_duration_s: float, swing: float) -> float:
    zero_based = max(0, int(step_index) - 1)
    preview_start_s = float(zero_based) * float(step_duration_s)
    local_step = (zero_based % 16) + 1
    if local_step in {3, 7, 11, 15}:
        preview_start_s += float(np.clip(swing, 0.0, 1.0)) * (step_duration_s * 0.35)
    return max(0.0, preview_start_s)


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


def _build_loop_audio(
    output: np.ndarray,
    *,
    sample_rate: int,
    loop_duration_s: float,
    was_mono: bool,
) -> np.ndarray | None:
    if output.ndim != 2 or output.shape[0] <= 0 or sample_rate <= 0:
        return None
    loop_frames = int(round(max(loop_duration_s, 1.0 / float(sample_rate)) * float(sample_rate)))
    if loop_frames <= 0:
        return None

    loop_buffer = np.zeros((loop_frames, output.shape[1]), dtype=np.float32)
    copy_frames = min(loop_frames, output.shape[0])
    loop_buffer[:copy_frames] = output[:copy_frames]

    if output.shape[0] > loop_frames:
        tail = output[loop_frames:]
        for index in range(tail.shape[0]):
            loop_buffer[index % loop_frames] += tail[index]

    peak = float(np.max(np.abs(loop_buffer))) if loop_buffer.size else 0.0
    if peak > 0.98:
        loop_buffer *= np.float32(0.98 / peak)

    if was_mono:
        return loop_buffer[:, 0].astype(np.float32, copy=False)
    return loop_buffer.astype(np.float32, copy=False)


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
