from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

# `break` est un mot-cle Python : import par importlib.
BreakGeneratorPanel = importlib.import_module(
    "frontend.labo.break.generator.generator_widget"
).BreakGeneratorPanel
PATTERN_TABLE_HEIGHT = importlib.import_module(
    "frontend.labo.break.generator.generator_constants"
).PATTERN_TABLE_HEIGHT


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
    step_count: int = 32
    bars: int = 2
    seed: int = 3
    event_count: int = 32
    swing: float = 0.0


class _Signal:
    def connect(self, *_a, **_k) -> None:
        pass


class _Service:
    def __getattr__(self, _name):
        return _Signal()


class _Player:
    current_sample_path = ""
    current_sample_id = None
    is_playing = False
    is_paused = False

    def clear_audio(self, *_a, **_k) -> None:
        pass


class _Ctx:
    audio_player = _Player()


class PlayheadTests(unittest.TestCase):
    """Le step joue s'illumine, et on ne repeint que les cellules concernees."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = BreakGeneratorPanel(_Ctx(), _Service())
        self.addCleanup(self.panel.deleteLater)
        pattern = _Pattern(
            steps=tuple(
                _Step(i + 1, ["kick", "closed_hat", "snare", "closed_hat"][i % 4])
                for i in range(32)
            )
        )
        self.panel._generated_pattern = pattern
        self.panel._populate_pattern_table(pattern)
        self.controller = self.panel.pattern

    def _hit_item(self, step: int):
        return self.panel.pattern_table.item(2, step - 1)

    def test_lighting_a_step_changes_only_that_cell(self):
        untouched = self._hit_item(5).background()
        self.controller.set_playhead_step(3)
        self.assertEqual(self.panel._playhead_step, 3)
        self.assertEqual(self._hit_item(5).background(), untouched)

    def test_moving_the_playhead_restores_the_previous_cell(self):
        original = self._hit_item(3).background().color().name()
        self.controller.set_playhead_step(3)
        self.assertNotEqual(self._hit_item(3).background().color().name(), original)
        self.controller.set_playhead_step(4)
        self.assertEqual(self._hit_item(3).background().color().name(), original)

    def test_clearing_the_playhead_restores_everything(self):
        original = self._hit_item(7).background().color().name()
        self.controller.set_playhead_step(7)
        self.controller.set_playhead_step(None)
        self.assertIsNone(self.panel._playhead_step)
        self.assertEqual(self._hit_item(7).background().color().name(), original)

    def test_same_step_twice_is_a_no_op(self):
        self.controller.set_playhead_step(2)
        lit = self._hit_item(2).background().color().name()
        self.controller.set_playhead_step(2)
        # La sauvegarde ne doit pas avoir capture la couleur allumee, sinon
        # on ne saurait plus restaurer la couleur d'origine.
        self.controller.set_playhead_step(None)
        self.assertNotEqual(self._hit_item(2).background().color().name(), lit)

    def test_out_of_range_step_is_ignored(self):
        self.controller.set_playhead_step(999)
        self.assertEqual(self.panel._playhead_step, 999)
        self.assertIsNone(self.panel._playhead_backup)

    def test_repainting_the_grid_drops_a_stale_playhead(self):
        self.controller.set_playhead_step(3)
        self.controller._refresh_pattern_visual_state(self.panel._generated_pattern)
        self.assertIsNone(self.panel._playhead_step)
        self.assertIsNone(self.panel._playhead_backup)


class PlayheadPositionTests(unittest.TestCase):
    """Conversion position audio -> numero de step."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = BreakGeneratorPanel(_Ctx(), _Service())
        self.addCleanup(self.panel.deleteLater)
        self.panel._generated_pattern = _Pattern(steps=tuple())
        self.panel.target_bpm_spin.setValue(120.0)  # 1 step = 0.125 s

    def test_origin_follows_a_loop_range(self):
        self.panel._active_preview_request = {
            "kind": "loop_range", "start_step": 9, "end_step": 12
        }
        self.assertEqual(self.panel.playback._playhead_origin_step(), 9)

    def test_origin_follows_a_from_step_preview(self):
        self.panel._active_preview_request = {"kind": "from_step", "step_index": 5}
        self.assertEqual(self.panel.playback._playhead_origin_step(), 5)

    def test_full_preview_starts_at_step_one(self):
        self.panel._active_preview_request = {"kind": "full"}
        self.assertEqual(self.panel.playback._playhead_origin_step(), 1)

    def test_no_step_when_nothing_plays(self):
        self.panel.playback._is_preview_playing = lambda: False
        self.assertIsNone(self.panel.playback._current_playhead_step())


class PatternGridSizeTests(unittest.TestCase):
    """La grille doit avoir la place d'afficher sa barre de defilement, sinon
    un pattern de 2 bars (32 steps) est coupe net a droite."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_height_reserves_room_for_the_horizontal_scrollbar(self):
        rows_and_header = 26 * 3 + 32
        self.assertGreater(PATTERN_TABLE_HEIGHT, rows_and_header)

    def test_every_step_stays_reachable_in_a_narrow_window(self):
        panel = BreakGeneratorPanel(_Ctx(), _Service())
        self.addCleanup(panel.deleteLater)
        pattern = _Pattern(
            steps=tuple(_Step(i + 1, "kick") for i in range(32)), step_count=32
        )
        panel._generated_pattern = pattern
        panel.show()
        self.addCleanup(panel.hide)
        self._app.processEvents()
        panel._populate_pattern_table(pattern)
        table = panel.pattern_table
        table.setFixedWidth(900)
        self._app.processEvents()
        self._app.processEvents()

        scrollbar = table.horizontalScrollBar()
        needed = 32 * table.columnWidth(0) - table.viewport().width()
        self.assertGreater(needed, 0, "cas de test invalide: tout tient deja")
        self.assertGreaterEqual(scrollbar.maximum(), needed)
        # Et la barre ne doit pas manger une ligne au passage.
        self.assertGreaterEqual(table.viewport().height(), 26 * 3)


if __name__ == "__main__":
    unittest.main()
