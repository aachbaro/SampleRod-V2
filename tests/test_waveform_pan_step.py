"""Defilement lateral (Shift+molette) : le pas doit suivre le zoom.

Le pas etait calcule sur la duree du FICHIER, donc identique quel que soit le
zoom : une fois zoome, chaque cran sautait plusieurs fenetres d'un coup.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import pyqtgraph as pg

from frontend.sample_gui.waveform.waveform_navigation import (
    PAN_FRACTION,
    WaveformNavigationController,
    pan_step_s,
)

_app = QApplication.instance() or QApplication([])


class PanStepMathTests(unittest.TestCase):
    """Le pas est une fraction de la fenetre visible."""

    def test_a_step_is_a_tenth_of_the_visible_window(self):
        self.assertAlmostEqual(pan_step_s(10.0, forward=True), 1.0)

    def test_zooming_in_shrinks_the_step_proportionally(self):
        # Fenetre 20x plus petite -> pas 20x plus petit.
        wide = pan_step_s(10.0, forward=True)
        tight = pan_step_s(0.5, forward=True)
        self.assertAlmostEqual(wide / tight, 20.0)

    def test_the_direction_only_flips_the_sign(self):
        self.assertAlmostEqual(
            pan_step_s(4.0, forward=True), -pan_step_s(4.0, forward=False)
        )

    def test_the_step_never_exceeds_the_visible_window(self):
        # Sinon on saute par-dessus ce qu'on regarde, sans repere d'un cran a
        # l'autre : c'etait tout le probleme.
        for span in (0.05, 0.5, 5.0, 300.0):
            self.assertLess(abs(pan_step_s(span, forward=True)), span)

    def test_a_degenerate_window_does_not_move(self):
        self.assertEqual(pan_step_s(0.0, forward=True), 0.0)
        self.assertEqual(pan_step_s(-3.0, forward=True), 0.0)

    def test_the_fraction_is_configurable(self):
        self.assertAlmostEqual(pan_step_s(10.0, forward=True, fraction=0.25), 2.5)

    def test_the_default_fraction_is_the_module_constant(self):
        self.assertAlmostEqual(pan_step_s(10.0, forward=True), 10.0 * PAN_FRACTION)


class _StubWidget:
    def __init__(self, duration=30.0):
        self.plot = pg.PlotWidget()
        self.duration = duration


class PanStepFromViewTests(unittest.TestCase):
    """Le controleur lit la fenetre reellement affichee."""

    def setUp(self):
        self.widget = _StubWidget()
        self.controller = WaveformNavigationController(self.widget)
        self.view_box = self.widget.plot.getViewBox()

    def test_the_step_follows_the_current_view(self):
        self.view_box.setXRange(10.0, 12.0, padding=0)
        step = self.controller.pan_step(self.view_box, forward=True)
        self.assertAlmostEqual(step, 2.0 * PAN_FRACTION, places=3)

    def test_zoomed_in_the_step_is_far_smaller_than_the_old_fixed_one(self):
        # Ancien comportement : 0.1 * duree du fichier = 3.0 s, quel que soit
        # le zoom. Sur une fenetre de 0.5 s, c'etait six fenetres par cran.
        self.view_box.setXRange(4.0, 4.5, padding=0)
        step = abs(self.controller.pan_step(self.view_box, forward=True))
        old_fixed_step = 0.1 * self.widget.duration
        self.assertLess(step, old_fixed_step / 50.0)
        self.assertLess(step, 0.5)

    def test_it_falls_back_to_the_file_duration_without_a_view(self):
        class _NoView:
            def viewRange(self):
                raise RuntimeError("vue pas encore etablie")

        step = self.controller.pan_step(_NoView(), forward=True)
        self.assertAlmostEqual(step, self.widget.duration * PAN_FRACTION)


if __name__ == "__main__":
    unittest.main()
