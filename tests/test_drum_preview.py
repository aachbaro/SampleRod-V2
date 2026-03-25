from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QRadioButton, QTableWidgetItem

from prototypes.drum_detector.analyzer import DrumCandidate, DrumDetectionResult, TransientHit
from prototypes.drum_detector.pattern_generator import (
    BreakPatternParams,
    GeneratedBreakPattern,
    GeneratedPatternStep,
    generate_break_pattern,
)
from prototypes.drum_detector.preview import (
    PREVIEW_MODE_PATTERN,
    PREVIEW_MODE_QUANTIZE,
    RetimedPreview,
    RetimedPreviewSegment,
    build_pattern_preview,
    build_retimed_preview,
)


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

    def data(self, role):
        if role == Qt.ItemDataRole.UserRole:
            return self._payload
        return None


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
            window._populate_result(result)
            window._populate_hits(result)

            window._on_hit_label_changed(2, "snare")

            self.assertEqual(window._result.transient_hits[1].label, "snare")
            self.assertIsNone(window._generated_pattern)
            self.assertIn('"label": "snare"', window.json_view.toPlainText())
            self.assertIn("snare:1", window.hits_summary_label.text())
            picker = window.hits_table.cellWidget(1, 1)
            checked = [radio for radio in picker.findChildren(QRadioButton) if radio.isChecked()]
            self.assertEqual(len(checked), 1)
            self.assertEqual(checked[0].property("hitLabel"), "snare")
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
                    TransientHit(2, 0.25, 0.33, "closed_hat", 0.8, -4.0, 0.1, 0.2, 0.7),
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
                window.close()
        finally:
            try:
                os.unlink(sample_path)
            except OSError:
                pass

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

            bar_button = window.generator_sequence_table.cellWidget(5, 0)
            beat_button = window.generator_sequence_table.cellWidget(5, 4)
            self.assertEqual(bar_button.property("generatorStepRole"), "bar_start")
            self.assertEqual(beat_button.property("generatorStepRole"), "beat")
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


if __name__ == "__main__":
    unittest.main()
