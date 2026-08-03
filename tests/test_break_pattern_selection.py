from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

_generator_widget = importlib.import_module(
    "frontend.labo.break.generator.generator_widget"
)
BreakGeneratorPanel = _generator_widget.BreakGeneratorPanel


@dataclass
class _Step:
    step_index: int
    label: str
    velocity: int = 90
    source_hit_index: int | None = 1
    tags: tuple = ()
    pitch_shift: float = 0.0


@dataclass
class _Pattern:
    steps: tuple
    step_count: int = 16
    bars: int = 1
    seed: int = 11
    event_count: int = 16
    swing: float = 0.0


@dataclass
class _Analysis:
    source_path: str = "C:/tmp/break.wav"
    slices: tuple = ()


class _Signal:
    def connect(self, *_a, **_k) -> None:
        pass


class _RecordingService:
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

    def clear_audio(self, *_a, **_k) -> None:
        pass


class _Ctx:
    audio_player = _Player()


_LABELS = ["kick", "closed_hat", "snare", "closed_hat"] * 4


class PatternSelectionTests(unittest.TestCase):
    """Cliquer-glisser sur les numeros de step selectionne une plage a boucler,
    et le menu contextuel permet de la figer ou de l'exporter."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = _RecordingService()
        self.panel = BreakGeneratorPanel(_Ctx(), self.service)
        self.addCleanup(self.panel.deleteLater)
        self.panel._analysis_result = _Analysis()
        self.panel._generated_pattern = _Pattern(
            steps=tuple(_Step(i + 1, label) for i, label in enumerate(_LABELS))
        )
        self.panel._pattern_dirty = False
        self.controller = self.panel.pattern
        self.loops: list[tuple[int, int]] = []
        self.from_steps: list[int] = []
        self.panel._preview_pattern_loop_range = lambda a, b: self.loops.append((a, b))
        self.panel._preview_pattern_from_step = lambda s: self.from_steps.append(s)

    # -- Selection -----------------------------------------------------------
    def test_dragging_across_steps_selects_the_range(self):
        self.controller._preview_selection_range(3, 7)
        self.assertEqual(self.panel._pattern_loop_range, (3, 7))

    def test_dragging_backwards_normalises_the_range(self):
        self.controller._preview_selection_range(9, 4)
        self.assertEqual(self.panel._pattern_loop_range, (4, 9))

    def test_releasing_after_a_drag_loops_the_selection(self):
        self.controller._commit_selection_range(3, 7, dragged=True)
        self.assertEqual(self.loops, [(3, 7)])
        self.assertEqual(self.panel._pattern_loop_range, (3, 7))

    def test_a_plain_click_still_plays_from_that_step(self):
        self.controller._commit_selection_range(5, 5, dragged=False)
        self.assertEqual(self.from_steps, [5])
        self.assertEqual(self.loops, [])
        self.assertIsNone(self.panel._pattern_loop_range)

    # -- Figer la selection --------------------------------------------------
    def test_locking_a_range_covers_every_step(self):
        self.controller._set_range_locked(3, 6, True)
        self.assertEqual(self.panel._pattern_locked_steps, {3, 4, 5, 6})

    def test_unlocking_a_range_clears_only_those_steps(self):
        self.panel._pattern_locked_steps = {2, 3, 4, 9}
        self.controller._set_range_locked(3, 4, False)
        self.assertEqual(self.panel._pattern_locked_steps, {2, 9})

    def test_anchoring_a_range_freezes_each_step_on_its_type(self):
        # Le vocabulaire des ancres est plus grossier que celui des labels :
        # closed_hat se fige sur la famille "hat".
        self.controller._set_range_anchored(1, 3, True)
        self.assertEqual(self.panel._pattern_step_anchors[1], "kick")
        self.assertEqual(self.panel._pattern_step_anchors[2], "hat")
        self.assertEqual(self.panel._pattern_step_anchors[3], "snare")

    def test_removing_anchors_on_a_range(self):
        self.controller._set_range_anchored(1, 3, True)
        self.controller._set_range_anchored(1, 3, False)
        self.assertEqual(self.panel._pattern_step_anchors, {})

    def test_freezing_does_not_block_preview_or_export(self):
        # Le piege : marquer le pattern "dirty" empecherait d'enchainer
        # « je fige la plage » puis « je l'exporte ».
        self.controller._set_range_locked(3, 6, True)
        self.assertFalse(self.panel._pattern_dirty)
        self.controller._set_range_anchored(3, 6, True)
        self.assertFalse(self.panel._pattern_dirty)

    # -- Export de la plage --------------------------------------------------
    def test_exporting_a_range_asks_for_a_render_in_range_mode(self):
        self.panel._render_range_artifact(5, 8)
        self.assertEqual(len(self.service.render_calls), 1)
        self.assertEqual(self.panel._render_request_mode, "artifact_range")
        self.assertEqual(self.panel._artifact_range, (5, 8))

    def test_exporting_uses_the_current_bpm(self):
        self.panel.target_bpm_spin.setValue(128.0)
        self.panel._render_range_artifact(1, 4)
        self.assertAlmostEqual(self.service.render_calls[-1]["target_bpm"], 128.0)

    def test_export_is_refused_while_a_render_runs(self):
        self.panel._render_busy = True
        self.panel._render_range_artifact(1, 4)
        self.assertEqual(self.service.render_calls, [])
        self.assertIsNone(self.panel._artifact_range)

    def test_export_is_refused_on_a_dirty_pattern(self):
        self.panel._pattern_dirty = True
        self.panel._render_range_artifact(1, 4)
        self.assertEqual(self.service.render_calls, [])

    def test_range_export_cancels_a_pending_live_bpm_refresh(self):
        self.panel._live_bpm_pending = True
        self.panel._render_range_artifact(1, 4)
        self.assertFalse(self.panel._live_bpm_pending)
        self.assertFalse(self.panel._live_bpm_timer.isActive())


if __name__ == "__main__":
    unittest.main()
