from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

BreakGeneratorPanel = importlib.import_module(
    "frontend.labo.break.generator.generator_widget"
).BreakGeneratorPanel


@dataclass
class _Pattern:
    steps: tuple = ()
    step_count: int = 16
    bars: int = 1
    seed: int = 7
    event_count: int = 4
    swing: float = 0.0


@dataclass
class _Analysis:
    source_path: str = "C:/tmp/break.wav"
    slices: tuple = ()


class _Signal:
    def connect(self, *_args, **_kwargs) -> None:
        pass


class _RecordingService:
    """Service double : memorise les demandes de rendu."""

    def __init__(self):
        self.render_calls: list[dict] = []

    def __getattr__(self, _name):
        return _Signal()

    def render_break_pattern(self, _result, _pattern, **kwargs):
        self.render_calls.append(dict(kwargs))
        return True


class _Player:
    current_sample_path = ""
    current_sample_id = None
    is_playing = False
    is_paused = False

    def clear_audio(self, *_args, **_kwargs) -> None:
        pass


class _Ctx:
    audio_player = _Player()


class LiveBpmTests(unittest.TestCase):
    """Changer le BPM pendant la lecture doit re-rendre le preview au nouveau
    tempo — jamais rejouer le meme fichier plus vite, ce qui pitcherait le
    break et divergerait de ce que « Rendre artefact » produit."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = _RecordingService()
        self.panel = BreakGeneratorPanel(_Ctx(), self.service)
        self.addCleanup(self.panel.deleteLater)
        self.panel._generated_pattern = _Pattern()
        self.panel._analysis_result = _Analysis()
        self.panel._pattern_dirty = False
        self._playing = True
        self.panel.playback._is_preview_playing = lambda: self._playing

    # -- Armement du re-rendu ------------------------------------------------
    def test_bpm_change_while_playing_arms_the_refresh(self):
        self.panel.target_bpm_spin.setValue(96.0)
        self.assertTrue(self.panel._live_bpm_timer.isActive())

    def test_bpm_change_while_stopped_does_nothing(self):
        self._playing = False
        self.panel.target_bpm_spin.setValue(96.0)
        self.assertFalse(self.panel._live_bpm_timer.isActive())

    def test_dirty_pattern_blocks_the_live_refresh(self):
        self.panel._pattern_dirty = True
        self.panel.target_bpm_spin.setValue(96.0)
        self.assertFalse(self.panel._live_bpm_timer.isActive())

    # -- Re-rendu ------------------------------------------------------------
    def test_refresh_renders_at_the_new_bpm_as_a_preview(self):
        self.panel.target_bpm_spin.setValue(96.0)
        self.panel._apply_live_bpm()
        self.assertEqual(len(self.service.render_calls), 1)
        self.assertAlmostEqual(self.service.render_calls[0]["target_bpm"], 96.0)
        # Surtout pas un rendu d'artefact.
        self.assertEqual(self.panel._render_request_mode, "preview")

    def test_refresh_reissues_the_extract_currently_playing(self):
        # Une boucle sur une plage de steps doit revenir en boucle sur la
        # meme plage, pas repartir sur le pattern entier.
        self.panel._active_preview_request = {
            "kind": "loop_range", "start_step": 5, "end_step": 8
        }
        self.panel._apply_live_bpm()
        self.assertEqual(
            self.panel._preview_request,
            {"kind": "loop_range", "start_step": 5, "end_step": 8},
        )

    def test_refresh_defers_while_a_render_is_running(self):
        self.panel._render_busy = True
        self.panel._apply_live_bpm()
        self.assertEqual(self.service.render_calls, [])
        self.assertTrue(self.panel._live_bpm_pending)

    def test_deferred_refresh_is_resumed_afterwards(self):
        self.panel._render_busy = True
        self.panel._apply_live_bpm()
        self.panel._render_busy = False
        self.panel._resume_pending_live_bpm()
        self.assertFalse(self.panel._live_bpm_pending)
        self.assertTrue(self.panel._live_bpm_timer.isActive())

    # -- Protection du rendu d'artefact --------------------------------------
    def test_artifact_render_cancels_a_pending_live_refresh(self):
        self.panel.target_bpm_spin.setValue(96.0)
        self.panel._live_bpm_pending = True
        self.panel._render_pattern_artifact()
        self.assertFalse(self.panel._live_bpm_timer.isActive())
        self.assertFalse(self.panel._live_bpm_pending)
        self.assertEqual(self.panel._render_request_mode, "artifact")

    def test_artifact_render_uses_the_same_bpm_as_the_preview(self):
        self.panel.target_bpm_spin.setValue(96.0)
        self.panel._apply_live_bpm()
        preview_bpm = self.service.render_calls[-1]["target_bpm"]

        self.panel._render_busy = False
        self.panel._render_pattern_artifact()
        self.assertAlmostEqual(self.service.render_calls[-1]["target_bpm"], preview_bpm)

    def test_stopping_the_preview_clears_the_live_state(self):
        self.panel._active_preview_path = "C:/tmp/preview.wav"
        self.panel.target_bpm_spin.setValue(96.0)
        self.panel._live_bpm_pending = True
        self.panel.playback._stop_preview()
        self.assertFalse(self.panel._live_bpm_timer.isActive())
        self.assertFalse(self.panel._live_bpm_pending)
        self.assertIsNone(self.panel._active_preview_request)


if __name__ == "__main__":
    unittest.main()
