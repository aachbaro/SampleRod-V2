"""Reperage visuel de la grille sur le fond de l'atelier.

Le point sensible : le pavage doit tomber exactement la ou le magnetisme
aligne. Un indicateur decale serait pire que pas d'indicateur du tout.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend.modular.backdrop import (
    GRID_LINE_ALPHA,
    GRID_MULTIPLIERS,
    MIN_VISIBLE_GRID_PX,
    BackdropWindow,
    display_step_px,
    grid_brush_origin,
)
from frontend.modular.layout.geometry import snap_to_grid

_app = QApplication.instance() or QApplication([])


class BrushOriginTests(unittest.TestCase):
    """Le pavage suit la grille GLOBALE, pas le coin du fond."""

    def test_an_origin_at_zero_needs_no_offset(self):
        self.assertEqual(grid_brush_origin(0, 0, 8).x(), 0)
        self.assertEqual(grid_brush_origin(0, 0, 8).y(), 0)

    def test_an_origin_already_on_the_grid_needs_no_offset(self):
        origin = grid_brush_origin(64, 128, 8)
        self.assertEqual((origin.x(), origin.y()), (0, 0))

    def test_an_offset_origin_is_compensated(self):
        # Le fond commence a x=3 : il faut decaler de 5 pour que le premier
        # point retombe sur un multiple de 8 en coordonnees globales.
        origin = grid_brush_origin(3, 0, 8)
        self.assertEqual(origin.x(), 5)
        self.assertEqual((3 + origin.x()) % 8, 0)

    def test_a_negative_origin_is_compensated(self):
        # Cas reel : un ecran secondaire a GAUCHE du principal place l'origine
        # du bureau virtuel en negatif. C'est la que l'erreur se verrait.
        origin = grid_brush_origin(-1920, 0, 8)
        self.assertEqual((-1920 + origin.x()) % 8, 0)

    def test_an_awkward_negative_origin_is_compensated(self):
        for global_x in (-1, -3, -7, -9, -1917, -2561):
            with self.subTest(global_x=global_x):
                origin = grid_brush_origin(global_x, 0, 8)
                self.assertGreaterEqual(origin.x(), 0)
                self.assertLess(origin.x(), 8)
                self.assertEqual((global_x + origin.x()) % 8, 0)

    def test_the_offset_matches_where_windows_actually_snap(self):
        # Verification croisee avec le moteur : le premier point affiche doit
        # coincider avec la position ou une fenetre serait arrondie.
        step = 8
        for global_x in (-2561, -1920, -3, 0, 3, 101, 1917):
            with self.subTest(global_x=global_x):
                origin = grid_brush_origin(global_x, 0, step)
                first_dot_global = global_x + origin.x()
                self.assertEqual(first_dot_global, snap_to_grid(first_dot_global, step))

    def test_a_degenerate_step_yields_no_offset(self):
        self.assertEqual((grid_brush_origin(3, 3, 0).x(), grid_brush_origin(3, 3, 0).y()), (0, 0))


class DisplayStepTests(unittest.TestCase):
    """Le quadrillage est toujours un MULTIPLE du pas de magnetisme.

    C'est ce qui empeche l'indicateur de mentir : une taille libre tracerait
    des lignes la ou aucune fenetre ne s'accroche.
    """

    def test_a_multiplier_of_one_shows_every_snap_step(self):
        self.assertEqual(display_step_px(8, 1), 8)

    def test_every_proposed_multiplier_stays_a_multiple(self):
        for multiplier in GRID_MULTIPLIERS:
            with self.subTest(multiplier=multiplier):
                self.assertEqual(display_step_px(8, multiplier) % 8, 0)

    def test_the_coarsest_setting_is_readable(self):
        self.assertEqual(display_step_px(8, 8), 64)

    def test_a_degenerate_multiplier_falls_back_to_one(self):
        self.assertEqual(display_step_px(8, 0), 8)
        self.assertEqual(display_step_px(8, -3), 8)

    def test_a_degenerate_snap_step_falls_back_to_one(self):
        self.assertEqual(display_step_px(0, 4), 4)

    def test_every_displayed_line_is_a_real_snap_position(self):
        # Verification croisee avec le moteur, pour tous les multiplicateurs.
        for multiplier in GRID_MULTIPLIERS:
            step = display_step_px(8, multiplier)
            for line in range(0, 512, step):
                self.assertEqual(line, snap_to_grid(line, 8))


class BackdropGridTests(unittest.TestCase):
    def setUp(self):
        self.backdrop = BackdropWindow()

    def tearDown(self):
        self.backdrop.deleteLater()

    def test_the_grid_is_off_by_default(self):
        self.assertFalse(self.backdrop.is_grid_visible())

    def test_it_can_be_turned_on_and_off(self):
        self.backdrop.set_grid_visible(True)
        self.assertTrue(self.backdrop.is_grid_visible())
        self.backdrop.set_grid_visible(False)
        self.assertFalse(self.backdrop.is_grid_visible())

    def test_the_snap_step_can_be_set_with_the_visibility(self):
        self.backdrop.set_grid_visible(True, step=16)
        self.assertEqual(self.backdrop.snap_step, 16)

    def test_the_displayed_step_is_the_snap_step_times_the_multiplier(self):
        self.backdrop.set_grid_metrics(snap_px=8, multiplier=4)
        self.assertEqual(self.backdrop.grid_step, 32)

    def test_the_tile_is_one_displayed_step_square(self):
        self.backdrop.set_grid_metrics(snap_px=12, multiplier=1)
        tile = self.backdrop._tile()
        self.assertEqual((tile.width(), tile.height()), (12, 12))

    def test_the_tile_carries_both_a_vertical_and_a_horizontal_line(self):
        # Un carreau avec une ligne sur chaque bord suffit : repete, il forme
        # le quadrillage complet.
        self.backdrop.set_grid_metrics(snap_px=16, multiplier=1)
        image = self.backdrop._tile().toImage()
        corner = image.pixelColor(0, 0)
        self.assertGreater(corner.alpha(), 0)                  # le coin est trace
        self.assertGreater(image.pixelColor(0, 8).alpha(), 0)  # verticale
        self.assertGreater(image.pixelColor(8, 0).alpha(), 0)  # horizontale
        self.assertEqual(image.pixelColor(8, 8).alpha(), 0)    # interieur vide

    def test_the_lines_are_discreet(self):
        # Des lignes couvrent bien plus de surface que des points : a opacite
        # egale elles domineraient le fond.
        self.assertLess(GRID_LINE_ALPHA, 40)

    def test_the_tile_is_reused_between_paints(self):
        # Refabriquer le pavage a chaque repeint couterait cher pour rien.
        self.backdrop.set_grid_visible(True, step=8)
        self.assertIs(self.backdrop._tile(), self.backdrop._tile())

    def test_changing_the_snap_step_rebuilds_the_tile(self):
        self.backdrop.set_grid_visible(True, step=8)
        first = self.backdrop._tile()
        self.backdrop.set_grid_visible(True, step=16)
        self.assertIsNot(self.backdrop._tile(), first)

    def test_changing_the_multiplier_rebuilds_the_tile(self):
        self.backdrop.set_grid_metrics(snap_px=8, multiplier=2)
        first = self.backdrop._tile()
        self.backdrop.set_grid_metrics(multiplier=8)
        self.assertIsNot(self.backdrop._tile(), first)

    def test_setting_the_same_metrics_keeps_the_tile(self):
        self.backdrop.set_grid_metrics(snap_px=8, multiplier=4)
        first = self.backdrop._tile()
        self.backdrop.set_grid_metrics(snap_px=8, multiplier=4)
        self.assertIs(self.backdrop._tile(), first)

    def test_a_theme_change_rebuilds_the_tile(self):
        # La couleur des lignes suit le texte du theme.
        self.backdrop.set_grid_visible(True, step=8)
        first = self.backdrop._tile()
        self.backdrop._on_theme_changed()
        self.assertIsNot(self.backdrop._tile(), first)

    def test_too_fine_a_grid_is_not_drawn(self):
        # En dessous du seuil, le quadrillage vire a l'aplat uniforme.
        self.backdrop.set_grid_metrics(
            snap_px=MIN_VISIBLE_GRID_PX - 1, multiplier=1
        )
        self.backdrop.set_grid_visible(True)
        self.assertIsNone(self.backdrop._tile())

    def test_a_multiplier_can_rescue_a_too_fine_snap_step(self):
        # Snap a 2 px, mais affiche tous les 8 : lisible.
        self.backdrop.set_grid_metrics(snap_px=2, multiplier=4)
        self.assertIsNotNone(self.backdrop._tile())

    def test_painting_with_the_grid_on_does_not_raise(self):
        self.backdrop.setGeometry(-1920, 0, 800, 600)
        self.backdrop.set_grid_visible(True, step=8)
        self.backdrop.render(self.backdrop.grab())    # force un paintEvent

    def test_painting_with_the_grid_off_does_not_raise(self):
        self.backdrop.set_grid_visible(False)
        self.backdrop.render(self.backdrop.grab())


class WindowManagerGridTests(unittest.TestCase):
    """Le pilotage depuis l'orchestrateur."""

    def setUp(self):
        from frontend.modular.module_registry import ModuleRegistry
        from frontend.modular.window_manager import WindowManager

        self.manager = WindowManager(None, None, ModuleRegistry())

    def tearDown(self):
        self.manager.set_backdrop_enabled(False)

    def test_the_overlay_is_off_by_default(self):
        self.assertFalse(self.manager.is_grid_overlay_visible())

    def test_turning_the_grid_on_lights_the_backdrop(self):
        # Sans fond, il n'y a pas de surface : un bouton sans effet visible
        # serait pris pour une panne.
        self.manager.set_grid_overlay_visible(True)
        self.assertTrue(self.manager.is_backdrop_enabled())
        self.assertTrue(self.manager.is_grid_overlay_visible())

    def test_the_backdrop_receives_the_grid_state(self):
        self.manager.set_grid_overlay_visible(True)
        self.assertTrue(self.manager._backdrop.is_grid_visible())

    def test_the_backdrop_receives_the_snap_step(self):
        self.manager.set_grid_overlay_visible(True)
        self.assertEqual(
            self.manager._backdrop.snap_step,
            self.manager.layout_manager.settings.grid_px,
        )

    def test_the_displayed_step_is_a_multiple_of_the_snap_step(self):
        # Garantie centrale : chaque ligne affichee marque une position ou une
        # fenetre s'accroche vraiment.
        self.manager.set_grid_overlay_visible(True)
        snap = self.manager.layout_manager.settings.grid_px
        for multiplier in GRID_MULTIPLIERS:
            with self.subTest(multiplier=multiplier):
                self.manager.set_grid_overlay_multiplier(multiplier)
                step = self.manager.grid_overlay_step_px()
                self.assertEqual(step % snap, 0)
                self.assertEqual(step, snap * multiplier)

    def test_changing_the_multiplier_reaches_the_backdrop(self):
        self.manager.set_grid_overlay_visible(True)
        with mock.patch.object(
            self.manager.layout_manager, "align_windows_to_grid", return_value=0
        ) as align:
            self.manager.set_grid_overlay_multiplier(8)
        self.assertEqual(self.manager._backdrop.grid_multiplier, 8)
        self.assertEqual(self.manager._backdrop.grid_step, 8 * 8)
        self.assertEqual(self.manager.layout_manager.alignment_grid_px, 64)
        align.assert_called_once_with(64)

    def test_the_current_multiplier_also_configures_move_alignment(self):
        # Important au demarrage : le multiplicateur charge peut etre egal a
        # la valeur par defaut, mais le moteur doit quand meme le recevoir.
        current = self.manager.grid_overlay_multiplier()
        self.manager.set_grid_overlay_multiplier(current)
        self.assertEqual(
            self.manager.layout_manager.alignment_grid_px,
            self.manager.grid_overlay_step_px(),
        )

    def test_reapplying_the_same_multiplier_does_not_realign_windows(self):
        current = self.manager.grid_overlay_multiplier()
        with mock.patch.object(
            self.manager.layout_manager, "align_windows_to_grid", return_value=0
        ) as align:
            self.manager.set_grid_overlay_multiplier(current)
        align.assert_not_called()

    def test_a_multiplier_below_one_is_clamped(self):
        self.manager.set_grid_overlay_multiplier(0)
        self.assertEqual(self.manager.grid_overlay_multiplier(), 1)

    def test_the_multiplier_survives_a_backdrop_created_later(self):
        self.manager.set_grid_overlay_multiplier(2)
        self.manager._grid_overlay_visible = True
        self.manager.set_backdrop_enabled(True)
        self.assertEqual(self.manager._backdrop.grid_multiplier, 2)

    def test_turning_the_grid_off_leaves_the_backdrop_on(self):
        # Eteindre le reperage ne doit pas emporter le fond avec lui.
        self.manager.set_grid_overlay_visible(True)
        self.manager.set_grid_overlay_visible(False)
        self.assertTrue(self.manager.is_backdrop_enabled())
        self.assertFalse(self.manager._backdrop.is_grid_visible())

    def test_a_backdrop_created_later_inherits_the_grid_state(self):
        self.manager._grid_overlay_visible = True
        self.manager.set_backdrop_enabled(True)
        self.assertTrue(self.manager._backdrop.is_grid_visible())


if __name__ == "__main__":
    unittest.main()
