from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from prototypes.drum_detector.analyzer import TransientHit
from prototypes.drum_detector.preview import RetimedPreview, RetimedPreviewSegment, build_retimed_preview


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
    def __init__(self) -> None:
        self.play_calls: list[tuple[np.ndarray, int, bool]] = []
        self.stop_calls = 0

    def play(self, audio, sample_rate: int, *, blocking: bool = False) -> None:
        self.play_calls.append((np.array(audio, copy=True), int(sample_rate), bool(blocking)))

    def stop(self) -> None:
        self.stop_calls += 1


class DrumPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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

    def test_loop_mode_restarts_retimed_preview_after_finish(self) -> None:
        from prototypes.drum_detector import ui as drum_ui

        fake_sounddevice = _FakeSounddevice()
        preview_audio = np.linspace(-0.25, 0.25, 120, dtype=np.float32)
        preview = RetimedPreview(
            audio=preview_audio,
            sample_rate=1000,
            source_bpm=85.0,
            target_bpm=170.0,
            speed_ratio=0.5,
            duration_s=0.12,
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
            window._retimed_preview = preview

            window._on_retimed_preview_finished()

            self.assertEqual(len(fake_sounddevice.play_calls), 1)
            played_audio, played_rate, blocking = fake_sounddevice.play_calls[0]
            np.testing.assert_array_equal(played_audio, preview_audio)
            self.assertEqual(played_rate, 1000)
            self.assertFalse(blocking)
            self.assertTrue(window._retimed_preview_playing)
            self.assertTrue(window._retime_stop_timer.isActive())
            self.assertTrue(window._retime_visual_timer.isActive())
            self.assertIn("boucle", window.retime_info_label.text().lower())

            window._stop_retimed_preview(update_status=False)
            window.close()


if __name__ == "__main__":
    unittest.main()
