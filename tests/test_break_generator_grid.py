from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

# `break` est un mot-cle Python : le package ne peut pas etre importe
# directement avec `from frontend.labo.break... import ...`.
BreakGeneratorPanel = importlib.import_module(
    "frontend.labo.break.generator.generator_widget"
).BreakGeneratorPanel


@dataclass
class _Step:
    step_index: int
    label: str
    velocity: int = 0
    source_hit_index: int | None = None
    tags: tuple = ()
    pitch_shift: float = 0.0


@dataclass
class _Pattern:
    steps: tuple
    step_count: int = 16
    bars: int = 1
    seed: int = 42
    event_count: int = 0
    summary: str = ""


class _DummySignal:
    def connect(self, *_args, **_kwargs) -> None:
        pass


class _DummyBreakService:
    def __getattr__(self, _name):
        return _DummySignal()


def _make_pattern() -> _Pattern:
    steps = (
        _Step(1, "kick", velocity=107, source_hit_index=27),
        _Step(2, "closed_hat", velocity=48, source_hit_index=84, tags=("reverse",)),
        _Step(3, "silence"),
    )
    return _Pattern(steps=steps, event_count=2)


class BreakGeneratorGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = BreakGeneratorPanel(None, _DummyBreakService())
        self.pattern = _make_pattern()
        self.panel._generated_pattern = self.pattern
        self.panel._populate_pattern_table(self.pattern)

    def tearDown(self):
        self.panel.deleteLater()

    def test_grid_is_compact_three_rows(self):
        table = self.panel.pattern_table
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual(table.columnCount(), 16)
        # Cellules carrees : hauteur de ligne proche de la largeur de colonne.
        self.assertLessEqual(abs(table.columnWidth(0) - table.rowHeight(0)), 10)

    def test_velocity_source_and_fx_moved_to_tooltip(self):
        table = self.panel.pattern_table
        tooltip = table.item(2, 1).toolTip()
        self.assertIn("48", tooltip)          # velocite
        self.assertIn("84", tooltip)          # slice source
        self.assertIn("Rev", tooltip)         # FX
        # Et plus aucune ligne dediee dans la grille.
        self.assertEqual(table.item(0, 1), None)

    def test_silence_step_has_no_source_slice(self):
        controller = self.panel.pattern
        self.assertIsNone(controller._step_source_hit_index(self.pattern.steps[2]))
        self.assertEqual(controller._step_source_hit_index(self.pattern.steps[0]), 27)

    def test_inspect_step_source_emits_slice_index(self):
        received: list[int] = []
        self.panel.sliceInspectRequested.connect(received.append)
        self.assertTrue(self.panel.pattern._inspect_step_source(1))
        self.assertEqual(received, [27])

    def test_inspect_step_source_is_noop_on_silence(self):
        received: list[int] = []
        self.panel.sliceInspectRequested.connect(received.append)
        self.assertFalse(self.panel.pattern._inspect_step_source(3))
        self.assertEqual(received, [])

    def test_context_menu_targets_event_row_only(self):
        table = self.panel.pattern_table
        controller = self.panel.pattern
        event_pos = table.visualRect(table.model().index(2, 0)).center()
        anchor_pos = table.visualRect(table.model().index(0, 0)).center()
        self.assertEqual(controller._event_step_at_pos(event_pos), 1)
        self.assertIsNone(controller._event_step_at_pos(anchor_pos))

    def test_controls_accept_mouse_wheel(self):
        # Les spins/combos du generateur doivent reagir a la molette.
        for control in (self.panel.target_bpm_spin, self.panel.bars_spin, self.panel.mode_combo):
            self.assertNotIn("_NoScroll", type(control).__name__)


if __name__ == "__main__":
    unittest.main()
