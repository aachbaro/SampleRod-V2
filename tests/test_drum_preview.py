from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QRadioButton, QSlider, QTableWidgetItem, QWidget

from prototypes.drum_detector.analyzer import (
    DrumCandidate,
    DrumDetectionResult,
    HitSequence,
    HitSequenceEvent,
    TransientHit,
)
from prototypes.drum_detector.pattern_generator import (
    BreakPatternParams,
    GeneratedBreakPattern,
    GeneratedPatternStep,
    STRETCH_TICKS_PER_STEP,
    StretchRetrigger,
    generate_break_pattern,
)
from prototypes.drum_detector.preview import (
    PATTERN_STEM_NAMES,
    PREVIEW_MODE_PATTERN,
    PREVIEW_MODE_QUANTIZE,
    RetimedPreview,
    RetimedPreviewSegment,
    build_retimed_preview_schedule,
    _pitch_shift_audio_segment,
    build_pattern_preview,
    build_retimed_preview,
)


def _test_stretch_retriggers(
    source_hit: TransientHit,
    *,
    start_step: int,
    offsets: tuple[int, ...],
    velocities: tuple[float, ...] | None = None,
) -> tuple[StretchRetrigger, ...]:
    if velocities is None:
        velocities = tuple(100.0 for _ in offsets)
    retriggers: list[StretchRetrigger] = []
    for offset_ticks, velocity in zip(offsets, velocities):
        retriggers.append(
            StretchRetrigger(
                slice_source=source_hit,
                offset_ticks=int(offset_ticks),
                step_index=int(start_step + (int(offset_ticks) // STRETCH_TICKS_PER_STEP)),
                sub_step_offset=int(int(offset_ticks) % STRETCH_TICKS_PER_STEP),
                velocity=float(velocity),
            )
        )
    return tuple(retriggers)


class _FakeSettings:
    def __init__(self, *_args, **_kwargs) -> None:
        self._values: dict[str, object] = {}

    def value(self, key: str, default=None, type=None):
        value = self._values.get(key, default)
        if type is None or value is None:
            return value
        try:
            return type(value)
        except Exception:
            return default

    def setValue(self, key: str, value) -> None:
        self._values[key] = value


class _FakeSounddevice:
    class CallbackStop(Exception):
        pass

    class _Stream:
        def __init__(
            self,
            *,
            samplerate: int,
            channels: int,
            dtype: str,
            blocksize: int,
            latency: str,
            callback,
        ) -> None:
            self.samplerate = samplerate
            self.channels = channels
            self.dtype = dtype
            self.blocksize = blocksize
            self.latency = latency
            self.callback = callback
            self.active = False
            self.closed = False

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            self.closed = True
            self.active = False

    def __init__(self) -> None:
        self.streams: list[_FakeSounddevice._Stream] = []

    def OutputStream(self, **kwargs):
        stream = self._Stream(**kwargs)
        self.streams.append(stream)
        return stream


class _FakeMarkerItem:
    def __init__(self, time_s: float) -> None:
        self._payload = {"time": float(time_s)}
        self._tooltip = ""

    def data(self, role):
        if role == Qt.ItemDataRole.UserRole:
            return self._payload
        return None

    def setToolTip(self, text: str) -> None:
        self._tooltip = str(text)


class _FakeMarkerList:
    def __init__(self, marker_times: list[float]) -> None:
        self._items = [_FakeMarkerItem(time_s) for time_s in marker_times]

    def count(self) -> int:
        return len(self._items)

    def item(self, row: int):
        return self._items[row]


class _FakeViewBox:
    def __init__(self, start: float, end: float) -> None:
        self._range = [[float(start), float(end)], [-1.0, 1.0]]

    def viewRange(self):
        return self._range


class _FakePlot:
    def __init__(self, start: float, end: float) -> None:
        self._view_box = _FakeViewBox(start, end)
        self.last_range: tuple[float, float, int] | None = None
        self.removed_items: list[object] = []

    def getViewBox(self):
        return self._view_box

    def setXRange(self, start: float, end: float, padding: int = 0) -> None:
        self.last_range = (float(start), float(end), int(padding))
        self._view_box._range[0] = [float(start), float(end)]

    def removeItem(self, item) -> None:
        self.removed_items.append(item)


class _FakeReadHead:
    def __init__(self) -> None:
        self.positions: list[float] = []

    def setPos(self, value: float) -> None:
        self.positions.append(float(value))


class _FakeWaveformWidget:
    def __init__(self, marker_times: list[float], *, duration: float, visible_range: tuple[float, float]) -> None:
        self.marker_list = _FakeMarkerList(marker_times)
        self.plot = _FakePlot(*visible_range)
        self.duration = float(duration)
        self.waveform_data = np.zeros(100, dtype=np.float32)
        self.audio_file_path: str | None = None
        self.markers = [float(time_s) for time_s in marker_times]
        self.marker_lines = {float(time_s): object() for time_s in marker_times}
        self.current_marker_idx = 0
        self.play_start = 0.0
        self.play_end = 0.0
        self.region = None
        self._record_history = True
        self.read_head = _FakeReadHead()
        self.clicked_payloads: list[dict[str, float]] = []
        self.play_calls = 0
        self.stop_calls = 0

    def on_marker_list_clicked(self, item) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            self.clicked_payloads.append(payload)

    def play_from_start(self) -> None:
        self.play_calls += 1

    def stop_audio(self) -> None:
        self.stop_calls += 1

    def add_marker(self, time_s: float) -> None:
        marker_time = float(time_s)
        self.markers.append(marker_time)
        self.markers.sort()
        self.marker_lines[marker_time] = object()
        self.marker_list = _FakeMarkerList(self.markers)

    def _refresh_marker_list(self) -> None:
        self.marker_list = _FakeMarkerList(self.markers)

    def set_waveform_data(self, waveform_data, sample_rate: int, duration_s: float) -> None:
        self.waveform_data = np.asarray(waveform_data)
        self.duration = float(duration_s)


def _test_detection_result(*, source_path: str | None = None) -> DrumDetectionResult:
    hits = (
        TransientHit(
            index=1,
            start_s=0.0,
            end_s=0.12,
            label="kick",
            confidence=0.92,
            peak_db=-3.0,
            low_ratio=0.8,
            mid_ratio=0.15,
            high_ratio=0.05,
            secondary_labels=(),
            layer_score=0.0,
            role="pillar",
            rhythmic_position="downbeat",
        ),
        TransientHit(
            index=2,
            start_s=0.25,
            end_s=0.36,
            label="snare",
            confidence=0.88,
            peak_db=-4.5,
            low_ratio=0.1,
            mid_ratio=0.7,
            high_ratio=0.2,
            secondary_labels=("clap",),
            layer_score=0.25,
            role="pillar",
            rhythmic_position="backbeat",
        ),
    )
    return DrumDetectionResult(
        source_path=source_path,
        label="break",
        form="loop",
        family="drum",
        confidence=0.91,
        loop_score=0.83,
        drum_score=0.96,
        break_score=0.8,
        duration_s=1.0,
        sample_rate=16000,
        tempo_bpm=120.0,
        pulse_score=0.75,
        regularity=0.7,
        onset_count=len(hits),
        onset_density=2.0,
        percussive_ratio=0.92,
        harmonic_ratio=0.08,
        decay_s=0.18,
        spectral_centroid_hz=3200.0,
        spectral_flatness=0.28,
        band_energies={"low": 0.7, "mid": 0.5, "high": 0.35},
        transient_hits=hits,
        candidates=(
            DrumCandidate(label="break", score=0.91, details="test"),
        ),
        hit_sequences=(
            HitSequence(
                index=1,
                role="groove",
                hit_count=2,
                total_steps=4,
                source_start_s=0.0,
                source_end_s=0.36,
                start_step_hint=1,
                end_step_hint=5,
                labels=("kick", "snare"),
                events=(
                    HitSequenceEvent(
                        order=0,
                        hit_index=1,
                        label="kick",
                        role="pillar",
                        start_offset_steps=0,
                        interval_steps=0,
                        velocity_ratio=1.0,
                        source_start_s=0.0,
                        source_end_s=0.12,
                        secondary_labels=(),
                        layer_score=0.0,
                        rhythmic_position="downbeat",
                    ),
                    HitSequenceEvent(
                        order=1,
                        hit_index=2,
                        label="snare",
                        role="pillar",
                        start_offset_steps=4,
                        interval_steps=4,
                        velocity_ratio=0.92,
                        source_start_s=0.25,
                        source_end_s=0.36,
                        secondary_labels=("clap",),
                        layer_score=0.25,
                        rhythmic_position="backbeat",
                    ),
                ),
            ),
        ),
    )


def _test_generated_pattern(
    *,
    seed: int = 123,
    bars: int = 1,
    gate: float = 1.0,
    mono_choke: bool = False,
) -> GeneratedBreakPattern:
    params = BreakPatternParams(
        seed=seed,
        bars=bars,
        gate=gate,
        mono_choke=mono_choke,
        energy=0.64,
        kick_weight=0.7,
        snare_weight=0.72,
        fill_strength=0.4,
    )
    step_count = 16 * bars
    steps = []
    for step_index in range(1, step_count + 1):
        if step_index == 1:
            steps.append(
                GeneratedPatternStep(
                    step_index=step_index,
                    label="kick",
                    velocity=118,
                    source_hit_index=1,
                    source_label="kick",
                    source_start_s=0.0,
                    source_end_s=0.12,
                    tags=("downbeat",),
                )
            )
        elif step_index == 5:
            steps.append(
                GeneratedPatternStep(
                    step_index=step_index,
                    label="snare",
                    velocity=110,
                    source_hit_index=2,
                    source_label="snare",
                    source_start_s=0.25,
                    source_end_s=0.36,
                    tags=("backbeat",),
                )
            )
        else:
            steps.append(
                GeneratedPatternStep(
                    step_index=step_index,
                    label="silence",
                    velocity=0,
                    source_hit_index=None,
                    source_label=None,
                    source_start_s=None,
                    source_end_s=None,
                    tags=(),
                )
            )
    return GeneratedBreakPattern(
        bars=bars,
        step_count=step_count,
        seed=seed,
        swing=float(params.swing),
        params=params,
        event_count=2,
        summary="kick 1, snare 1",
        steps=tuple(steps),
        fill_decisions=(),
        metrics={"fill_ratio": 0.0},
    )



class _BootWaveformWidget(QWidget):
    def __init__(self, *_args, **_kwargs) -> None:
        super().__init__()
        self.plot = QWidget(self)
        self.save_button = QPushButton(self)
        self.play_button = QPushButton(self)
        self.pause_button = QPushButton(self)
        self.stop_button = QPushButton(self)
        self.undo_button = QPushButton(self)
        self.redo_button = QPushButton(self)
        self.waveform_data = np.zeros(32, dtype=np.float32)
        self.duration = 0.0
        self.marker_calls: list[tuple[str, object]] = []

    def _cut_region(self, start, end) -> None:
        self.marker_calls.append(("cut", (start, end)))

    def undo(self) -> None:
        self.marker_calls.append(("undo", None))

    def redo(self) -> None:
        self.marker_calls.append(("redo", None))

    def add_marker(self, time_s) -> None:
        self.marker_calls.append(("add", float(time_s)))

    def remove_marker(self, time_s) -> None:
        self.marker_calls.append(("remove", float(time_s)))

    def _on_marker_move_finished(self, line) -> None:
        self.marker_calls.append(("move", line))

    def stop_audio(self) -> None:
        return

    def set_waveform_data(self, waveform_data, sample_rate: int, duration_s: float) -> None:
        self.waveform_data = np.asarray(waveform_data)
        self.duration = float(duration_s)


class _FakeActiveStream:
    def __init__(self) -> None:
        self.active = True
        self.stop_calls = 0
        self.close_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.active = False

    def close(self) -> None:
        self.close_calls += 1
        self.active = False


class DrumPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_copy_preview_frames_wraps_cleanly_in_loop_mode(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        audio = np.arange(5, dtype=np.float32)[:, np.newaxis]
        outdata = np.zeros((8, 1), dtype=np.float32)

        cursor, frames_written, should_stop = drum_ui._copy_preview_frames(
            outdata,
            audio,
            3,
            loop_enabled=True,
        )

        self.assertEqual(cursor, 1)
        self.assertEqual(frames_written, 8)
        self.assertFalse(should_stop)
        self.assertTrue(
            np.array_equal(
                outdata[:, 0],
                np.asarray([3, 4, 0, 1, 2, 3, 4, 0], dtype=np.float32),
            )
        )

    def test_copy_preview_frames_stops_and_zero_fills_in_one_shot_mode(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        audio = np.arange(5, dtype=np.float32)[:, np.newaxis]
        outdata = np.full((8, 1), -1.0, dtype=np.float32)

        cursor, frames_written, should_stop = drum_ui._copy_preview_frames(
            outdata,
            audio,
            3,
            loop_enabled=False,
        )

        self.assertEqual(cursor, 5)
        self.assertEqual(frames_written, 2)
        self.assertTrue(should_stop)
        self.assertTrue(
            np.array_equal(
                outdata[:, 0],
                np.asarray([3, 4, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            )
        )

    def test_retimed_preview_shortens_hit_spacing_when_target_bpm_is_higher(self) -> None:
        sample_rate = 1000
        audio = np.zeros(900, dtype=np.float32)
        audio[0:200] = 1.0
        audio[500:700] = 0.5

        hits = (
            TransientHit(1, 0.0, 0.2, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.5, 0.7, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        preview = build_retimed_preview(audio, sample_rate, hits, source_bpm=100.0, target_bpm=200.0)

        self.assertAlmostEqual(preview.speed_ratio, 0.5, places=3)
        self.assertAlmostEqual(preview.duration_s, 0.45, places=2)
        self.assertEqual(preview.segment_count, 2)
        self.assertEqual(len(preview.segments), 2)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.25, places=3)
        self.assertAlmostEqual(preview.segments[1].source_start_s, 0.5, places=3)
        self.assertGreater(float(np.max(preview.audio[10:160])), 0.85)
        self.assertGreater(float(np.max(preview.audio[260:410])), 0.35)

    def test_retimed_preview_preserves_stereo_shape(self) -> None:
        sample_rate = 1000
        left = np.zeros(700, dtype=np.float32)
        right = np.zeros(700, dtype=np.float32)
        left[0:120] = 0.7
        right[0:120] = -0.7
        left[350:470] = 0.4
        right[350:470] = -0.4
        stereo = np.column_stack((left, right))

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.35, 0.47, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        preview = build_retimed_preview(stereo, sample_rate, hits, source_bpm=90.0, target_bpm=120.0)

        self.assertEqual(preview.audio.ndim, 2)
        self.assertEqual(preview.audio.shape[1], 2)
        self.assertGreater(float(np.max(preview.audio[:, 0])), 0.3)
        self.assertLess(float(np.min(preview.audio[:, 1])), -0.3)

    def test_quantized_preview_snaps_hit_to_grid_when_strength_is_full(self) -> None:
        sample_rate = 1000
        audio = np.zeros(400, dtype=np.float32)
        audio[0:80] = 1.0
        audio[110:190] = 0.6
        hits = (
            TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.11, 0.19, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        preview = build_retimed_preview(
            audio,
            sample_rate,
            hits,
            source_bpm=120.0,
            target_bpm=120.0,
            mode=PREVIEW_MODE_QUANTIZE,
            quantize_grid_division=16,
            quantize_strength=1.0,
        )

        self.assertEqual(preview.mode, PREVIEW_MODE_QUANTIZE)
        self.assertEqual(preview.quantize_grid_division, 16)
        self.assertAlmostEqual(preview.quantize_strength, 1.0, places=3)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.125, places=3)

    def test_quantized_preview_strength_blends_original_timing_and_grid(self) -> None:
        sample_rate = 1000
        audio = np.zeros(400, dtype=np.float32)
        audio[0:80] = 1.0
        audio[110:190] = 0.6
        hits = (
            TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.11, 0.19, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        preview = build_retimed_preview(
            audio,
            sample_rate,
            hits,
            source_bpm=120.0,
            target_bpm=120.0,
            mode=PREVIEW_MODE_QUANTIZE,
            quantize_grid_division=16,
            quantize_strength=0.5,
        )

        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.1175, places=3)

    def test_retimed_preview_global_mono_choke_truncates_previous_segment(self) -> None:
        sample_rate = 1000
        audio = np.zeros(600, dtype=np.float32)
        audio[0:300] = 1.0
        audio[250:450] = 0.6
        hits = (
            TransientHit(1, 0.0, 0.3, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.25, 0.45, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        preview = build_retimed_preview(
            audio,
            sample_rate,
            hits,
            source_bpm=120.0,
            target_bpm=120.0,
            mono_choke=True,
        )
        schedule = build_retimed_preview_schedule(
            hits,
            source_bpm=120.0,
            target_bpm=120.0,
            mono_choke=True,
        )

        self.assertTrue(preview.mono_choke)
        self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.25, places=3)
        self.assertAlmostEqual(preview.segments[0].source_end_s, 0.25, places=3)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.25, places=3)
        self.assertAlmostEqual(schedule[0].preview_end_s, 0.25, places=3)

    def test_retimed_preview_schedule_can_be_built_without_rendering_audio(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.11, 0.19, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )

        schedule = build_retimed_preview_schedule(
            hits,
            source_bpm=120.0,
            target_bpm=120.0,
            mode=PREVIEW_MODE_QUANTIZE,
            quantize_grid_division=16,
            quantize_strength=1.0,
        )

        self.assertEqual(len(schedule), 2)
        self.assertAlmostEqual(schedule[1].preview_start_s, 0.125, places=3)
        self.assertAlmostEqual(schedule[1].source_start_s, 0.11, places=3)

    def test_retime_preview_visual_widget_shows_quantize_offsets_and_active_segment(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=120.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.11, 0.19, "snare", 0.8, -4.0, 0.1, 0.2, 0.7),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            quantize_index = window.preview_mode_combo.findData(PREVIEW_MODE_QUANTIZE)
            window.preview_mode_combo.setCurrentIndex(quantize_index)
            grid_index = window.quantize_grid_combo.findData(16)
            window.quantize_grid_combo.setCurrentIndex(grid_index)
            window.quantize_strength_slider.setValue(100)

            window._update_retimed_preview_state(result)

            self.assertEqual(window.retime_pattern_preview.segment_count, 2)
            self.assertEqual(window.retime_pattern_preview._mode, PREVIEW_MODE_QUANTIZE)
            self.assertAlmostEqual(window.retime_pattern_preview._scaled_starts[1], 0.11, places=3)
            self.assertAlmostEqual(window.retime_pattern_preview._preview_starts[1], 0.125, places=3)

            preview = build_retimed_preview(
                np.zeros(400, dtype=np.float32),
                1000,
                result.transient_hits,
                source_bpm=120.0,
                target_bpm=120.0,
                mode=PREVIEW_MODE_QUANTIZE,
                quantize_grid_division=16,
                quantize_strength=1.0,
            )
            window._retimed_preview = preview
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_RETIME
            window._retime_stream = _FakeActiveStream()
            window._retime_stream_total_frames = 400
            window._retime_stream_frames_played = 130

            window._update_retimed_preview_visual()

            self.assertEqual(window.retime_pattern_preview.active_segment_index, 1)
            window.close()

    def test_generated_pattern_preview_uses_step_grid_and_velocity_gain(self) -> None:
        sample_rate = 1000
        audio = np.zeros(900, dtype=np.float32)
        audio[0:120] = 1.0
        audio[250:370] = 0.7
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
            TransientHit(2, 0.25, 0.37, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.18, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=5,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=0.8,
                ghost_density=0.0,
                swing=0.0,
            ),
        )

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        self.assertEqual(preview.mode, PREVIEW_MODE_PATTERN)
        self.assertIs(preview.pattern, pattern)
        self.assertGreater(preview.segment_count, 0)
        self.assertTrue(all(segment.step_index is not None for segment in preview.segments))
        self.assertTrue(all(segment.velocity is not None for segment in preview.segments))
        self.assertAlmostEqual(preview.segments[0].preview_start_s, 0.0, places=3)

    def test_generated_pattern_preview_applies_swing_to_offbeats(self) -> None:
        sample_rate = 1000
        audio = np.zeros(500, dtype=np.float32)
        audio[0:80] = 1.0
        hits = (
            TransientHit(1, 0.0, 0.08, "closed_hat", 0.9, -1.0, 0.2, 0.3, 0.8),
            TransientHit(2, 0.1, 0.18, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )
        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=18,
                energy=0.9,
                hat_density=1.0,
                snare_weight=1.0,
                swing=1.0,
            ),
        )

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)
        offbeats = [segment for segment in preview.segments if segment.step_index in {3, 7, 11, 15}]
        if offbeats:
            self.assertGreater(offbeats[0].preview_start_s, 0.25)

    def test_pattern_loop_audio_wraps_tail_back_to_cycle_start(self) -> None:
        sample_rate = 1000
        audio = np.zeros(1200, dtype=np.float32)
        audio[900:1100] = 0.75
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=16,
                source_start_s=0.9,
                source_end_s=1.1,
                label="snare",
                velocity=100,
                source_hit_index=1,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        self.assertAlmostEqual(preview.loop_duration_s, 2.0, places=3)
        self.assertIsNotNone(preview.loop_audio)
        self.assertEqual(preview.loop_audio.shape[0], 2000)
        self.assertGreater(float(np.max(preview.loop_audio[:60])), 0.1)

    def test_generated_pattern_preview_gate_shortens_slice_lengths(self) -> None:
        sample_rate = 1000
        audio = np.zeros(400, dtype=np.float32)
        audio[0:200] = 1.0
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.2,
                label="kick",
                velocity=100,
                source_hit_index=1,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0, gate=0.5)

        self.assertAlmostEqual(preview.segments[0].source_end_s, 0.1, places=3)
        self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.1, places=3)
        self.assertEqual(preview.audio.shape[0], 100)

    def test_generated_pattern_preview_global_mono_choke_truncates_previous_step(self) -> None:
        sample_rate = 1000
        audio = np.zeros(500, dtype=np.float32)
        audio[0:220] = 1.0
        audio[50:250] = 0.7
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.22,
                label="kick",
                velocity=100,
                source_hit_index=1,
                tags=(),
            ),
            mock.Mock(
                step_index=2,
                source_start_s=0.05,
                source_end_s=0.25,
                label="snare",
                velocity=100,
                source_hit_index=2,
                tags=(),
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0, mono_choke=True)

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        self.assertTrue(preview.mono_choke)
        self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.125, places=3)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.125, places=3)
        self.assertAlmostEqual(preview.segments[0].source_end_s, 0.125, places=3)

    def test_generated_pattern_preview_retriggers_repeat_glitch_within_same_step(self) -> None:
        sample_rate = 1000
        audio = np.zeros(400, dtype=np.float32)
        audio[0:200] = 1.0
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=3,
                source_start_s=0.0,
                source_end_s=0.2,
                label="closed_hat",
                velocity=100,
                source_hit_index=1,
                tags=("offbeat", "repeat", "repeat_glitch", "repeat_count_4"),
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        self.assertEqual(preview.segment_count, 4)
        self.assertTrue(all(segment.step_index == 3 for segment in preview.segments))
        self.assertAlmostEqual(preview.segments[0].preview_start_s, 0.25, places=3)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.28125, places=3)
        self.assertLess(preview.segments[0].source_end_s - preview.segments[0].source_start_s, 0.2)

    def test_generated_pattern_preview_reverses_audio_for_reverse_tagged_step(self) -> None:
        sample_rate = 100
        audio = np.asarray([0.05, 0.1, 0.15, 0.2], dtype=np.float32)
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.04,
                label="snare",
                velocity=100,
                source_hit_index=1,
                tags=("strong", "reverse"),
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(
            audio,
            sample_rate,
            pattern,
            target_bpm=120.0,
            fade_in_ms=0.0,
            fade_out_ms=0.0,
        )

        np.testing.assert_allclose(preview.audio[:4], np.asarray([0.2, 0.15, 0.1, 0.05], dtype=np.float32))

    def test_generated_pattern_preview_applies_pitch_shift_per_step(self) -> None:
        from prototypes.drum_detector import preview as drum_preview

        sample_rate = 1000
        audio = np.zeros(400, dtype=np.float32)
        audio[0:90] = np.linspace(0.0, 1.0, 90, dtype=np.float32)
        pitched_pattern = mock.Mock()
        pitched_pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.09,
                label="snare",
                velocity=100,
                source_hit_index=1,
                tags=("downbeat",),
                pitch_shift=7.0,
            ),
        )
        pitched_pattern.swing = 0.0
        pitched_pattern.step_count = 16
        pitched_pattern.params = BreakPatternParams(pitch_mode="random", pitch_amount=1.0)

        plain_pattern = mock.Mock()
        plain_pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.09,
                label="snare",
                velocity=100,
                source_hit_index=1,
                tags=("downbeat",),
                pitch_shift=0.0,
            ),
        )
        plain_pattern.swing = 0.0
        plain_pattern.step_count = 16
        plain_pattern.params = BreakPatternParams()

        with mock.patch.object(
            drum_preview,
            "_pitch_shift_audio_segment",
            side_effect=lambda segment, *, sample_rate, pitch_shift: segment * np.float32(0.25),
        ) as pitch_mock:
            pitched_preview = build_pattern_preview(audio, sample_rate, pitched_pattern, target_bpm=120.0)

        plain_preview = build_pattern_preview(audio, sample_rate, plain_pattern, target_bpm=120.0)

        pitch_mock.assert_called_once()
        self.assertFalse(np.allclose(pitched_preview.audio[:90], plain_preview.audio[:90]))
        self.assertLess(float(np.max(np.abs(pitched_preview.audio[:90]))), float(np.max(np.abs(plain_preview.audio[:90]))))

    def test_pitch_shift_audio_segment_uses_safe_fft_for_short_buffers(self) -> None:
        class _FakeEffects:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def pitch_shift(self, y, *, sr, n_steps, **kwargs):
                self.calls.append({"sr": sr, "n_steps": n_steps, **kwargs})
                return np.asarray(y, dtype=np.float32)

        fake_effects = _FakeEffects()
        fake_librosa = mock.Mock()
        fake_librosa.effects = fake_effects
        segment = np.linspace(-1.0, 1.0, 1898, dtype=np.float32)

        with mock.patch("prototypes.drum_detector.preview._require_librosa", return_value=fake_librosa):
            shifted = _pitch_shift_audio_segment(segment, sample_rate=44100, pitch_shift=3.0)

        np.testing.assert_allclose(shifted, segment)
        self.assertEqual(len(fake_effects.calls), 1)
        self.assertEqual(fake_effects.calls[0]["n_fft"], 1024)
        self.assertEqual(fake_effects.calls[0]["win_length"], 1024)
        self.assertEqual(fake_effects.calls[0]["hop_length"], 256)

    def test_generated_pattern_preview_applies_synthetic_ghost_velocity_pitch_and_gate(self) -> None:
        from prototypes.drum_detector import preview as drum_preview

        sample_rate = 1000
        audio = np.ones(400, dtype=np.float32)
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.2,
                label="snare_ghost",
                velocity=100,
                source_hit_index=1,
                tags=("downbeat",),
                pitch_shift=2.0,
                is_synthetic_ghost=True,
                ghost_vel_ratio=0.5,
                ghost_pitch_offset=1.0,
                ghost_gate_ratio=0.5,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(synth_ghost_enabled=True)

        with mock.patch.object(
            drum_preview,
            "_pitch_shift_audio_segment",
            side_effect=lambda segment, *, sample_rate, pitch_shift: segment * np.float32(0.5),
        ) as pitch_mock:
            preview = build_pattern_preview(
                audio,
                sample_rate,
                pattern,
                target_bpm=120.0,
                fade_in_ms=0.0,
                fade_out_ms=0.0,
            )

        pitch_mock.assert_called_once()
        self.assertAlmostEqual(float(pitch_mock.call_args.kwargs["pitch_shift"]), 3.0, places=6)
        self.assertEqual(preview.audio.shape[0], 100)
        self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.1, places=3)
        self.assertEqual(preview.segments[0].velocity, 50)
        self.assertAlmostEqual(float(np.max(preview.audio)), 0.25, places=5)

    def test_synthetic_ghost_gate_ratio_zero_keeps_full_slice_length(self) -> None:
        sample_rate = 1000
        audio = np.ones(400, dtype=np.float32)
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.2,
                label="snare_ghost",
                velocity=100,
                source_hit_index=1,
                tags=("downbeat",),
                pitch_shift=0.0,
                is_synthetic_ghost=True,
                ghost_vel_ratio=0.5,
                ghost_pitch_offset=0.0,
                ghost_gate_ratio=0.0,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(synth_ghost_enabled=True)

        preview = build_pattern_preview(
            audio,
            sample_rate,
            pattern,
            target_bpm=120.0,
            fade_in_ms=0.0,
            fade_out_ms=0.0,
        )

        self.assertEqual(preview.audio.shape[0], 200)
        self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.2, places=3)

    def test_generated_pattern_preview_caps_reverse_tail_to_step_slot(self) -> None:
        sample_rate = 1000
        audio = np.ones(400, dtype=np.float32)
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=2,
                source_start_s=0.0,
                source_end_s=0.2,
                label="kick",
                velocity=100,
                source_hit_index=1,
                tags=("subdivision", "reverse", "effect_reverse"),
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(
            audio,
            sample_rate,
            pattern,
            target_bpm=120.0,
            fade_in_ms=0.0,
            fade_out_ms=0.0,
        )

        self.assertAlmostEqual(preview.segments[0].preview_start_s, 0.125, places=3)
        self.assertLessEqual(preview.segments[0].source_end_s - preview.segments[0].source_start_s, 0.123)

    def test_generated_pattern_preview_renders_exponential_snare_retriggers(self) -> None:
        sample_rate = 1000
        audio = np.zeros(200, dtype=np.float32)
        audio[0:80] = np.linspace(0.0, 1.0, 80, dtype=np.float32)
        source_hit = TransientHit(1, 0.0, 0.08, "snare", 0.9, -2.0, 0.1, 0.7, 0.2)
        retriggers = _test_stretch_retriggers(
            source_hit,
            start_step=5,
            offsets=(0, 72, 116, 142, 158, 168, 175, 180),
            velocities=(100.0, 92.0, 84.0, 76.0, 68.0, 60.0, 52.0, 44.0),
        )
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=5,
                source_start_s=0.0,
                source_end_s=0.08,
                label="snare",
                velocity=100,
                source_hit_index=1,
                tags=(
                    "backbeat",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch",
                    "snare_stretch_zone",
                    "snare_stretch_zone_start",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(
            audio,
            sample_rate,
            pattern,
            target_bpm=120.0,
            fade_in_ms=0.0,
            fade_out_ms=0.0,
        )

        self.assertEqual(len(preview.segments), len(retriggers))
        self.assertTrue(all(segment.stem == "stretch" for segment in preview.segments))
        self.assertAlmostEqual(preview.segments[0].preview_start_s, 0.5, places=3)
        self.assertAlmostEqual(preview.segments[1].preview_start_s, 0.59, places=2)
        self.assertTrue(any((segment.preview_end_s - segment.preview_start_s) < 0.07 for segment in preview.segments[1:]))
        self.assertGreater(preview.segments[-1].preview_start_s, preview.segments[0].preview_start_s)
        self.assertGreater(preview.audio.shape[0], 650)

    def test_snare_stretch_preview_uses_only_retrigger_schedule_inside_zone(self) -> None:
        sample_rate = 1000
        audio = np.zeros(300, dtype=np.float32)
        audio[0:80] = np.linspace(0.0, 1.0, 80, dtype=np.float32)
        audio[100:130] = 0.7
        source_hit = TransientHit(1, 0.0, 0.08, "snare", 0.9, -2.0, 0.1, 0.7, 0.2)
        retriggers = _test_stretch_retriggers(
            source_hit,
            start_step=5,
            offsets=(0, 72, 116, 142, 158, 168, 175, 180),
            velocities=(100.0, 96.0, 88.0, 80.0, 72.0, 64.0, 56.0, 48.0),
        )
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=5,
                source_start_s=0.0,
                source_end_s=0.08,
                label="snare",
                velocity=100,
                source_hit_index=1,
                tags=(
                    "backbeat",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch",
                    "snare_stretch_zone",
                    "snare_stretch_zone_start",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
            mock.Mock(
                step_index=6,
                source_start_s=None,
                source_end_s=None,
                label="silence",
                velocity=0,
                source_hit_index=None,
                tags=(
                    "subdivision",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch_tail",
                    "snare_stretch_zone",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 16
        pattern.params = BreakPatternParams(gate=1.0)

        preview = build_pattern_preview(
            audio,
            sample_rate,
            pattern,
            target_bpm=120.0,
            fade_in_ms=0.0,
            fade_out_ms=0.0,
        )

        self.assertEqual(len(preview.segments), len(retriggers))
        self.assertAlmostEqual(preview.segments[0].preview_start_s, 0.5, places=3)
        self.assertTrue(all(segment.stem == "stretch" for segment in preview.segments))
        self.assertFalse(any(segment.label == "closed_hat" for segment in preview.segments))
        self.assertTrue(any(segment.step_index == 6 for segment in preview.segments))

    def test_pattern_preview_locator_tracks_silence_steps_without_jumping_to_start(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 1000
        audio = np.zeros(500, dtype=np.float32)
        audio[0:80] = 1.0
        audio[220:300] = 0.8
        pattern = mock.Mock()
        pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.08,
                label="kick",
                velocity=96,
                source_hit_index=1,
            ),
            mock.Mock(
                step_index=2,
                source_start_s=None,
                source_end_s=None,
                label="silence",
                velocity=0,
                source_hit_index=None,
            ),
            mock.Mock(
                step_index=3,
                source_start_s=0.22,
                source_end_s=0.30,
                label="snare",
                velocity=92,
                source_hit_index=2,
            ),
        )
        pattern.swing = 0.0
        pattern.step_count = 4

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._retimed_preview = preview

            row, source_position = window._locate_retimed_preview_source_position(0.18)

            self.assertEqual(row, 1)
            self.assertIsNone(source_position)
            window.close()

    def test_loop_mode_uses_continuous_stream_and_wraps_elapsed_position(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        fake_sounddevice = _FakeSounddevice()
        preview_audio = np.linspace(-0.25, 0.25, 120, dtype=np.float32)
        preview = RetimedPreview(
            audio=preview_audio,
            loop_audio=preview_audio[:100],
            sample_rate=1000,
            source_bpm=85.0,
            target_bpm=170.0,
            speed_ratio=0.5,
            duration_s=0.12,
            loop_duration_s=0.1,
            segment_count=1,
            segments=(
                RetimedPreviewSegment(
                    index=1,
                    source_start_s=0.0,
                    source_end_s=0.12,
                    preview_start_s=0.0,
                    preview_end_s=0.12,
                    label="kick",
                ),
            ),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            mock.patch.object(drum_ui, "_require_sounddevice", return_value=fake_sounddevice),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.retime_loop_button.setChecked(True)
            window._start_retimed_preview_playback(preview, sounddevice=fake_sounddevice)

            self.assertTrue(window._retimed_preview_playing)
            self.assertEqual(len(fake_sounddevice.streams), 1)
            self.assertIs(window._retime_stream, fake_sounddevice.streams[0])
            self.assertEqual(fake_sounddevice.streams[0].blocksize, 0)
            self.assertEqual(fake_sounddevice.streams[0].latency, "high")
            self.assertFalse(window._retime_stop_timer.isActive())
            self.assertTrue(window._retime_visual_timer.isActive())
            self.assertIn("boucle", window.retime_info_label.text().lower())
            self.assertTrue(window._retime_stream_loop_enabled)

            window._retime_stream_frames_played = 245
            window._retime_stream_total_frames = 120
            self.assertAlmostEqual(window._elapsed_preview_seconds(), 0.045, places=3)

            window._stop_retimed_preview(update_status=False)
            self.assertFalse(fake_sounddevice.streams[0].active)
            self.assertTrue(fake_sounddevice.streams[0].closed)
            window.close()

    def test_manual_hit_relabel_updates_result_and_clears_generated_pattern(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = result
            window._generated_pattern = object()
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])
            window._populate_result(result)
            window._populate_hits(result)

            window._on_hit_label_changed(2, "snare")

            self.assertEqual(window._result.transient_hits[1].label, "snare")
            self.assertIsNone(window._generated_pattern)
            self.assertIn('"label": "snare"', window.json_view.toPlainText())
            self.assertIn("snare:1", window.hits_summary_label.text())
            picker = window.hits_table.cellWidget(1, 2)
            checked = [radio for radio in picker.findChildren(QRadioButton) if radio.isChecked()]
            self.assertEqual(len(checked), 1)
            self.assertEqual(checked[0].property("hitLabel"), "snare")
            window.close()

    def test_manual_hit_relabel_rebuilds_sequences_after_label_change(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "clap", 0.8, -4.0, 0.1, 0.6, 0.3, role="pillar"),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
            hit_sequences=(
                HitSequence(
                    index=1,
                    role="groove",
                    hit_count=2,
                    total_steps=5,
                    source_start_s=0.0,
                    source_end_s=0.33,
                    start_step_hint=1,
                    end_step_hint=5,
                    labels=("kick", "clap"),
                    events=(
                        HitSequenceEvent(1, 1, "kick", "pillar", 0, 0, 1.0, 0.0, 0.08),
                        HitSequenceEvent(2, 2, "clap", "pillar", 4, 4, 0.9, 0.25, 0.33),
                    ),
                ),
            ),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = result
            window._generated_pattern = object()
            window._on_hit_label_changed(2, "snare")

            self.assertEqual(window._result.transient_hits[1].label, "snare")
            self.assertTrue(window._result.hit_sequences)
            self.assertFalse(
                any("clap" in sequence.labels for sequence in window._result.hit_sequences)
            )
            self.assertFalse(
                any(event.label == "clap" for sequence in window._result.hit_sequences for event in sequence.events)
            )
            self.assertTrue(
                any(event.label == "snare" for sequence in window._result.hit_sequences for event in sequence.events)
            )
            window.close()

    def test_hit_pool_toggle_excludes_hit_from_generator_and_resets_pattern(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = result
            window._generated_pattern = object()
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])
            window._populate_result(result)
            window._populate_hits(result)

            toggle_widget = window.hits_table.cellWidget(1, 1)
            checkbox = toggle_widget.findChild(QCheckBox)
            self.assertIsNotNone(checkbox)
            checkbox.setChecked(False)

            self.assertFalse(window._result.transient_hits[1].generator_enabled)
            self.assertIsNone(window._generated_pattern)
            self.assertIn('"generator_enabled": false', window.json_view.toPlainText())
            self.assertIn("mute", window.hits_summary_label.text().lower())
            window.close()

    def test_pattern_update_during_generator_playback_keeps_transport_running(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        old_pattern = generate_break_pattern(hits, BreakPatternParams(seed=12))
        new_pattern = generate_break_pattern(hits, BreakPatternParams(seed=34))

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = old_pattern
            window._retimed_preview = RetimedPreview(
                audio=np.zeros(100, dtype=np.float32),
                loop_audio=np.zeros(100, dtype=np.float32),
                sample_rate=1000,
                source_bpm=120.0,
                target_bpm=120.0,
                speed_ratio=1.0,
                duration_s=0.1,
                loop_duration_s=0.1,
                segment_count=1,
                segments=(
                    RetimedPreviewSegment(
                        index=1,
                        source_start_s=0.0,
                        source_end_s=0.1,
                        preview_start_s=0.0,
                        preview_end_s=0.1,
                        label="kick",
                        step_index=1,
                    ),
                ),
                mode=PREVIEW_MODE_PATTERN,
            )
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_GENERATOR

            window._on_pattern_generated(new_pattern)

            self.assertTrue(window._retimed_preview_playing)
            self.assertTrue(window._generator_live_changes_pending)
            self.assertEqual(window._generated_pattern.seed, 34)
            self.assertIn("ancienne version", window.generator_info_label.text())
            window.close()

    def test_pattern_update_during_generator_playback_starts_live_refresh_when_audio_is_available(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
        )
        old_pattern = generate_break_pattern(hits, BreakPatternParams(seed=12))
        new_pattern = generate_break_pattern(hits, BreakPatternParams(seed=56))

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = old_pattern
            window._loaded_audio_samples = np.zeros(400, dtype=np.float32)
            window._loaded_audio_sample_rate = 1000
            window._retimed_preview = RetimedPreview(
                audio=np.zeros(100, dtype=np.float32),
                loop_audio=np.zeros(100, dtype=np.float32),
                sample_rate=1000,
                source_bpm=120.0,
                target_bpm=120.0,
                speed_ratio=1.0,
                duration_s=0.1,
                loop_duration_s=0.1,
                segment_count=1,
                segments=(
                    RetimedPreviewSegment(
                        index=1,
                        source_start_s=0.0,
                        source_end_s=0.1,
                        preview_start_s=0.0,
                        preview_end_s=0.1,
                        label="kick",
                        step_index=1,
                    ),
                ),
                mode=PREVIEW_MODE_PATTERN,
            )
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_GENERATOR

            with mock.patch.object(window, "_start_preview_build") as start_preview_build:
                window._on_pattern_generated(new_pattern)

            start_preview_build.assert_called_once()
            self.assertTrue(window._generator_live_changes_pending)
            window.close()

    def test_locked_steps_are_preserved_when_pattern_is_regenerated(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        params_old = BreakPatternParams(seed=12)
        params_new = BreakPatternParams(seed=34)
        old_pattern = GeneratedBreakPattern(
            bars=1,
            step_count=4,
            seed=12,
            swing=0.0,
            params=params_old,
            event_count=3,
            summary="kick:1, snare:1, closed_hat:1",
            steps=(
                GeneratedPatternStep(1, "kick", 96, 1, "kick", 0.0, 0.08, ("pillar",)),
                GeneratedPatternStep(2, "snare", 90, 2, "snare", 0.25, 0.33, ("pillar",)),
                GeneratedPatternStep(3, "closed_hat", 64, 3, "closed_hat", 0.125, 0.19, ("texture",)),
                GeneratedPatternStep(4, "silence", 0, None, None, None, None, ()),
            ),
        )
        new_pattern = GeneratedBreakPattern(
            bars=1,
            step_count=4,
            seed=34,
            swing=0.0,
            params=params_new,
            event_count=3,
            summary="kick:1, clap:1, open_hat:1",
            steps=(
                GeneratedPatternStep(1, "kick", 94, 1, "kick", 0.0, 0.08, ("pillar",)),
                GeneratedPatternStep(2, "clap", 86, 4, "clap", 0.5, 0.58, ("pillar",)),
                GeneratedPatternStep(3, "open_hat", 70, 5, "open_hat", 0.6, 0.75, ("accent",)),
                GeneratedPatternStep(4, "silence", 0, None, None, None, None, ()),
            ),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generator_locked_steps = {2}

            merged = window._merge_locked_generated_steps(new_pattern, old_pattern)
            merged_ignored = window._merge_locked_generated_steps(new_pattern, old_pattern, ignore_step=2)

            self.assertEqual(merged.steps[1].label, "snare")
            self.assertEqual(merged.steps[2].label, "open_hat")
            self.assertEqual(merged.summary, "kick:1, snare:1, open_hat:1")
            self.assertEqual(merged_ignored.steps[1].label, "clap")
            window.close()

    def test_preview_build_success_hot_swaps_active_generator_stream(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 1000
        audio = np.zeros(600, dtype=np.float32)
        audio[0:80] = 1.0
        audio[220:300] = 0.8
        old_pattern = mock.Mock()
        old_pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.0,
                source_end_s=0.08,
                label="kick",
                velocity=96,
                source_hit_index=1,
            ),
            mock.Mock(
                step_index=2,
                source_start_s=0.22,
                source_end_s=0.30,
                label="snare",
                velocity=88,
                source_hit_index=2,
            ),
        )
        old_pattern.swing = 0.0
        old_pattern.step_count = 4
        old_pattern.bars = 1
        old_pattern.event_count = 2
        old_pattern.seed = 11
        new_pattern = mock.Mock()
        new_pattern.steps = (
            mock.Mock(
                step_index=1,
                source_start_s=0.22,
                source_end_s=0.30,
                label="snare",
                velocity=88,
                source_hit_index=2,
            ),
            mock.Mock(
                step_index=2,
                source_start_s=None,
                source_end_s=None,
                label="silence",
                velocity=0,
                source_hit_index=None,
            ),
        )
        new_pattern.swing = 0.0
        new_pattern.step_count = 4
        new_pattern.bars = 1
        new_pattern.event_count = 1
        new_pattern.seed = 22

        old_preview = build_pattern_preview(audio, sample_rate, old_pattern, target_bpm=120.0)
        new_preview = build_pattern_preview(audio, sample_rate, new_pattern, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            fake_stream = _FakeActiveStream()
            window.generator_loop_button.setChecked(True)
            window._retimed_preview = old_preview
            window._generated_pattern = new_pattern
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_GENERATOR
            window._retime_stream = fake_stream
            window._retime_stream_audio = window._normalize_preview_audio(old_preview.loop_audio)
            window._retime_stream_total_frames = int(window._retime_stream_audio.shape[0])
            window._retime_stream_frames_played = 150
            window._retime_stream_cursor = 150
            window._generator_live_changes_pending = True

            window._on_preview_build_success(drum_ui.PREVIEW_OWNER_GENERATOR, new_preview)

            self.assertIs(window._retimed_preview, new_preview)
            self.assertIs(window._retime_stream, fake_stream)
            self.assertEqual(fake_stream.stop_calls, 0)
            self.assertEqual(fake_stream.close_calls, 0)
            self.assertTrue(window._retimed_preview_playing)
            self.assertGreater(window._retime_stream_total_frames, 0)
            self.assertFalse(window._generator_live_changes_pending)
            self.assertEqual(window._preview_owner, drum_ui.PREVIEW_OWNER_GENERATOR)
            window.close()

    def test_target_bpm_change_during_retime_playback_keeps_transport_running(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = result
            window._retimed_preview = RetimedPreview(
                audio=np.zeros(100, dtype=np.float32),
                loop_audio=np.zeros(100, dtype=np.float32),
                sample_rate=1000,
                source_bpm=168.0,
                target_bpm=168.0,
                speed_ratio=1.0,
                duration_s=0.1,
                loop_duration_s=0.1,
                segment_count=2,
                segments=(
                    RetimedPreviewSegment(
                        index=1,
                        source_start_s=0.0,
                        source_end_s=0.05,
                        preview_start_s=0.0,
                        preview_end_s=0.05,
                        label="kick",
                        step_index=1,
                    ),
                    RetimedPreviewSegment(
                        index=2,
                        source_start_s=0.05,
                        source_end_s=0.1,
                        preview_start_s=0.05,
                        preview_end_s=0.1,
                        label="snare",
                        step_index=2,
                    ),
                ),
                mode=PREVIEW_MODE_QUANTIZE,
            )
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_RETIME

            window.target_bpm_spin.setValue(176.0)

            self.assertTrue(window._retimed_preview_playing)
            self.assertTrue(window._retime_live_changes_pending)
            self.assertIn("ancienne version", window.retime_info_label.text())
            window.close()

    def test_generator_target_bpm_change_keeps_transport_running(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
        )
        pattern = generate_break_pattern(hits, BreakPatternParams(seed=12))

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = pattern
            window._retimed_preview = RetimedPreview(
                audio=np.zeros(100, dtype=np.float32),
                loop_audio=np.zeros(100, dtype=np.float32),
                sample_rate=1000,
                source_bpm=120.0,
                target_bpm=120.0,
                speed_ratio=1.0,
                duration_s=0.1,
                loop_duration_s=0.1,
                segment_count=1,
                segments=(
                    RetimedPreviewSegment(
                        index=1,
                        source_start_s=0.0,
                        source_end_s=0.1,
                        preview_start_s=0.0,
                        preview_end_s=0.1,
                        label="kick",
                        step_index=1,
                    ),
                ),
                mode=PREVIEW_MODE_PATTERN,
            )
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_GENERATOR

            window.generator_target_bpm_spin.setValue(140.0)

            self.assertTrue(window._retimed_preview_playing)
            self.assertTrue(window._generator_live_changes_pending)
            self.assertIn("ancienne version", window.generator_info_label.text())
            window.close()

    def test_focus_hit_row_recenters_waveform_without_touching_page_scroll(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            fake_waveform = _FakeWaveformWidget([1.0, 4.5, 8.0], duration=10.0, visible_range=(0.0, 2.0))
            window._waveform_widget = fake_waveform
            ensure_visible = mock.Mock()
            window.page_scroll.ensureWidgetVisible = ensure_visible

            window._focus_hit_row(1, autoplay=False)

            self.assertEqual(fake_waveform.clicked_payloads, [{"time": 4.5}])
            self.assertEqual(fake_waveform.plot.last_range, (3.5, 5.5, 0))
            ensure_visible.assert_not_called()
            self.assertEqual(fake_waveform.play_calls, 0)
            window.close()

    def test_simple_click_on_hit_row_starts_waveform_playback(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            fake_waveform = _FakeWaveformWidget([1.0, 4.5, 8.0], duration=10.0, visible_range=(0.0, 2.0))
            window._waveform_widget = fake_waveform
            window.hits_table.setRowCount(1)
            item = QTableWidgetItem("1")
            window.hits_table.setItem(0, 0, item)

            window._on_hit_clicked(item)

            self.assertEqual(fake_waveform.clicked_payloads, [{"time": 1.0}])
            self.assertEqual(fake_waveform.play_calls, 1)
            window.close()

    def test_generator_step_header_click_plays_source_slice(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.33, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )
        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=hits,
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )
        pattern = generate_break_pattern(hits, BreakPatternParams(seed=12))
        target_column = next(
            index for index, step in enumerate(pattern.steps) if step.label != "silence" and step.source_hit_index == 2
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = result
            window._generated_pattern = pattern
            window._waveform_widget = _FakeWaveformWidget([0.0, 0.25], duration=1.0, visible_range=(0.0, 0.5))
            window._populate_generated_pattern(pattern)

            window._on_generator_sequence_header_clicked(target_column)

            self.assertEqual(window.generator_table.item(target_column, 3).text(), "2")
            self.assertEqual(window._waveform_widget.clicked_payloads, [{"time": 0.25}])
            self.assertEqual(window._waveform_widget.play_calls, 1)
            window.close()

    def test_saved_markers_restore_for_same_audio_file(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        sample_path = handle.name
        try:
            with (
                mock.patch.object(drum_ui, "QSettings", _FakeSettings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            ):
                window = drum_ui.DrumDetectorWindow()
                window.path_input.setText(sample_path)
                window._loaded_audio_path = sample_path
                window._loaded_audio_samples = np.zeros(128, dtype=np.float32)
                window._loaded_audio_sample_rate = 1000
                window._waveform_widget = _FakeWaveformWidget([0.12, 0.36], duration=1.0, visible_range=(0.0, 1.0))

                self.assertTrue(window._persist_marker_times_for_path(sample_path, window._current_marker_times()))

                window._waveform_widget = _FakeWaveformWidget([], duration=1.0, visible_range=(0.0, 1.0))
                self.assertTrue(window._restore_persisted_markers_for_path(sample_path))
                self.assertEqual([round(value, 2) for value in window._waveform_widget.markers], [0.12, 0.36])
                self.assertTrue(window._marker_rebuild_available())
                window.close()
        finally:
            try:
                os.unlink(sample_path)
            except OSError:
                pass

    def test_saved_hit_labels_restore_for_same_audio_file(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        sample_path = handle.name
        try:
            result = DrumDetectionResult(
                source_path=sample_path,
                label="break",
                form="loop",
                family="drum",
                confidence=0.82,
                loop_score=0.77,
                drum_score=0.91,
                break_score=0.66,
                duration_s=1.2,
                sample_rate=44100,
                tempo_bpm=168.0,
                pulse_score=0.73,
                regularity=0.61,
                onset_count=2,
                onset_density=1.6,
                percussive_ratio=0.88,
                harmonic_ratio=0.12,
                decay_s=0.18,
                spectral_centroid_hz=2400.0,
                spectral_flatness=0.41,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=(
                    TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                    TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7, generator_enabled=False),
                ),
                candidates=(DrumCandidate("break", 0.82, "demo"),),
            )

            with (
                mock.patch.object(drum_ui, "QSettings", _FakeSettings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            ):
                window = drum_ui.DrumDetectorWindow()
                self.assertTrue(window._persist_hit_labels_for_result(result))

                rebuilt = DrumDetectionResult(
                    **{
                        **result.__dict__,
                        "transient_hits": (
                            TransientHit(1, 0.002, 0.081, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                            TransientHit(2, 0.252, 0.331, "snare", 0.8, -4.0, 0.1, 0.2, 0.7),
                        ),
                    }
                )

                restored = window._apply_persisted_hit_labels(rebuilt)

                self.assertEqual(restored.transient_hits[0].label, "kick")
                self.assertEqual(restored.transient_hits[1].label, "closed_hat")
                self.assertFalse(restored.transient_hits[1].generator_enabled)
                window.close()
        finally:
            try:
                os.unlink(sample_path)
            except OSError:
                pass

    def test_effective_generator_result_filters_muted_hits_and_sequences(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "snare", 0.8, -4.0, 0.1, 0.2, 0.7, generator_enabled=False),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
            hit_sequences=(
                HitSequence(
                    index=1,
                    role="groove",
                    hit_count=2,
                    total_steps=5,
                    source_start_s=0.0,
                    source_end_s=0.33,
                    start_step_hint=1,
                    end_step_hint=5,
                    labels=("kick", "snare"),
                    events=(
                        HitSequenceEvent(1, 1, "kick", "pillar", 0, 0, 1.0, 0.0, 0.08),
                        HitSequenceEvent(2, 2, "snare", "pillar", 4, 4, 0.9, 0.25, 0.33),
                    ),
                ),
            ),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            filtered = window._effective_generator_result(result)

            self.assertIsNotNone(filtered)
            self.assertEqual(len(filtered.transient_hits), 1)
            self.assertEqual(filtered.transient_hits[0].label, "kick")
            self.assertEqual(filtered.hit_sequences, ())
            window.close()

    def test_saved_hit_analysis_restores_automatically_when_waveform_loads(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        sample_path = handle.name
        shared_settings = _FakeSettings()
        try:
            result = DrumDetectionResult(
                source_path=sample_path,
                label="break",
                form="loop",
                family="drum",
                confidence=0.82,
                loop_score=0.77,
                drum_score=0.91,
                break_score=0.66,
                duration_s=1.2,
                sample_rate=44100,
                tempo_bpm=168.0,
                pulse_score=0.73,
                regularity=0.61,
                onset_count=2,
                onset_density=1.6,
                percussive_ratio=0.88,
                harmonic_ratio=0.12,
                decay_s=0.18,
                spectral_centroid_hz=2400.0,
                spectral_flatness=0.41,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=(
                    TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1, role="pillar"),
                    TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7, role="texture"),
                ),
                candidates=(DrumCandidate("break", 0.82, "demo"),),
            )

            with (
                mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            ):
                saver = drum_ui.DrumDetectorWindow()
                self.assertTrue(saver._persist_detection_result(result))
                saver.close()

                window = drum_ui.DrumDetectorWindow()
                window._waveform_widget = _FakeWaveformWidget([], duration=1.0, visible_range=(0.0, 1.0))
                load_result = drum_ui.WaveformLoadResult(
                    path=sample_path,
                    samples=np.zeros(128, dtype=np.float32),
                    waveform_data=np.zeros(128, dtype=np.float32),
                    sample_rate=44100,
                    duration_s=1.2,
                )

                window._on_waveform_loaded(load_result, window._waveform_load_token)

                self.assertIsNotNone(window._result)
                self.assertEqual([hit.label for hit in window._result.transient_hits], ["kick", "closed_hat"])
                self.assertEqual(window.hits_table.rowCount(), 2)
                self.assertEqual(window._waveform_widget.markers, [0.0, 0.25])
                self.assertIn("analyse et les labels", window.waveform_status_label.text().lower())
                window.close()
        finally:
            try:
                os.unlink(sample_path)
            except OSError:
                pass

    def test_saved_hit_analysis_is_skipped_when_restored_markers_diverge(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        sample_path = handle.name
        shared_settings = _FakeSettings()
        try:
            result = DrumDetectionResult(
                source_path=sample_path,
                label="break",
                form="loop",
                family="drum",
                confidence=0.82,
                loop_score=0.77,
                drum_score=0.91,
                break_score=0.66,
                duration_s=1.2,
                sample_rate=44100,
                tempo_bpm=168.0,
                pulse_score=0.73,
                regularity=0.61,
                onset_count=2,
                onset_density=1.6,
                percussive_ratio=0.88,
                harmonic_ratio=0.12,
                decay_s=0.18,
                spectral_centroid_hz=2400.0,
                spectral_flatness=0.41,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=(
                    TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                    TransientHit(2, 0.25, 0.33, "snare", 0.8, -4.0, 0.1, 0.2, 0.7),
                ),
                candidates=(DrumCandidate("break", 0.82, "demo"),),
            )

            with (
                mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            ):
                saver = drum_ui.DrumDetectorWindow()
                self.assertTrue(saver._persist_detection_result(result))
                self.assertTrue(saver._persist_marker_times_for_path(sample_path, [0.0, 0.4]))
                saver.close()

                window = drum_ui.DrumDetectorWindow()
                window._waveform_widget = _FakeWaveformWidget([], duration=1.0, visible_range=(0.0, 1.0))
                load_result = drum_ui.WaveformLoadResult(
                    path=sample_path,
                    samples=np.zeros(128, dtype=np.float32),
                    waveform_data=np.zeros(128, dtype=np.float32),
                    sample_rate=44100,
                    duration_s=1.2,
                )

                window._on_waveform_loaded(load_result, window._waveform_load_token)

                self.assertIsNone(window._result)
                self.assertEqual(window.hits_table.rowCount(), 0)
                self.assertEqual(window._waveform_widget.markers, [0.0, 0.4])
                self.assertIn("markers sauvegardes", window.waveform_status_label.text().lower())
                window.close()
        finally:
            try:
                os.unlink(sample_path)
            except OSError:
                pass

    def test_recent_files_restore_across_windows(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle_a = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle_b = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle_a.close()
        handle_b.close()
        sample_a = str(Path(handle_a.name).resolve())
        sample_b = str(Path(handle_b.name).resolve())
        shared_settings = _FakeSettings()
        try:
            with (
                mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_sync_waveform_path", autospec=True) as sync_waveform,
            ):
                first = drum_ui.DrumDetectorWindow()
                first._handle_path_selected(sample_a)
                first._handle_path_selected(sample_b)

                self.assertEqual(first.recent_files_combo.itemData(1), sample_b)
                self.assertEqual(first.recent_files_combo.itemData(2), sample_a)
                first.close()

                restored = drum_ui.DrumDetectorWindow()

                self.assertEqual(restored.path_input.text(), sample_b)
                self.assertEqual(restored.recent_files_combo.itemData(1), sample_b)
                self.assertEqual(restored.recent_files_combo.itemData(2), sample_a)
                self.assertEqual(restored.recent_files_combo.currentData(), sample_b)
                sync_waveform.assert_any_call(restored, sample_b)
                restored.close()
        finally:
            for path in (sample_a, sample_b):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def test_selecting_recent_file_moves_it_to_top(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        handle_a = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle_b = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle_a.close()
        handle_b.close()
        sample_a = str(Path(handle_a.name).resolve())
        sample_b = str(Path(handle_b.name).resolve())
        shared_settings = _FakeSettings()
        try:
            with (
                mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                mock.patch.object(drum_ui.DrumDetectorWindow, "_sync_waveform_path", autospec=True),
            ):
                window = drum_ui.DrumDetectorWindow()
                window._handle_path_selected(sample_a)
                window._handle_path_selected(sample_b)

                window._on_recent_file_selected(2)

                self.assertEqual(window.path_input.text(), sample_a)
                self.assertEqual(window.recent_files_combo.itemData(1), sample_a)
                self.assertEqual(window.recent_files_combo.itemData(2), sample_b)
                self.assertEqual(window.recent_files_combo.currentData(), sample_a)
                window.close()
        finally:
            for path in (sample_a, sample_b):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def test_hybrid_mode_persists_user_motifs_per_project_json(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                ):
                    first = drum_ui.DrumDetectorWindow()
                    self.assertTrue(first.generator_motif_editor_box.isHidden())

                    hybrid_index = first.generator_mode_combo.findData(drum_ui.GENERATOR_MODE_HYBRID)
                    self.assertGreaterEqual(hybrid_index, 0)
                    first.generator_mode_combo.setCurrentIndex(hybrid_index)
                    self.assertFalse(first.generator_motif_editor_box.isHidden())
                    self.assertFalse(first.generator_saved_motifs_box.isHidden())

                    first.generator_motif_name_input.setText("KickSnare")
                    first.generator_motif_base_prob_slider.setValue(80)
                    first._on_generator_motif_editor_step_clicked(0)
                    first._on_generator_motif_editor_step_clicked(2)
                    first._on_generator_motif_editor_step_clicked(2)
                    first._save_generator_user_motif()

                    storage_path = Path(temp_dir) / drum_ui.USER_MOTIF_PROJECT_FILE
                    self.assertTrue(storage_path.exists())
                    payload = json.loads(storage_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(payload["user_motifs"]), 1)
                    self.assertEqual(payload["user_motifs"][0]["steps"][:4], ["kick", None, "snare", None])
                    first.close()

                    restored = drum_ui.DrumDetectorWindow()
                    self.assertEqual(restored._generator_mode(), drum_ui.GENERATOR_MODE_HYBRID)
                    self.assertFalse(restored.generator_motif_editor_box.isHidden())
                    self.assertEqual(len(restored._generator_user_motifs), 1)
                    self.assertEqual(restored._generator_user_motifs[0].name, "KickSnare")
                    self.assertEqual(restored._generator_user_motifs[0].steps[:4], ["kick", None, "snare", None])
                    self.assertEqual(restored.generator_saved_motifs_table.rowCount(), 1)
                    restored.generator_motif_density_slider.setValue(100)
                    previous_effective = restored.generator_saved_motifs_table.item(0, 5).text()
                    probability_widget = restored.generator_saved_motifs_table.cellWidget(0, 4)
                    self.assertIsNotNone(probability_widget)
                    saved_slider = probability_widget.findChild(QSlider)
                    self.assertIsNotNone(saved_slider)
                    saved_slider.setValue(25)

                    payload = json.loads(storage_path.read_text(encoding="utf-8"))
                    self.assertAlmostEqual(float(payload["user_motifs"][0]["base_prob"]), 0.25, places=6)
                    self.assertAlmostEqual(restored._generator_user_motifs[0].base_prob, 0.25, places=6)
                    self.assertEqual(restored.generator_saved_motifs_table.rowCount(), 1)
                    self.assertNotEqual(restored.generator_saved_motifs_table.item(0, 5).text(), previous_effective)
                    restored.close()
            finally:
                os.chdir(previous_cwd)

    def test_saved_break_snapshot_persists_and_restores_exact_generation(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                ):
                    first = drum_ui.DrumDetectorWindow()
                    first._result = _test_detection_result()
                    first._generated_pattern = _test_generated_pattern(seed=246, gate=0.72, mono_choke=True)
                    first.generator_target_bpm_spin.setValue(137.5)
                    first._generator_step_anchors[1] = "kick"
                    first._generator_locked_steps.add(5)
                    first._refresh_control_states(first.status_label.text())

                    first.generator_save_snapshot_button.click()

                    storage_path = Path(temp_dir) / drum_ui.SAVED_PATTERN_PROJECT_FILE
                    self.assertTrue(storage_path.exists())
                    payload = json.loads(storage_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(payload["saved_patterns"]), 1)
                    self.assertEqual(payload["saved_patterns"][0]["pattern_payload"]["seed"], 246)
                    first.close()

                    restored = drum_ui.DrumDetectorWindow()
                    self.assertEqual(restored.saved_patterns_table.rowCount(), 1)
                    restored.saved_patterns_table.selectRow(0)

                    restored._open_selected_saved_pattern()

                    self.assertIsNotNone(restored._generated_pattern)
                    self.assertEqual(restored._generated_pattern.seed, 246)
                    self.assertAlmostEqual(restored.generator_target_bpm_spin.value(), 137.5, places=1)
                    self.assertTrue(restored.generator_mono_choke_check.isChecked())
                    self.assertEqual(restored._generator_step_anchors.get(1), "kick")
                    self.assertIn(5, restored._generator_locked_steps)
                    self.assertIsNotNone(restored._result)
                    self.assertEqual(restored._result.label, "break")
                    self.assertEqual(
                        restored._current_main_tab_key(),
                        drum_ui.MAIN_TAB_GENERATOR,
                    )
                    restored.close()
            finally:
                os.chdir(previous_cwd)

    def test_live_slot_star_saves_snapshot_in_saved_tab(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                ):
                    window = drum_ui.DrumDetectorWindow()
                    pattern = _test_generated_pattern(seed=777, gate=0.9, mono_choke=False)
                    window._result = _test_detection_result()
                    window._live_slots["A"] = drum_ui.PatternSlot(
                        pattern=pattern,
                        params=pattern.params,
                        seed=pattern.seed,
                        mode=drum_ui.GENERATOR_MODE_CLASSIC,
                        status="ready",
                    )
                    window._refresh_control_states(window.status_label.text())

                    window.live_slot_save_buttons["A"].click()

                    self.assertEqual(window.saved_patterns_table.rowCount(), 1)
                    payload = json.loads((Path(temp_dir) / drum_ui.SAVED_PATTERN_PROJECT_FILE).read_text(encoding="utf-8"))
                    self.assertEqual(payload["saved_patterns"][0]["origin"], "live:A")
                    window.close()
            finally:
                os.chdir(previous_cwd)

    def test_render_generated_pattern_writes_exact_loop_length(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                sample_rate = 16000
                samples = np.zeros((sample_rate, 1), dtype=np.float32)
                samples[:2000, 0] = 0.4
                sample_path = Path(temp_dir) / "source.wav"
                output_path = Path(temp_dir) / "render.wav"
                soundfile = drum_ui._require_soundfile()
                soundfile.write(str(sample_path), samples, sample_rate, subtype="PCM_16")

                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                    mock.patch.object(
                        drum_ui.QFileDialog,
                        "getSaveFileName",
                        return_value=(str(output_path), "Wave files (*.wav)"),
                    ),
                ):
                    window = drum_ui.DrumDetectorWindow()
                    pattern = _test_generated_pattern(seed=909, gate=1.0, mono_choke=False)
                    window._result = _test_detection_result(source_path=str(sample_path))
                    window._generated_pattern = pattern
                    window._loaded_audio_samples = np.array(samples, dtype=np.float32, copy=True)
                    window._loaded_audio_sample_rate = sample_rate
                    window._loaded_audio_path = str(sample_path)
                    window.generator_target_bpm_spin.setValue(120.0)
                    window.generator_gate_slider.setValue(100)
                    window.generator_mono_choke_check.setChecked(False)
                    window._refresh_control_states(window.status_label.text())

                    window.generator_render_wav_button.click()

                    self.assertTrue(output_path.exists())
                    rendered_audio, rendered_sr = soundfile.read(str(output_path), dtype="float32", always_2d=True)
                    expected_preview = build_pattern_preview(
                        samples,
                        sample_rate,
                        pattern,
                        target_bpm=120.0,
                        gate=1.0,
                        mono_choke=False,
                    )
                    expected_loop = window._normalize_preview_audio(expected_preview.loop_audio)
                    self.assertEqual(int(rendered_sr), sample_rate)
                    self.assertEqual(rendered_audio.shape[0], expected_loop.shape[0])
                    self.assertEqual(rendered_audio.shape[1], expected_loop.shape[1])
                    window.close()
            finally:
                os.chdir(previous_cwd)

    def test_render_generated_pattern_remembers_last_export_directory(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                sample_rate = 16000
                samples = np.zeros((sample_rate, 1), dtype=np.float32)
                samples[:2000, 0] = 0.35
                sample_path = Path(temp_dir) / "source.wav"
                export_dir = Path(temp_dir) / "exports" / "favorite"
                first_output_path = export_dir / "render_one.wav"
                second_output_path = export_dir / "render_two.wav"
                soundfile = drum_ui._require_soundfile()
                soundfile.write(str(sample_path), samples, sample_rate, subtype="PCM_16")

                dialog_default_paths: list[str] = []
                chosen_paths = [str(first_output_path), str(second_output_path)]

                def _fake_get_save_file_name(*args, **kwargs):
                    dialog_default_paths.append(str(args[2]))
                    return (chosen_paths[len(dialog_default_paths) - 1], "Wave files (*.wav)")

                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                    mock.patch.object(drum_ui.QFileDialog, "getSaveFileName", side_effect=_fake_get_save_file_name),
                ):
                    window = drum_ui.DrumDetectorWindow()
                    pattern = _test_generated_pattern(seed=515, gate=1.0, mono_choke=False)
                    window._result = _test_detection_result(source_path=str(sample_path))
                    window._generated_pattern = pattern
                    window._loaded_audio_samples = np.array(samples, dtype=np.float32, copy=True)
                    window._loaded_audio_sample_rate = sample_rate
                    window._loaded_audio_path = str(sample_path)
                    window.generator_target_bpm_spin.setValue(120.0)
                    window.generator_gate_slider.setValue(100)
                    window._refresh_control_states(window.status_label.text())

                    window.generator_render_wav_button.click()
                    remembered_dir = shared_settings.value(drum_ui.RENDER_WAV_LAST_DIR_SETTINGS_KEY)
                    self.assertEqual(remembered_dir, str(export_dir))

                    window.generator_render_wav_button.click()
                    self.assertGreaterEqual(len(dialog_default_paths), 2)
                    self.assertEqual(Path(dialog_default_paths[1]).parent, export_dir)
                    window.close()
            finally:
                os.chdir(previous_cwd)

    def test_live_quick_render_exports_active_slot_to_last_render_directory(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                sample_rate = 16000
                samples = np.zeros((sample_rate, 1), dtype=np.float32)
                samples[:2000, 0] = 0.3
                sample_path = Path(temp_dir) / "source.wav"
                export_dir = Path(temp_dir) / "exports" / "live"
                soundfile = drum_ui._require_soundfile()
                soundfile.write(str(sample_path), samples, sample_rate, subtype="PCM_16")
                shared_settings.setValue(drum_ui.RENDER_WAV_LAST_DIR_SETTINGS_KEY, str(export_dir))

                with (
                    mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
                    mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
                ):
                    window = drum_ui.DrumDetectorWindow()
                    pattern = _test_generated_pattern(seed=1201, gate=1.0, mono_choke=False)
                    window._result = _test_detection_result(source_path=str(sample_path))
                    window._loaded_audio_samples = np.array(samples, dtype=np.float32, copy=True)
                    window._loaded_audio_sample_rate = sample_rate
                    window._loaded_audio_path = str(sample_path)
                    window._live_mode_enabled = True
                    window._live_slots["A"] = drum_ui.PatternSlot(
                        pattern=pattern,
                        params=pattern.params,
                        seed=pattern.seed,
                        mode=drum_ui.GENERATOR_MODE_CLASSIC,
                        status="ready",
                    )
                    window._refresh_control_states(window.status_label.text())

                    self.assertTrue(window.live_quick_render_button.isEnabled())
                    window.live_quick_render_button.click()

                    exported = sorted(export_dir.glob("*.wav"))
                    self.assertEqual(len(exported), 1)
                    self.assertIn("live_slot_A", exported[0].stem)
                    self.assertIn("exporte", window.live_mode_info_label.text())
                    window.close()
            finally:
                os.chdir(previous_cwd)

    def test_waveform_shortcuts_follow_samplerod_playback_scheme(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        class _LoopButton:
            def __init__(self) -> None:
                self.toggle_calls = 0

            def toggle(self) -> None:
                self.toggle_calls += 1

        class _ShortcutWaveform:
            def __init__(self) -> None:
                self.play_calls = 0
                self.pause_calls = 0
                self.stop_calls = 0
                self.marker_mode = False
                self.marker_toggle_values: list[bool] = []
                self.loop_button = _LoopButton()

            def _on_cut_shortcut(self) -> None:
                return

            def undo(self) -> None:
                return

            def redo(self) -> None:
                return

            def play_from_start(self) -> None:
                self.play_calls += 1

            def pause_or_resume(self) -> None:
                self.pause_calls += 1

            def stop_and_reset(self) -> None:
                self.stop_calls += 1

            def toggle_marker_mode(self, checked: bool) -> None:
                self.marker_mode = bool(checked)
                self.marker_toggle_values.append(bool(checked))

            def _on_export_shortcut(self) -> None:
                return

            def add_markers_to_region(self) -> None:
                return

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            waveform = _ShortcutWaveform()
            window._waveform_widget = waveform

            shortcuts = {shortcut.key().toString(): shortcut for shortcut in window._waveform_shortcuts}
            shortcuts["Ctrl+Space"].activated.emit()
            shortcuts["Space"].activated.emit()
            shortcuts["Alt+Space"].activated.emit()
            shortcuts["Ctrl+L"].activated.emit()
            shortcuts["Ctrl+G"].activated.emit()

            self.assertEqual(waveform.play_calls, 1)
            self.assertEqual(waveform.pause_calls, 1)
            self.assertEqual(waveform.stop_calls, 1)
            self.assertEqual(waveform.loop_button.toggle_calls, 1)
            self.assertEqual(waveform.marker_toggle_values, [True])
            window.close()

    def test_waveform_shortcuts_remain_available_in_live_mode_when_waveform_has_focus(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        class _LoopButton:
            def toggle(self) -> None:
                return

        class _ShortcutWaveform:
            def __init__(self) -> None:
                self.pause_calls = 0
                self.loop_button = _LoopButton()
                self.marker_mode = False

            def _on_cut_shortcut(self) -> None:
                return

            def undo(self) -> None:
                return

            def redo(self) -> None:
                return

            def play_from_start(self) -> None:
                return

            def pause_or_resume(self) -> None:
                self.pause_calls += 1

            def stop_and_reset(self) -> None:
                return

            def toggle_marker_mode(self, checked: bool) -> None:
                self.marker_mode = bool(checked)

            def _on_export_shortcut(self) -> None:
                return

            def add_markers_to_region(self) -> None:
                return

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            waveform = _ShortcutWaveform()
            window._waveform_widget = waveform
            window.generator_live_mode_button.setChecked(True)

            shortcuts = {shortcut.key().toString(): shortcut for shortcut in window._waveform_shortcuts}
            self.assertTrue(shortcuts["Space"].isEnabled())
            with mock.patch.object(window, "_waveform_focus_active", return_value=True):
                shortcuts["Space"].activated.emit()

            self.assertEqual(waveform.pause_calls, 1)
            window.close()

    def test_waveform_playback_buttons_call_samplerod_widget(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        class _LoopButton:
            def __init__(self) -> None:
                self.checked = False

            def isChecked(self) -> bool:
                return self.checked

            def setChecked(self, checked: bool) -> None:
                self.checked = bool(checked)

        class _PlaybackWaveform:
            def __init__(self) -> None:
                self.play_calls = 0
                self.pause_calls = 0
                self.stop_calls = 0
                self.loop_calls: list[bool] = []
                self.loop_button = _LoopButton()

            def play_from_start(self) -> None:
                self.play_calls += 1

            def pause_or_resume(self) -> None:
                self.pause_calls += 1

            def stop_and_reset(self) -> None:
                self.stop_calls += 1

            def toggle_loop(self, checked: bool) -> None:
                self.loop_calls.append(bool(checked))

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            waveform = _PlaybackWaveform()
            window._waveform_widget = waveform
            window._sync_waveform_playback_controls()

            window.waveform_play_button.click()
            window.waveform_pause_button.click()
            window.waveform_stop_button.click()
            window.waveform_loop_toggle_button.setChecked(True)

            self.assertEqual(waveform.play_calls, 1)
            self.assertEqual(waveform.pause_calls, 1)
            self.assertEqual(waveform.stop_calls, 1)
            self.assertEqual(waveform.loop_button.checked, True)
            window.close()

    def test_generated_sequence_highlights_bar_starts_and_strong_beats(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_bars_spin.setValue(2)
            window._populate_generated_sequence(None)

            bar_header = window.generator_sequence_table.horizontalHeaderItem(0)
            beat_header = window.generator_sequence_table.horizontalHeaderItem(4)
            subdivision_header = window.generator_sequence_table.horizontalHeaderItem(1)

            self.assertEqual(bar_header.background().color().name(), "#382c19")
            self.assertEqual(beat_header.background().color().name(), "#21343c")
            self.assertEqual(subdivision_header.background().color().name(), "#101318")

            bar_button = window.generator_sequence_table.cellWidget(6, 0)
            beat_button = window.generator_sequence_table.cellWidget(6, 4)
            self.assertEqual(bar_button.property("generatorStepRole"), "bar_start")
            self.assertEqual(beat_button.property("generatorStepRole"), "beat")
            window.close()

    def test_generated_sequence_marks_repeat_zone_boundaries_in_header(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        steps = tuple(
            GeneratedPatternStep(
                step_index=index,
                label="closed_hat" if index in {2, 3, 4} else "silence",
                velocity=72 if index in {2, 3, 4} else 0,
                source_hit_index=1 if index in {2, 3, 4} else None,
                source_label="closed_hat" if index in {2, 3, 4} else None,
                source_start_s=0.1 if index in {2, 3, 4} else None,
                source_end_s=0.18 if index in {2, 3, 4} else None,
                tags=(
                    ("subdivision", "repeat", "repeat_glitch", "repeat_count_4", "repeat_zone", "repeat_zone_span_3", "repeat_zone_start")
                    if index == 2
                    else ("offbeat", "repeat", "repeat_glitch", "repeat_count_4", "repeat_zone", "repeat_zone_span_3")
                    if index == 3
                    else ("subdivision", "repeat", "repeat_glitch", "repeat_count_4", "repeat_zone", "repeat_zone_span_3", "repeat_zone_end")
                    if index == 4
                    else ("subdivision",)
                ),
            )
            for index in range(1, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=123,
            swing=0.0,
            params=BreakPatternParams(),
            event_count=3,
            summary="closed_hat:3",
            steps=steps,
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = pattern
            window._populate_generated_pattern(pattern)

            self.assertEqual(window.generator_sequence_table.horizontalHeaderItem(1).text(), "[2")
            self.assertEqual(window.generator_sequence_table.horizontalHeaderItem(2).text(), "3")
            self.assertEqual(window.generator_sequence_table.horizontalHeaderItem(3).text(), "4]")
            self.assertIn("Debut repeat", window.generator_sequence_table.horizontalHeaderItem(1).toolTip())
            self.assertIn("Fin repeat", window.generator_sequence_table.horizontalHeaderItem(3).toolTip())
            self.assertEqual(window.generator_sequence_table.item(5, 1).text(), "Rpt x4")
            window.close()

    def test_generated_sequence_fx_row_displays_reverse_tail_and_effect_probabilities(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        steps = (
            GeneratedPatternStep(
                step_index=1,
                label="kick",
                velocity=96,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("strong",),
            ),
            GeneratedPatternStep(
                step_index=2,
                label="kick",
                velocity=64,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("subdivision", "reverse", "effect", "effect_reverse", "reverse_transition", "reverse_from_kick"),
            ),
        ) + tuple(
            GeneratedPatternStep(
                step_index=index,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            )
            for index in range(3, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=123,
            swing=0.0,
            params=BreakPatternParams(reverse_density=1.0),
            event_count=2,
            summary="kick:2",
            steps=steps,
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = DrumDetectionResult(
                source_path="demo.wav",
                label="break",
                form="loop",
                family="drum",
                confidence=0.8,
                loop_score=0.7,
                drum_score=0.9,
                break_score=0.7,
                duration_s=1.0,
                sample_rate=44100,
                tempo_bpm=170.0,
                pulse_score=0.7,
                regularity=0.6,
                onset_count=3,
                onset_density=3.0,
                percussive_ratio=0.9,
                harmonic_ratio=0.1,
                decay_s=0.15,
                spectral_centroid_hz=2000.0,
                spectral_flatness=0.4,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=hits,
                candidates=(DrumCandidate("break", 0.8, "demo"),),
            )
            window._generated_pattern = pattern
            window._populate_generated_pattern(pattern)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])
            window._refresh_generator_probability_preview()

            self.assertEqual(window.generator_sequence_table.rowCount(), 7)
            self.assertEqual(window.generator_sequence_table.verticalHeaderItem(5).text(), "FX")
            self.assertEqual(window.generator_sequence_table.item(5, 1).text(), "Rev<-K")
            self.assertIn("reverse tail", window.generator_sequence_table.item(5, 1).toolTip().lower())
            self.assertEqual(window.generator_effect_probability_table.columnCount(), 5)
            self.assertEqual(window.generator_effect_probability_table.item(3, 1).text()[-1], "%")
            self.assertEqual(window.generator_effect_probability_table.item(3, 2).text()[-1], "%")
            self.assertEqual(window.generator_effect_probability_table.item(1, 3).text()[-1], "%")
            self.assertEqual(window.generator_effect_probability_table.horizontalHeaderItem(4).text(), "Pitch")
            self.assertEqual(window.generator_effect_probability_table.item(1, 4).text()[-1], "%")
            window.close()

    def test_generator_uses_effective_detected_bpm_to_requantize_sequences(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.09, 0.15, "kick", 0.9, -3.0, 0.8, 0.15, 0.05),
            TransientHit(2, 0.34, 0.39, "closed_hat", 0.82, -8.0, 0.05, 0.3, 0.65),
            TransientHit(3, 0.59, 0.68, "snare", 0.88, -4.0, 0.15, 0.65, 0.2),
        )
        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.8,
            loop_score=0.7,
            drum_score=0.9,
            break_score=0.7,
            duration_s=1.0,
            sample_rate=44100,
            tempo_bpm=120.0,
            pulse_score=0.7,
            regularity=0.95,
            onset_count=3,
            onset_density=3.0,
            percussive_ratio=0.9,
            harmonic_ratio=0.1,
            decay_s=0.15,
            spectral_centroid_hz=2000.0,
            spectral_flatness=0.4,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=hits,
            candidates=(DrumCandidate("break", 0.8, "demo"),),
            hit_sequences=(),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._set_detected_bpm_factor(2.0)

            adjusted = window._effective_generator_result(result)

            self.assertIsNotNone(adjusted)
            self.assertEqual(round(adjusted.tempo_bpm), 240)
            self.assertEqual(
                [hit.rhythmic_position for hit in adjusted.transient_hits],
                ["downbeat", "backbeat", "downbeat"],
            )
            matching_sequences = [
                sequence
                for sequence in adjusted.hit_sequences
                if sequence.hit_count == 3
                and sequence.start_step_hint == 1
                and sequence.end_step_hint == 9
                and [event.start_offset_steps for event in sequence.events] == [0, 4, 8]
            ]
            self.assertTrue(matching_sequences)
            window.close()

    def test_generated_sequence_fx_row_displays_kick_roll_zone(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.1, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.33, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
        )
        steps = (
            GeneratedPatternStep(
                step_index=1,
                label="kick",
                velocity=104,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.1,
                tags=("strong",),
            ),
            GeneratedPatternStep(
                step_index=2,
                label="kick",
                velocity=92,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.1,
                tags=("subdivision", "effect", "effect_kick_roll", "kick_roll", "kick_roll_zone", "kick_roll_zone_span_4", "kick_roll_zone_start", "kick_roll_hi"),
                relative_velocity_ratio=1.0,
            ),
            GeneratedPatternStep(
                step_index=3,
                label="kick",
                velocity=54,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.1,
                tags=("offbeat", "effect", "effect_kick_roll", "kick_roll", "kick_roll_zone", "kick_roll_zone_span_4", "kick_roll_lo"),
                relative_velocity_ratio=0.38,
            ),
            GeneratedPatternStep(
                step_index=4,
                label="kick",
                velocity=88,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.1,
                tags=("subdivision", "effect", "effect_kick_roll", "kick_roll", "kick_roll_zone", "kick_roll_zone_span_4", "kick_roll_zone_end", "kick_roll_hi"),
                relative_velocity_ratio=0.94,
            ),
        ) + tuple(
            GeneratedPatternStep(
                step_index=index,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            )
            for index in range(5, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=222,
            swing=0.0,
            params=BreakPatternParams(kick_roll_density=1.0),
            event_count=4,
            summary="kick:4",
            steps=steps,
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = DrumDetectionResult(
                source_path="demo.wav",
                label="break",
                form="loop",
                family="drum",
                confidence=0.8,
                loop_score=0.7,
                drum_score=0.9,
                break_score=0.7,
                duration_s=1.0,
                sample_rate=44100,
                tempo_bpm=170.0,
                pulse_score=0.7,
                regularity=0.6,
                onset_count=2,
                onset_density=2.0,
                percussive_ratio=0.9,
                harmonic_ratio=0.1,
                decay_s=0.15,
                spectral_centroid_hz=2000.0,
                spectral_flatness=0.4,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=hits,
                candidates=(DrumCandidate("break", 0.8, "demo"),),
            )
            window._generated_pattern = pattern
            window._populate_generated_pattern(pattern)

            self.assertEqual(window.generator_sequence_table.item(5, 1).text(), "KRoll 4")
            self.assertIn("kick roll", window.generator_sequence_table.item(5, 1).toolTip().lower())
            self.assertIn("Debut kick roll", window.generator_sequence_table.horizontalHeaderItem(1).toolTip())
            window.close()

    def test_generated_sequence_fx_row_displays_snare_stretch(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        source_hit = TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2)
        retriggers = _test_stretch_retriggers(
            source_hit,
            start_step=5,
            offsets=(0, 72, 116, 142, 158, 168, 175, 180),
            velocities=(94.0, 90.0, 84.0, 78.0, 70.0, 62.0, 54.0, 46.0),
        )
        steps = (
            GeneratedPatternStep(
                step_index=1,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("strong",),
            ),
            GeneratedPatternStep(
                step_index=2,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            ),
            GeneratedPatternStep(
                step_index=3,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("offbeat",),
            ),
            GeneratedPatternStep(
                step_index=4,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            ),
            GeneratedPatternStep(
                step_index=5,
                label="snare",
                velocity=94,
                source_hit_index=2,
                source_label="snare",
                source_start_s=0.25,
                source_end_s=0.37,
                tags=(
                    "backbeat",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch",
                    "snare_stretch_zone",
                    "snare_stretch_zone_start",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
            GeneratedPatternStep(
                step_index=6,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=(
                    "subdivision",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch_tail",
                    "snare_stretch_zone",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
            GeneratedPatternStep(
                step_index=7,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=(
                    "offbeat",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch_tail",
                    "snare_stretch_zone",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
            GeneratedPatternStep(
                step_index=8,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=(
                    "subdivision",
                    "effect",
                    "effect_snare_stretch",
                    "snare_stretch_tail",
                    "snare_stretch_zone",
                    "snare_stretch_zone_end",
                    "snare_stretch_zone_span_4",
                    "snare_stretch_amount_100",
                    "snare_stretch_curve_decay",
                ),
                stretch_retriggers=retriggers,
            ),
        ) + tuple(
            GeneratedPatternStep(
                step_index=index,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            )
            for index in range(9, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=444,
            swing=0.0,
            params=BreakPatternParams(snare_stretch_density=1.0),
            event_count=1,
            summary="snare:1",
            steps=steps,
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = pattern
            window._populate_generated_pattern(pattern)

            self.assertIn(".", window.generator_sequence_table.item(5, 4).text())
            self.assertTrue(
                any(token in window.generator_sequence_table.item(5, 5).text() for token in (".", "~"))
            )
            self.assertIn("retrigger expo", window.generator_sequence_table.item(5, 4).toolTip().lower())
            self.assertIn("retrigger expo", window.generator_sequence_table.item(5, 5).toolTip().lower())
            self.assertIn("retrigger expo", window.generator_sequence_table.horizontalHeaderItem(4).toolTip().lower())
            window.close()

    def test_generated_sequence_fx_row_displays_pitch_shift(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        steps = (
            GeneratedPatternStep(
                step_index=1,
                label="snare",
                velocity=96,
                source_hit_index=1,
                source_label="snare",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("downbeat",),
                pitch_shift=3.0,
            ),
        ) + tuple(
            GeneratedPatternStep(
                step_index=index,
                label="silence",
                velocity=0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("subdivision",),
            )
            for index in range(2, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=555,
            swing=0.0,
            params=BreakPatternParams(pitch_mode="sequence", pitch_amount=1.0),
            event_count=1,
            summary="snare:1",
            steps=steps,
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generated_pattern = pattern
            window._populate_generated_pattern(pattern)

            self.assertEqual(window.generator_sequence_table.item(5, 0).text(), "Pch +3")
            self.assertIn("pitch shift +3.0", window.generator_sequence_table.item(5, 0).toolTip().lower())
            self.assertIn("pch +3", window.generator_sequence_table.horizontalHeaderItem(0).toolTip().lower())
            window.close()

    def test_generator_effect_probability_table_shows_pitch_when_enabled(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.375, 0.46, "clap", 0.81, -3.0, 0.1, 0.55, 0.35),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._result = DrumDetectionResult(
                source_path="demo.wav",
                label="break",
                form="loop",
                family="drum",
                confidence=0.8,
                loop_score=0.7,
                drum_score=0.9,
                break_score=0.7,
                duration_s=1.0,
                sample_rate=44100,
                tempo_bpm=170.0,
                pulse_score=0.7,
                regularity=0.6,
                onset_count=3,
                onset_density=3.0,
                percussive_ratio=0.9,
                harmonic_ratio=0.1,
                decay_s=0.15,
                spectral_centroid_hz=2000.0,
                spectral_flatness=0.4,
                band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
                transient_hits=hits,
                candidates=(DrumCandidate("break", 0.8, "demo"),),
            )
            window.generator_pitch_mode_combo.setCurrentIndex(window.generator_pitch_mode_combo.findData("random"))
            window.generator_pitch_scope_combo.setCurrentIndex(window.generator_pitch_scope_combo.findData("snare+clap"))
            window.generator_pitch_amount_slider.setValue(100)
            window.generator_pitch_range_min_slider.setValue(-7)
            window.generator_pitch_range_max_slider.setValue(7)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])
            window._refresh_generator_probability_preview()

            self.assertEqual(window.generator_effect_probability_table.columnCount(), 5)
            self.assertEqual(window.generator_effect_probability_table.horizontalHeaderItem(4).text(), "Pitch")
            self.assertGreater(int(window.generator_effect_probability_table.item(1, 4).text().removesuffix("%")), 0)
            window.close()

    def test_generator_ghost_synthesis_box_visibility_tracks_ghost_density(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_ghost_slider.setValue(0)
            window._refresh_generator_ghost_ui()
            self.assertTrue(window.generator_ghost_synthesis_box.isHidden())

            window.generator_ghost_slider.setValue(30)
            window._refresh_generator_ghost_ui()
            self.assertFalse(window.generator_ghost_synthesis_box.isHidden())

            window.generator_synth_ghost_enabled_check.setChecked(False)
            window._refresh_generator_ghost_ui()
            self.assertFalse(window.generator_ghost_vel_min_slider.isEnabled())
            window.close()

    def test_generator_params_include_ghost_synthesis_controls(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_ghost_slider.setValue(40)
            window.generator_synth_ghost_enabled_check.setChecked(True)
            window.generator_ghost_vel_min_slider.setValue(18)
            window.generator_ghost_vel_max_slider.setValue(42)
            window.generator_ghost_pitch_min_slider.setValue(-5)
            window.generator_ghost_pitch_max_slider.setValue(8)
            window.generator_ghost_gate_slider.setValue(35)

            params = window._generator_params(seed=123)

            self.assertTrue(params.synth_ghost_enabled)
            self.assertEqual(params.ghost_vel_range, (0.18, 0.42))
            self.assertEqual(params.ghost_pitch_range, (-0.5, 0.8))
            self.assertAlmostEqual(params.ghost_gate_ratio, 0.35, places=6)
            window.close()

    def test_generator_params_and_retimed_preview_include_mono_choke_toggle(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_mono_choke_check.setChecked(True)

            params = window._generator_params(seed=123)
            self.assertTrue(params.mono_choke)

            audio = np.zeros(600, dtype=np.float32)
            audio[0:300] = 1.0
            audio[250:450] = 0.6
            result = DrumDetectionResult(
                source_path=None,
                label="break",
                form="loop",
                family="drum",
                confidence=0.9,
                loop_score=0.9,
                drum_score=0.9,
                break_score=0.9,
                duration_s=0.6,
                sample_rate=1000,
                tempo_bpm=120.0,
                pulse_score=0.8,
                regularity=0.8,
                onset_count=2,
                onset_density=2.0,
                percussive_ratio=0.9,
                harmonic_ratio=0.1,
                decay_s=0.2,
                spectral_centroid_hz=2000.0,
                spectral_flatness=0.2,
                band_energies={"low": 0.5, "mid": 0.3, "high": 0.2},
                transient_hits=(
                    TransientHit(1, 0.0, 0.3, "kick", 0.9, -1.0, 0.9, 0.1, 0.0),
                    TransientHit(2, 0.25, 0.45, "snare", 0.8, -2.0, 0.1, 0.7, 0.2),
                ),
                candidates=(),
            )

            preview = window._build_preview_for_current_settings(result, audio, 1000)
            self.assertTrue(preview.mono_choke)
            self.assertAlmostEqual(preview.segments[0].preview_end_s, 0.25, places=3)
            window.close()

    def test_generator_creative_sliders_persist_across_window_reopen(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        shared_settings = _FakeSettings()
        with (
            mock.patch.object(drum_ui, "QSettings", lambda *_args, **_kwargs: shared_settings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            first = drum_ui.DrumDetectorWindow()
            first.generator_energy_slider.setValue(83)
            first.generator_kick_slider.setValue(12)
            first.generator_snare_slider.setValue(67)
            first.generator_hat_slider.setValue(41)
            first.generator_ghost_slider.setValue(22)
            first.generator_fill_slider.setValue(74)
            first.generator_velocity_slider.setValue(58)
            first.generator_swing_slider.setValue(19)
            first.generator_anti_repeat_slider.setValue(91)
            first.generator_breath_slider.setValue(27)
            first.close()

            restored = drum_ui.DrumDetectorWindow()
            self.assertEqual(restored.generator_energy_slider.value(), 83)
            self.assertEqual(restored.generator_kick_slider.value(), 12)
            self.assertEqual(restored.generator_snare_slider.value(), 67)
            self.assertEqual(restored.generator_hat_slider.value(), 41)
            self.assertEqual(restored.generator_ghost_slider.value(), 22)
            self.assertEqual(restored.generator_fill_slider.value(), 74)
            self.assertEqual(restored.generator_velocity_slider.value(), 58)
            self.assertEqual(restored.generator_swing_slider.value(), 19)
            self.assertEqual(restored.generator_anti_repeat_slider.value(), 91)
            self.assertEqual(restored.generator_breath_slider.value(), 27)
            restored.close()

    def test_randomize_generator_params_changes_creative_controls_without_touching_transport(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._generator_user_motifs = []
            initial_target_bpm = float(window.generator_target_bpm_spin.value())
            initial_bars = int(window.generator_bars_spin.value())
            initial_mode = str(window.generator_mode_combo.currentData())

            window.generator_energy_slider.setValue(0)
            window.generator_kick_slider.setValue(0)
            window.generator_snare_slider.setValue(0)
            window.generator_pitch_amount_slider.setValue(0)
            window.generator_pitch_sequence_input.setText("0")

            window._randomize_generator_params(rng=np.random.default_rng(123))

            changed_count = sum(
                int(value != 0)
                for value in (
                    window.generator_energy_slider.value(),
                    window.generator_kick_slider.value(),
                    window.generator_snare_slider.value(),
                    window.generator_pitch_amount_slider.value(),
                )
            )
            self.assertGreaterEqual(changed_count, 3)
            self.assertNotEqual(window.generator_pitch_sequence_input.text().strip(), "0")
            self.assertEqual(float(window.generator_target_bpm_spin.value()), initial_target_bpm)
            self.assertEqual(int(window.generator_bars_spin.value()), initial_bars)
            self.assertEqual(str(window.generator_mode_combo.currentData()), initial_mode)
            self.assertEqual(window.status_label.text(), "Parametres du generateur randomises.")
            window.close()

    def test_generator_view_mode_toggles_advanced_panels(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()

            advanced_index = window.generator_view_mode_combo.findData(drum_ui.GENERATOR_VIEW_MODE_ADVANCED)
            basic_index = window.generator_view_mode_combo.findData(drum_ui.GENERATOR_VIEW_MODE_BASIC)
            window.generator_ghost_slider.setValue(35)
            window.generator_view_mode_combo.setCurrentIndex(advanced_index)
            window._refresh_generator_mode_ui()

            self.assertFalse(window.generator_probability_section.isHidden())
            self.assertFalse(window.generator_pitch_box.isHidden())
            self.assertFalse(window.generator_ghost_synthesis_box.isHidden())
            self.assertFalse(window.generator_sequence_max_len_spin.isHidden())

            window.generator_view_mode_combo.setCurrentIndex(basic_index)
            window._refresh_generator_mode_ui()

            self.assertTrue(window.generator_probability_section.isHidden())
            self.assertFalse(window.generator_pitch_box.isHidden())
            self.assertFalse(window.generator_ghost_synthesis_box.isHidden())
            self.assertFalse(window.generator_sequence_max_len_spin.isHidden())
            self.assertFalse(window.generator_sequence_role_lock_check.isHidden())
            window.close()

    def test_live_mode_keeps_pitch_controls_accessible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window._refresh_generator_mode_ui()

            self.assertFalse(window.generator_pitch_box.isHidden())
            self.assertTrue(window.generator_pitch_mode_combo.isEnabled())
            window.close()

    def test_live_mode_keeps_ghost_synthesis_controls_accessible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_ghost_slider.setValue(35)
            window.generator_live_mode_button.setChecked(True)
            window._refresh_generator_mode_ui()

            self.assertFalse(window.generator_ghost_synthesis_box.isHidden())
            self.assertTrue(window.generator_synth_ghost_enabled_check.isEnabled())
            window.close()

    def test_live_mode_keeps_sequence_controls_accessible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            basic_index = window.generator_view_mode_combo.findData(drum_ui.GENERATOR_VIEW_MODE_BASIC)
            window.generator_view_mode_combo.setCurrentIndex(basic_index)
            window.generator_live_mode_button.setChecked(True)
            window._refresh_generator_mode_ui()

            self.assertFalse(window.generator_sequence_max_len_spin.isHidden())
            self.assertFalse(window.generator_sequence_role_lock_check.isHidden())
            self.assertTrue(window.generator_sequence_max_len_spin.isEnabled())
            self.assertTrue(window.generator_sequence_role_lock_check.isEnabled())
            window.close()

    def test_inspector_refresh_is_deferred_until_tab_is_visible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        result = DrumDetectionResult(
            source_path="demo.wav",
            label="break",
            form="loop",
            family="drum",
            confidence=0.82,
            loop_score=0.77,
            drum_score=0.91,
            break_score=0.66,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.73,
            regularity=0.61,
            onset_count=2,
            onset_density=1.6,
            percussive_ratio=0.88,
            harmonic_ratio=0.12,
            decay_s=0.18,
            spectral_centroid_hz=2400.0,
            spectral_flatness=0.41,
            band_energies={"low": 0.4, "mid": 0.35, "high": 0.25},
            transient_hits=(
                TransientHit(1, 0.0, 0.08, "kick", 0.9, -1.0, 0.8, 0.1, 0.1),
                TransientHit(2, 0.25, 0.33, "snare", 0.8, -4.0, 0.1, 0.2, 0.7),
            ),
            candidates=(DrumCandidate("break", 0.82, "demo"),),
        )

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            self.assertEqual(window._current_main_tab_key(), drum_ui.MAIN_TAB_ANALYZE)

            window._result = result
            window._populate_result(result)

            self.assertTrue(window._inspector_tab_refresh_pending)
            self.assertEqual(window.result_label.text(), "Aucun sample charge")

            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])

            self.assertFalse(window._inspector_tab_refresh_pending)
            self.assertEqual(window.result_label.text(), "break")
            self.assertIn('"label": "break"', window.json_view.toPlainText())
            window.close()

    def test_waveform_panel_mount_reuses_pending_loaded_audio_path(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        original_init_waveform_panel = drum_ui.DrumDetectorWindow._init_waveform_panel

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()

        sync_calls: list[str] = []
        with (
            mock.patch.object(drum_ui, "_require_waveform_widget", return_value=_BootWaveformWidget),
            mock.patch.object(window, "_sync_waveform_path", side_effect=lambda path: sync_calls.append(str(path))),
            mock.patch.object(drum_ui.QTimer, "singleShot", side_effect=lambda _delay, callback: callback()),
        ):
            window._loaded_audio_path = "C:/tmp/demo.wav"
            window._waveform_loading = False
            original_init_waveform_panel(window)

        self.assertIsNotNone(window._waveform_widget)
        self.assertEqual(sync_calls, ["C:/tmp/demo.wav"])
        self.assertTrue(window.waveform_placeholder.isHidden())
        self.assertIn("Synchronisation du sample", window.waveform_status_label.text())
        window.close()

    def test_waveform_panel_bootstrap_failure_keeps_ui_alive(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        original_init_waveform_panel = drum_ui.DrumDetectorWindow._init_waveform_panel

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()

        with mock.patch.object(drum_ui, "_require_waveform_widget", side_effect=RuntimeError("boom")):
            original_init_waveform_panel(window)
        self.assertIsNone(window._waveform_widget)
        self.assertIn("boom", window.waveform_status_label.text())
        self.assertIn("boom", window.waveform_placeholder.text())
        window.close()

    def test_process_pool_is_disabled_by_default_on_windows(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(drum_ui.sys, "platform", "win32"),
        ):
            self.assertFalse(drum_ui._process_pool_allowed())

    def test_process_pool_can_be_reenabled_explicitly(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.dict(os.environ, {"SAMPLEROD_ENABLE_PROCESS_POOL": "1"}, clear=True),
            mock.patch.object(drum_ui.sys, "platform", "win32"),
        ):
            self.assertTrue(drum_ui._process_pool_allowed())

    def test_generator_display_presets_expand_expected_sections(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()

            inspector_index = window.generator_display_preset_combo.findData(
                drum_ui.GENERATOR_DISPLAY_PRESET_INSPECTOR
            )
            performance_index = window.generator_display_preset_combo.findData(
                drum_ui.GENERATOR_DISPLAY_PRESET_PERFORMANCE
            )

            window.generator_display_preset_combo.setCurrentIndex(inspector_index)
            self.assertTrue(window.generator_probability_section.isExpanded())
            self.assertTrue(window.generator_pattern_details_section.isExpanded())
            self.assertTrue(window.candidates_section.isExpanded())
            self.assertTrue(window.json_section.isExpanded())

            window.generator_display_preset_combo.setCurrentIndex(performance_index)
            self.assertFalse(window.generator_probability_section.isExpanded())
            self.assertFalse(window.generator_pattern_details_section.isExpanded())
            self.assertFalse(window.candidates_section.isExpanded())
            self.assertFalse(window.json_section.isExpanded())
            window.close()

    def test_generator_probability_preview_waits_for_slider_release(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            with mock.patch.object(window, "_refresh_generator_probability_preview_now") as refresh_now:
                window.generator_energy_slider.sliderPressed.emit()
                window._flush_generator_probability_preview_refresh()

                refresh_now.assert_not_called()
                self.assertTrue(window._generator_probability_refresh_pending)

                window.generator_energy_slider.sliderReleased.emit()

                refresh_now.assert_called_once()
            window.close()

    def test_generator_gate_live_refresh_waits_for_slider_release(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_GENERATOR

            with (
                mock.patch.object(window, "_schedule_live_generator_preview_refresh") as schedule_refresh,
                mock.patch.object(window, "_refresh_generated_pattern_state") as refresh_state,
            ):
                window.generator_gate_slider.sliderPressed.emit()
                window._on_generator_gate_changed(70)

                schedule_refresh.assert_not_called()
                refresh_state.assert_not_called()
                self.assertTrue(window._generator_gate_preview_pending)

                window.generator_gate_slider.sliderReleased.emit()

                schedule_refresh.assert_called_once()
                refresh_state.assert_called_once()
                self.assertFalse(window._generator_gate_preview_pending)
            window.close()

    def test_split_waveform_equally_replaces_markers_with_even_grid(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
            mock.patch.object(drum_ui.QInputDialog, "getInt", return_value=(4, True)),
        ):
            window = drum_ui.DrumDetectorWindow()
            fake_waveform = _FakeWaveformWidget([1.0, 3.0], duration=8.0, visible_range=(0.0, 2.0))
            window._waveform_widget = fake_waveform

            window._split_waveform_equally()

            self.assertEqual(fake_waveform.markers, [2.0, 4.0, 6.0])
            self.assertEqual(fake_waveform.marker_list.count(), 3)
            self.assertEqual(window.status_label.text(), "Split sample applique: 4 slices regulieres sur 8.00s.")
            self.assertIn("Markers redistribues", window.waveform_status_label.text())
            window.close()

    def test_pattern_preview_builds_separate_stems_and_segment_stem_metadata(self) -> None:
        sample_rate = 100
        audio = np.zeros(80, dtype=np.float32)
        audio[0:12] = 0.7
        audio[18:28] = -0.5
        steps = (
            GeneratedPatternStep(
                step_index=1,
                label="kick",
                velocity=96,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("downbeat",),
            ),
            GeneratedPatternStep(
                step_index=2,
                label="snare",
                velocity=72,
                source_hit_index=2,
                source_label="snare",
                source_start_s=0.18,
                source_end_s=0.28,
                tags=("backbeat", "reverse", "reverse_from_snare"),
            ),
        ) + tuple(
            GeneratedPatternStep(index, "silence", 0, None, None, None, None, ())
            for index in range(3, 17)
        )
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=11,
            swing=0.0,
            params=BreakPatternParams(),
            event_count=2,
            summary="kick:1,snare:1",
            steps=steps,
        )

        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        self.assertEqual(set(preview.stems.keys()), set(PATTERN_STEM_NAMES))
        self.assertEqual(set(preview.loop_stems.keys()), set(PATTERN_STEM_NAMES))
        self.assertEqual(preview.segments[0].stem, "kick")
        self.assertEqual(preview.segments[1].stem, "reverse")
        stem_sum = np.sum(np.stack([preview.stems[name] for name in PATTERN_STEM_NAMES], axis=0), axis=0)
        np.testing.assert_allclose(stem_sum, preview.audio, atol=1e-6)

    def test_tabbed_layout_keeps_live_generator_and_inspector_controls_accessible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            self.assertIsNotNone(window.main_tabs)
            self.assertEqual(window.main_tabs.count(), 5)

            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])
            window.generator_live_section.setExpanded(True)
            self.assertTrue(window.generator_live_section.isVisibleTo(window))
            self.assertTrue(window.generator_live_box.isVisibleTo(window))

            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_GENERATOR])
            self.assertTrue(window.generator_sequence_table.isVisibleTo(window))

            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_INSPECTOR])
            self.assertTrue(window.generator_probability_section.isVisibleTo(window))
            self.assertTrue(window.generator_pattern_details_section.isVisibleTo(window))
            self.assertTrue(window.results_panel.isVisibleTo(window))
            window.close()

    def test_analyze_tab_hosts_source_controls_and_larger_transient_area(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_ANALYZE])

            self.assertTrue(window.analyze_source_box.isVisibleTo(window))
            self.assertTrue(window.waveform_box.isVisibleTo(window))
            self.assertIsNotNone(window.waveform_splitter)
            self.assertGreaterEqual(window.hits_table.minimumHeight(), 320)

            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_GENERATOR])
            self.assertFalse(window.analyze_source_box.isVisibleTo(window))
            window.close()

    def test_main_tabs_use_browser_style_shortcuts_and_ignore_wheel_switching(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            self.assertIsInstance(window.main_tabs.tabBar(), drum_ui.NoWheelTabBar)

            shortcuts = {shortcut.key().toString(): shortcut for shortcut in window._tab_navigation_shortcuts}
            initial_index = window.main_tabs.currentIndex()

            shortcuts["Ctrl+Tab"].activated.emit()
            self.assertEqual(window.main_tabs.currentIndex(), (initial_index + 1) % window.main_tabs.count())

            shortcuts["Ctrl+Shift+Tab"].activated.emit()
            self.assertEqual(window.main_tabs.currentIndex(), initial_index)
            window.close()

    def test_live_mode_can_show_selected_slot_pattern_in_generator_grid(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            pattern_a = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=11,
                swing=0.0,
                params=BreakPatternParams(seed=11),
                event_count=1,
                summary="kick:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else "silence",
                        velocity=90 if index == 1 else 0,
                        source_hit_index=1 if index == 1 else None,
                        source_label="kick" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=0.1 if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            pattern_b = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=22,
                swing=0.0,
                params=BreakPatternParams(seed=22),
                event_count=1,
                summary="snare:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="snare" if index == 1 else "silence",
                        velocity=88 if index == 1 else 0,
                        source_hit_index=2 if index == 1 else None,
                        source_label="snare" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=0.1 if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            window._live_slots["A"].pattern = pattern_a
            window._live_slots["A"].status = "ready"
            window._live_slots["B"].pattern = pattern_b
            window._live_slots["B"].status = "ready"

            window.generator_live_mode_button.setChecked(True)
            window._select_live_view_slot("A")
            self.assertEqual(window.generator_sequence_table.item(2, 0).text(), "Kick")

            window._select_live_view_slot("B")
            self.assertEqual(window.generator_sequence_table.item(2, 0).text(), "Snare")
            self.assertTrue(window.live_slot_view_buttons["B"].isChecked())
            window.close()

    def test_live_slot_boxes_expose_visual_state_properties_for_playing_and_pending(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])
            window._live_slots["A"].status = "ready"
            window._live_slots["B"].status = "ready"
            window._live_active_slot = "A"
            window._live_pending_switch_slot = "B"
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_LIVE

            window._refresh_live_mode_ui_now()

            self.assertEqual(window.live_slot_boxes["A"].property("liveSlotState"), "playing")
            self.assertEqual(window.live_slot_boxes["A"].property("liveSlotPending"), "false")
            self.assertEqual(window.live_slot_boxes["B"].property("liveSlotState"), "ready")
            self.assertEqual(window.live_slot_boxes["B"].property("liveSlotPending"), "true")
            self.assertTrue(window._live_pending_flash_timer.isActive())

            window._live_pending_switch_slot = None
            window._refresh_live_mode_ui_now()
            self.assertFalse(window._live_pending_flash_timer.isActive())
            window.close()

    def test_live_slot_compact_table_shows_bars_and_allows_quick_anchor_lock_edits(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=2,
                step_count=32,
                seed=77,
                swing=0.0,
                params=BreakPatternParams(seed=77, bars=2),
                event_count=2,
                summary="kick:1,snare:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else ("snare" if index == 17 else "silence"),
                        velocity=96 if index in {1, 17} else 0,
                        source_hit_index=index if index in {1, 17} else None,
                        source_label="kick" if index == 1 else ("snare" if index == 17 else None),
                        source_start_s=0.0 if index in {1, 17} else None,
                        source_end_s=0.1 if index in {1, 17} else None,
                        tags=(),
                    )
                    for index in range(1, 33)
                ),
            )
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].params = pattern.params
            window._live_slots["A"].status = "ready"

            window._refresh_live_mode_ui_now()

            table = window.live_slot_pattern_tables["A"]
            self.assertEqual(table.rowCount(), 6)
            self.assertEqual(table.item(0, 0).text(), "K")
            self.assertEqual(table.item(3, 0).text(), "S")
            base_background = table.item(0, 0).background().color().name().lower()
            self.assertEqual(base_background, "#1d3b38")
            self.assertEqual(table.item(3, 0).background().color().name().lower(), "#3b301d")
            self.assertEqual(table.item(1, 0).text(), "·")
            self.assertEqual(table.item(2, 0).text(), "·")

            table.cellClicked.emit(1, 0)
            self.assertEqual(window._generator_anchor_for_step(1), "kick")
            anchored_background = table.item(0, 0).background().color().name().lower()
            self.assertNotEqual(anchored_background, base_background)
            self.assertEqual(table.item(1, 0).text(), "K")

            table.cellClicked.emit(2, 0)
            self.assertTrue(window._generator_step_locked(1))
            locked_background = table.item(0, 0).background().color().name().lower()
            self.assertNotEqual(locked_background, anchored_background)
            self.assertEqual(table.item(2, 0).text(), "L")
            window.close()

    def test_live_slot_compact_table_expands_to_show_four_bars_without_scroll(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=4,
                step_count=64,
                seed=78,
                swing=0.0,
                params=BreakPatternParams(seed=78, bars=4),
                event_count=4,
                summary="kick:2,snare:2",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index in {1, 33} else ("snare" if index in {17, 49} else "silence"),
                        velocity=96 if index in {1, 17, 33, 49} else 0,
                        source_hit_index=index if index in {1, 17, 33, 49} else None,
                        source_label="kick" if index in {1, 33} else ("snare" if index in {17, 49} else None),
                        source_start_s=0.0 if index in {1, 17, 33, 49} else None,
                        source_end_s=0.1 if index in {1, 17, 33, 49} else None,
                        tags=(),
                    )
                    for index in range(1, 65)
                ),
            )
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].params = pattern.params
            window._live_slots["A"].status = "ready"

            window._refresh_live_mode_ui_now()

            table = window.live_slot_pattern_tables["A"]
            self.assertEqual(table.rowCount(), 12)
            self.assertEqual(table.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertGreaterEqual(table.minimumHeight(), 320)
            window.close()

    def test_live_slot_compact_table_highlights_current_playback_step(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=79,
                swing=0.0,
                params=BreakPatternParams(seed=79, bars=1),
                event_count=1,
                summary="kick:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else "silence",
                        velocity=96 if index == 1 else 0,
                        source_hit_index=index if index == 1 else None,
                        source_label="kick" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=0.1 if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].params = pattern.params
            window._live_slots["A"].status = "ready"
            window._refresh_live_mode_ui_now()

            table = window.live_slot_pattern_tables["A"]
            event_base = table.item(0, 0).background().color().name().lower()
            anchor_base = table.item(1, 0).background().color().name().lower()
            lock_base = table.item(2, 0).background().color().name().lower()

            window._set_live_compact_playback_highlight("A", 1)

            self.assertEqual(table.horizontalHeaderItem(0).text(), "▶1")
            self.assertEqual(table.item(0, 0).text(), "▶K")
            self.assertNotEqual(table.item(0, 0).background().color().name().lower(), event_base)
            self.assertNotEqual(table.item(1, 0).background().color().name().lower(), anchor_base)
            self.assertNotEqual(table.item(2, 0).background().color().name().lower(), lock_base)

            window._set_live_compact_playback_highlight(None, None)
            self.assertEqual(table.horizontalHeaderItem(0).text(), "1")
            self.assertEqual(table.item(0, 0).text(), "K")
            self.assertEqual(table.item(0, 0).background().color().name().lower(), event_base)
            window.close()

    def test_live_compact_highlight_tracks_stream_cursor_without_waveform_widget(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=81,
                swing=0.0,
                params=BreakPatternParams(seed=81, bars=1),
                event_count=16,
                summary="kick:16",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick",
                        velocity=100,
                        source_hit_index=index,
                        source_label="kick",
                        source_start_s=0.0,
                        source_end_s=0.1,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            loop_audio = np.zeros((1600, 1), dtype=np.float32)
            preview = RetimedPreview(
                audio=loop_audio,
                loop_audio=loop_audio,
                sample_rate=1600,
                source_bpm=160.0,
                target_bpm=160.0,
                speed_ratio=1.0,
                duration_s=1.0,
                loop_duration_s=1.0,
                segment_count=16,
                segments=(),
                mode=PREVIEW_MODE_PATTERN,
                pattern=pattern,
                loop_stems={"kick": loop_audio},
            )
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].preview = preview
            window._live_slots["A"].params = pattern.params
            window._live_slots["A"].loop_stems = {"kick": loop_audio}
            window._live_slots["A"].status = "playing"
            window._retimed_preview = preview
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_LIVE
            window._retime_stream_total_frames = 1600
            window._retime_stream_cursor = 450
            window._refresh_live_mode_ui_now()

            window._update_retimed_preview_visual()

            table = window.live_slot_pattern_tables["A"]
            self.assertEqual(window._live_compact_highlight_slot, "A")
            self.assertEqual(window._live_compact_highlight_step, 5)
            self.assertEqual(table.horizontalHeaderItem(4).text(), window._live_slot_compact_header_text(5, highlighted=True))
            self.assertEqual(table.item(0, 4).text(), f"{window._live_slot_compact_header_text(1, highlighted=True)[:-1]}K")
            window.close()

    def test_live_preview_row_tracking_skips_generator_table_when_live_tab_visible(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=82,
                swing=0.0,
                params=BreakPatternParams(seed=82, bars=1),
                event_count=2,
                summary="kick:2",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index in {1, 2} else "silence",
                        velocity=96 if index in {1, 2} else 0,
                        source_hit_index=index if index in {1, 2} else None,
                        source_label="kick" if index in {1, 2} else None,
                        source_start_s=0.0 if index in {1, 2} else None,
                        source_end_s=0.1 if index in {1, 2} else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            preview = RetimedPreview(
                audio=np.zeros((1600, 1), dtype=np.float32),
                loop_audio=np.zeros((1600, 1), dtype=np.float32),
                sample_rate=1600,
                source_bpm=160.0,
                target_bpm=160.0,
                speed_ratio=1.0,
                duration_s=1.0,
                loop_duration_s=1.0,
                segment_count=2,
                segments=(),
                mode=PREVIEW_MODE_PATTERN,
                pattern=pattern,
            )
            window._retimed_preview = preview
            window._retimed_preview_playing = True
            window._preview_owner = drum_ui.PREVIEW_OWNER_LIVE
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].params = pattern.params
            window._refresh_live_mode_ui_now()

            window._select_retimed_preview_row(0)

            self.assertEqual(window._live_compact_highlight_step, 1)
            self.assertEqual(window.generator_table.currentRow(), -1)
            self.assertEqual(window.generator_sequence_table.currentColumn(), -1)
            window.close()

    def test_live_mode_ui_skips_compact_table_rebuild_when_signature_is_unchanged(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window.main_tabs.setCurrentWidget(window._main_tab_pages[drum_ui.MAIN_TAB_LIVE])

            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=83,
                swing=0.0,
                params=BreakPatternParams(seed=83, bars=1),
                event_count=1,
                summary="kick:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else "silence",
                        velocity=96 if index == 1 else 0,
                        source_hit_index=index if index == 1 else None,
                        source_label="kick" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=0.1 if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            window._live_slots["A"].pattern = pattern
            window._live_slots["A"].params = pattern.params
            window._live_slots["A"].status = "ready"
            window._refresh_live_mode_ui_now()

            with mock.patch.object(window, "_populate_live_slot_compact_table", wraps=window._populate_live_slot_compact_table) as rebuild_mock:
                window._refresh_live_mode_ui_now()

            self.assertEqual(rebuild_mock.call_count, 0)
            window.close()

    def test_live_slot_ready_uses_prebuilt_group_cache_without_ui_prewarm(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=84,
                swing=0.0,
                params=BreakPatternParams(seed=84, bars=1),
                event_count=1,
                summary="kick:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else "silence",
                        velocity=96 if index == 1 else 0,
                        source_hit_index=index if index == 1 else None,
                        source_label="kick" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=0.1 if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )
            stem_audio = np.ones((64, 1), dtype=np.float32)
            preview = RetimedPreview(
                audio=stem_audio,
                loop_audio=stem_audio,
                sample_rate=1600,
                source_bpm=160.0,
                target_bpm=160.0,
                speed_ratio=1.0,
                duration_s=0.04,
                loop_duration_s=0.04,
                segment_count=1,
                segments=(),
                mode=PREVIEW_MODE_PATTERN,
                pattern=pattern,
                stems={"kick": stem_audio},
                loop_stems={"kick": stem_audio},
            )
            payload = (
                84,
                pattern.params,
                pattern,
                preview,
                {("kick", "snare"): stem_audio},
            )
            window._live_slot_tokens["A"] = 1

            with mock.patch.object(window, "_prewarm_live_group_loop_cache") as prewarm_mock:
                window._on_live_slot_pattern_ready("A", 1, payload)

            self.assertEqual(prewarm_mock.call_count, 0)
            self.assertIn(("kick", "snare"), window._live_slots["A"].group_loop_cache)
            window.close()

    def test_live_audio_shared_buffer_exposes_current_loaded_audio(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            samples = np.linspace(-0.5, 0.5, 64, dtype=np.float32).reshape(-1, 1)
            window._loaded_audio_samples = samples
            window._loaded_audio_sample_rate = 1600

            window._sync_live_audio_shared_buffer()
            spec = window._live_audio_shared_spec()

            self.assertIsNotNone(spec)
            assert spec is not None
            handle, shared_audio = drum_ui._shared_audio_view(spec[0], spec[1])
            try:
                self.assertTrue(np.allclose(shared_audio, samples))
            finally:
                handle.close()
            window.close()

    def test_live_preview_process_task_can_read_shared_audio(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            samples = np.linspace(-0.5, 0.5, 64, dtype=np.float32).reshape(-1, 1)
            window._loaded_audio_samples = samples
            window._loaded_audio_sample_rate = 1600
            window._sync_live_audio_shared_buffer()
            spec = window._live_audio_shared_spec()
            assert spec is not None

            pattern = GeneratedBreakPattern(
                bars=1,
                step_count=16,
                seed=85,
                swing=0.0,
                params=BreakPatternParams(seed=85, bars=1),
                event_count=1,
                summary="kick:1",
                steps=tuple(
                    GeneratedPatternStep(
                        step_index=index,
                        label="kick" if index == 1 else "silence",
                        velocity=96 if index == 1 else 0,
                        source_hit_index=index if index == 1 else None,
                        source_label="kick" if index == 1 else None,
                        source_start_s=0.0 if index == 1 else None,
                        source_end_s=(64.0 / 1600.0) if index == 1 else None,
                        tags=(),
                    )
                    for index in range(1, 17)
                ),
            )

            preview, group_cache = drum_ui._build_live_pattern_preview_process_task(
                None,
                1600,
                pattern,
                target_bpm=160.0,
                gate=1.0,
                grouped_stem_names=(("kick", "snare"),),
                shared_audio_name=spec[0],
                shared_audio_shape=spec[1],
            )

            self.assertGreater(preview.audio.shape[0], 0)
            self.assertIn(("kick", "snare"), group_cache)
            window.close()

    def test_live_mix_plan_groups_stems_with_identical_fx_chain(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window._rebuild_live_mix_plan()

            self.assertEqual(len(window._live_mix_plan.stems), 1)
            self.assertEqual(window._live_mix_plan.stems[0].stem_names, tuple(drum_ui.LIVE_STEM_NAMES))
            window.close()

    def test_live_group_loop_audio_caches_combined_stems(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            slot = drum_ui.PatternSlot(
                loop_stems={
                    "kick": np.ones((8, 1), dtype=np.float32),
                    "snare": np.full((8, 1), 2.0, dtype=np.float32),
                }
            )

            combined_first = window._live_group_loop_audio(slot, ("kick", "snare"))
            combined_second = window._live_group_loop_audio(slot, ("kick", "snare"))

            self.assertIsNotNone(combined_first)
            self.assertIs(combined_first, combined_second)
            np.testing.assert_allclose(combined_first, np.full((8, 1), 3.0, dtype=np.float32))
            window.close()

    def test_rebuild_live_mix_plan_clears_stale_group_loop_cache(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            slot = drum_ui.PatternSlot(
                loop_stems={
                    "kick": np.ones((8, 1), dtype=np.float32),
                    "snare": np.full((8, 1), 2.0, dtype=np.float32),
                }
            )
            stale_key = ("kick",)
            slot.group_loop_cache[stale_key] = np.full((8, 1), 9.0, dtype=np.float32)
            window._live_slots["A"] = slot

            window._set_all_live_stems(False)
            window._toggle_live_stem("kick")
            window._toggle_live_stem("snare")

            self.assertNotIn(stale_key, window._live_slots["A"].group_loop_cache)
            rebuilt = window._live_group_loop_audio(window._live_slots["A"], ("kick", "snare"))
            self.assertIsNotNone(rebuilt)
            self.assertIn(("kick", "snare"), window._live_slots["A"].group_loop_cache)
            window.close()

    def test_live_effect_target_toggle_updates_button_state_and_mix_plan(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            window._set_all_live_stems(False)
            window._toggle_live_stem("kick")
            window._set_live_effect_value("lowpass", 1200.0)

            self.assertEqual(len(window._live_mix_plan.stems), 1)
            self.assertTrue(window._live_mix_plan.stems[0].apply_lowpass)
            self.assertTrue(window.live_effect_target_buttons["lowpass"]["kick"].isChecked())

            window._toggle_live_effect_target("lowpass", "kick")

            self.assertFalse(window.live_effect_target_buttons["lowpass"]["kick"].isChecked())
            self.assertEqual(len(window._live_mix_plan.stems), 1)
            self.assertFalse(window._live_mix_plan.stems[0].apply_lowpass)
            window.close()

    def test_live_distortion_changes_audio_only_when_target_enabled(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 100
        audio = np.zeros(96, dtype=np.float32)
        audio[0:24] = np.linspace(-0.6, 0.6, 24, dtype=np.float32)
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=505,
            swing=0.0,
            params=BreakPatternParams(seed=505),
            event_count=1,
            summary="kick:1",
            steps=tuple(
                GeneratedPatternStep(
                    step_index=index,
                    label="kick" if index == 1 else "silence",
                    velocity=100 if index == 1 else 0,
                    source_hit_index=1 if index == 1 else None,
                    source_label="kick" if index == 1 else None,
                    source_start_s=0.0 if index == 1 else None,
                    source_end_s=0.24 if index == 1 else None,
                    tags=("downbeat",) if index == 1 else (),
                )
                for index in range(1, 17)
            ),
        )
        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            live_preview = replace(
                preview,
                audio=window._normalize_preview_audio(preview.audio),
                loop_audio=window._normalize_preview_audio(preview.loop_audio),
                stems={name: window._normalize_preview_audio(preview.stems[name]) for name in PATTERN_STEM_NAMES},
                loop_stems={name: window._normalize_preview_audio(preview.loop_stems[name]) for name in PATTERN_STEM_NAMES},
            )
            slot = drum_ui.PatternSlot(
                pattern=pattern,
                params=pattern.params,
                seed=pattern.seed,
                mode=drum_ui.GENERATOR_MODE_CLASSIC,
                status="ready",
                stems=live_preview.stems,
                loop_stems=live_preview.loop_stems,
                preview=live_preview,
            )
            window._live_slots["A"] = slot
            window._live_active_slot = "A"
            window._set_all_live_stems(False)
            window._toggle_live_stem("kick")

            dry = window._mix_live_stem_chunk(slot, 0.0, 24)
            window._set_live_distortion_param("drive", 0.8)
            window._set_live_distortion_param("tone", 0.35)
            window._set_live_distortion_param("mix", 1.0)
            wet = window._mix_live_stem_chunk(slot, 0.0, 24)

            self.assertFalse(np.allclose(dry, wet))
            self.assertTrue(window.live_effect_target_buttons["distortion"]["kick"].isChecked())

            window._toggle_live_effect_target("distortion", "kick")
            bypassed = window._mix_live_stem_chunk(slot, 0.0, 24)
            np.testing.assert_allclose(dry, bypassed, atol=1e-6)
            window.close()

    def test_live_callback_switches_to_other_slot_on_loop_boundary(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 100
        audio = np.zeros(80, dtype=np.float32)
        audio[0:12] = 0.7
        audio[18:30] = -0.4
        pattern_a = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=101,
            swing=0.0,
            params=BreakPatternParams(seed=101),
            event_count=1,
            summary="kick:1",
            steps=tuple(
                GeneratedPatternStep(
                    step_index=index,
                    label="kick" if index == 1 else "silence",
                    velocity=96 if index == 1 else 0,
                    source_hit_index=1 if index == 1 else None,
                    source_label="kick" if index == 1 else None,
                    source_start_s=0.0 if index == 1 else None,
                    source_end_s=0.12 if index == 1 else None,
                    tags=("downbeat",) if index == 1 else (),
                )
                for index in range(1, 17)
            ),
        )
        pattern_b = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=202,
            swing=0.0,
            params=BreakPatternParams(seed=202),
            event_count=1,
            summary="snare:1",
            steps=tuple(
                GeneratedPatternStep(
                    step_index=index,
                    label="snare" if index == 1 else "silence",
                    velocity=82 if index == 1 else 0,
                    source_hit_index=2 if index == 1 else None,
                    source_label="snare" if index == 1 else None,
                    source_start_s=0.18 if index == 1 else None,
                    source_end_s=0.30 if index == 1 else None,
                    tags=("downbeat",) if index == 1 else (),
                )
                for index in range(1, 17)
            ),
        )
        preview_a = build_pattern_preview(audio, sample_rate, pattern_a, target_bpm=120.0)
        preview_b = build_pattern_preview(audio, sample_rate, pattern_b, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            fake_sd = _FakeSounddevice()

            def _normalized_live_preview(preview):
                return replace(
                    preview,
                    audio=window._normalize_preview_audio(preview.audio),
                    loop_audio=window._normalize_preview_audio(preview.loop_audio),
                    stems={name: window._normalize_preview_audio(preview.stems[name]) for name in PATTERN_STEM_NAMES},
                    loop_stems={name: window._normalize_preview_audio(preview.loop_stems[name]) for name in PATTERN_STEM_NAMES},
                )

            live_preview_a = _normalized_live_preview(preview_a)
            live_preview_b = _normalized_live_preview(preview_b)
            window._live_slots["A"] = drum_ui.PatternSlot(
                pattern=pattern_a,
                params=pattern_a.params,
                seed=pattern_a.seed,
                mode=drum_ui.GENERATOR_MODE_CLASSIC,
                status="ready",
                stems=live_preview_a.stems,
                loop_stems=live_preview_a.loop_stems,
                preview=live_preview_a,
            )
            window._live_slots["B"] = drum_ui.PatternSlot(
                pattern=pattern_b,
                params=pattern_b.params,
                seed=pattern_b.seed,
                mode=drum_ui.GENERATOR_MODE_CLASSIC,
                status="ready",
                stems=live_preview_b.stems,
                loop_stems=live_preview_b.loop_stems,
                preview=live_preview_b,
            )
            window._live_active_slot = "A"
            window._start_retimed_preview_playback(live_preview_a, owner=drum_ui.PREVIEW_OWNER_LIVE, sounddevice=fake_sd)
            window._live_pending_switch_slot = "B"

            outdata = np.zeros((220, 1), dtype=np.float32)
            fake_status = type("Status", (), {"output_underflow": False})()
            with mock.patch.object(window, "_refresh_live_mode_ui", wraps=window._refresh_live_mode_ui) as refresh_live_ui:
                fake_sd.streams[-1].callback(outdata, outdata.shape[0], None, fake_status)
                self.assertEqual(refresh_live_ui.call_count, 0)
                self.assertTrue(window._live_switch_ui_refresh_pending)
                window._drain_ui_callback_queue()
                self.assertGreaterEqual(refresh_live_ui.call_count, 1)

            self.assertEqual(window._live_active_slot, "B")
            self.assertIsNone(window._live_pending_switch_slot)
            self.assertTrue(np.max(np.abs(outdata)) > 0.0)
            self.assertEqual(window._live_slots["B"].status, "playing")
            self.assertIs(window._retimed_preview, live_preview_b)
            window.close()

    def test_live_target_bpm_uses_cached_value_outside_widget_access(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window._live_target_bpm_value = 177.5

            class _ExplodingSpin:
                def value(self):
                    raise AssertionError("live audio path should not read the Qt spinbox directly")

            window.generator_target_bpm_spin = _ExplodingSpin()
            self.assertEqual(window._live_target_bpm(), 177.5)
            window.close()

    def test_live_bpm_spin_stays_synced_with_generator_target_bpm(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            self.assertTrue(hasattr(window, "live_target_bpm_spin"))
            self.assertEqual(float(window.live_target_bpm_spin.value()), float(window.generator_target_bpm_spin.value()))

            window.live_target_bpm_spin.setValue(156.5)
            self.assertEqual(float(window.generator_target_bpm_spin.value()), 156.5)
            self.assertEqual(window._live_target_bpm(), 156.5)

            window.generator_target_bpm_spin.setValue(143.0)
            self.assertEqual(float(window.live_target_bpm_spin.value()), 143.0)
            self.assertEqual(window._live_target_bpm(), 143.0)
            window.close()

    def test_live_mode_rebuilds_slot_previews_when_target_bpm_changes_offline(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 100
        audio = np.zeros(80, dtype=np.float32)
        audio[0:12] = 0.8
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=303,
            swing=0.0,
            params=BreakPatternParams(seed=303),
            event_count=1,
            summary="snare:1",
            steps=tuple(
                GeneratedPatternStep(
                    step_index=index,
                    label="snare" if index == 1 else "silence",
                    velocity=92 if index == 1 else 0,
                    source_hit_index=1 if index == 1 else None,
                    source_label="snare" if index == 1 else None,
                    source_start_s=0.0 if index == 1 else None,
                    source_end_s=0.12 if index == 1 else None,
                    tags=("downbeat",) if index == 1 else (),
                )
                for index in range(1, 17)
            ),
        )
        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            live_preview = replace(
                preview,
                audio=window._normalize_preview_audio(preview.audio),
                loop_audio=window._normalize_preview_audio(preview.loop_audio),
                stems={name: window._normalize_preview_audio(preview.stems[name]) for name in PATTERN_STEM_NAMES},
                loop_stems={name: window._normalize_preview_audio(preview.loop_stems[name]) for name in PATTERN_STEM_NAMES},
            )
            window._live_slots["A"] = drum_ui.PatternSlot(
                pattern=pattern,
                params=pattern.params,
                seed=pattern.seed,
                mode=drum_ui.GENERATOR_MODE_CLASSIC,
                status="ready",
                stems=live_preview.stems,
                loop_stems=live_preview.loop_stems,
                preview=live_preview,
            )
            window._live_active_slot = "A"
            window.generator_live_mode_button.setChecked(True)
            with (
                mock.patch.object(window, "_analysis_audio_snapshot", return_value=(audio, sample_rate)),
                mock.patch.object(window, "_rebuild_live_slot_preview") as rebuild_preview,
            ):
                window.generator_target_bpm_spin.setValue(180.0)
            rebuild_preview.assert_called_once()
            window.close()

    def test_live_callback_keeps_native_pitch_when_generator_target_bpm_changes(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        sample_rate = 100
        audio = np.zeros(80, dtype=np.float32)
        audio[0:12] = 0.75
        pattern = GeneratedBreakPattern(
            bars=1,
            step_count=16,
            seed=404,
            swing=0.0,
            params=BreakPatternParams(seed=404),
            event_count=1,
            summary="kick:1",
            steps=tuple(
                GeneratedPatternStep(
                    step_index=index,
                    label="kick" if index == 1 else "silence",
                    velocity=96 if index == 1 else 0,
                    source_hit_index=1 if index == 1 else None,
                    source_label="kick" if index == 1 else None,
                    source_start_s=0.0 if index == 1 else None,
                    source_end_s=0.12 if index == 1 else None,
                    tags=("downbeat",) if index == 1 else (),
                )
                for index in range(1, 17)
            ),
        )
        preview = build_pattern_preview(audio, sample_rate, pattern, target_bpm=120.0)

        with (
            mock.patch.object(drum_ui, "QSettings", _FakeSettings),
            mock.patch.object(drum_ui.DrumDetectorWindow, "_init_waveform_panel", lambda self: None),
        ):
            window = drum_ui.DrumDetectorWindow()
            window.generator_live_mode_button.setChecked(True)
            live_preview = replace(
                preview,
                audio=window._normalize_preview_audio(preview.audio),
                loop_audio=window._normalize_preview_audio(preview.loop_audio),
                stems={name: window._normalize_preview_audio(preview.stems[name]) for name in PATTERN_STEM_NAMES},
                loop_stems={name: window._normalize_preview_audio(preview.loop_stems[name]) for name in PATTERN_STEM_NAMES},
            )
            window._live_slots["A"] = drum_ui.PatternSlot(
                pattern=pattern,
                params=pattern.params,
                seed=pattern.seed,
                mode=drum_ui.GENERATOR_MODE_CLASSIC,
                status="ready",
                stems=live_preview.stems,
                loop_stems=live_preview.loop_stems,
                preview=live_preview,
            )
            window._live_active_slot = "A"
            window.generator_target_bpm_spin.setValue(240.0)
            fake_sd = _FakeSounddevice()

            window._start_retimed_preview_playback(live_preview, owner=drum_ui.PREVIEW_OWNER_LIVE, sounddevice=fake_sd)
            outdata = np.zeros((25, 1), dtype=np.float32)
            should_stop = window._fill_live_preview_buffer(outdata)

            self.assertFalse(should_stop)
            self.assertAlmostEqual(float(window._retime_stream_cursor), 25.0, places=4)
            self.assertGreater(float(np.max(np.abs(outdata))), 0.0)
            window.close()


if __name__ == "__main__":
    unittest.main()
