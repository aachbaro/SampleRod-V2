"""Geometrie du placement : convention semi-ouverte et arrondi grille.

Aucun import Qt, aucune QApplication : ce module doit rester testable seul.
"""

from __future__ import annotations

import unittest

from frontend.modular.layout.geometry import (
    Rect,
    rect_from_qrect,
    snap_rect_edges_to_grid,
    snap_resized_edges_to_grid,
    snap_to_grid,
)


class PurityTests(unittest.TestCase):
    """Le moteur ne doit JAMAIS importer Qt.

    C'est l'invariant qui rend seuils, priorites et cas limites testables sans
    ouvrir de fenetre. Une regression ici ne casserait rien visiblement, mais
    ferait perdre la testabilite : d'ou ce garde-fou.
    """

    def _source_of(self, module_name: str) -> str:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.find_spec(module_name)
        return Path(spec.origin).read_text(encoding="utf-8")

    def test_geometry_module_imports_no_qt(self):
        source = self._source_of("frontend.modular.layout.geometry")
        self.assertNotIn("PySide6", source)
        self.assertNotIn("pyqtgraph", source)

    def test_snap_engine_module_imports_no_qt(self):
        source = self._source_of("frontend.modular.layout.snap_engine")
        self.assertNotIn("PySide6", source)
        self.assertNotIn("pyqtgraph", source)

    def test_the_layout_package_pulls_no_qt_of_its_own(self):
        """Le paquet `layout` n'ajoute AUCUN module Qt.

        `frontend/modular/__init__.py` importe ModuleWindow, donc Qt, avant
        meme qu'on atteigne `layout`. On mesure donc le DELTA : ce que le
        moteur charge en propre, une fois le parent deja en memoire.
        """
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        script = (
            "import sys;"
            "sys.path.insert(0, r'%s');"
            "import frontend.modular;"
            "before = {m for m in sys.modules if m.startswith('PySide6')};"
            "import frontend.modular.layout.geometry;"
            "import frontend.modular.layout.snap_engine;"
            "after = {m for m in sys.modules if m.startswith('PySide6')};"
            "print(len(after - before))" % root
        )
        out = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "0", "le moteur a tire un module Qt")


class RectConventionTests(unittest.TestCase):
    """Convention SEMI-OUVERTE : right = x + w, surtout pas x + w - 1.

    Qt utilise la convention inclusive pour QRect.right()/bottom(). Melanger
    les deux produirait un accolement a 7 px la ou on en demande 8.
    """

    def test_edges_of_a_reference_rect(self):
        rect = Rect(10, 20, 100, 50)
        self.assertEqual(rect.left, 10)
        self.assertEqual(rect.right, 110)      # PAS 109
        self.assertEqual(rect.top, 20)
        self.assertEqual(rect.bottom, 70)      # PAS 69

    def test_width_is_the_distance_between_edges(self):
        rect = Rect(10, 20, 100, 50)
        self.assertEqual(rect.right - rect.left, rect.w)
        self.assertEqual(rect.bottom - rect.top, rect.h)

    def test_two_rects_touching_have_equal_edges(self):
        # Coeur de la convention : coller B a droite de A signifie
        # B.left == A.right, sans le +1 de la convention inclusive.
        a = Rect(0, 0, 100, 50)
        b = Rect(a.right, 0, 100, 50)
        self.assertEqual(b.left, 100)
        self.assertEqual(b.left - a.right, 0)

    def test_negative_coordinates(self):
        rect = Rect(-200, -100, 80, 40)
        self.assertEqual(rect.left, -200)
        self.assertEqual(rect.right, -120)
        self.assertEqual(rect.top, -100)
        self.assertEqual(rect.bottom, -60)


class RectTransformTests(unittest.TestCase):
    def test_moved_to_preserves_dimensions(self):
        rect = Rect(10, 20, 100, 50).moved_to(300, 400)
        self.assertEqual((rect.x, rect.y, rect.w, rect.h), (300, 400, 100, 50))

    def test_translated_shifts_both_axes(self):
        rect = Rect(10, 20, 100, 50).translated(-5, 7)
        self.assertEqual((rect.x, rect.y), (5, 27))

    def test_rects_are_immutable_and_comparable(self):
        self.assertEqual(Rect(1, 2, 3, 4), Rect(1, 2, 3, 4))
        with self.assertRaises(Exception):
            Rect(1, 2, 3, 4).x = 9  # type: ignore[misc]

    def test_a_rect_without_surface_is_invalid(self):
        self.assertTrue(Rect(0, 0, 1, 1).is_valid())
        self.assertFalse(Rect(0, 0, 0, 50).is_valid())
        self.assertFalse(Rect(0, 0, 50, 0).is_valid())
        self.assertFalse(Rect(0, 0, -10, -10).is_valid())


class _FakeQRect:
    """QRect minimal : x/y/width/height, plus les aretes INCLUSIVES de Qt.

    Les proprietes right()/bottom() sont volontairement presentes avec la
    convention de Qt : si la conversion les utilisait, le test le verrait.
    """

    def __init__(self, x, y, w, h):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self): return self._x
    def y(self): return self._y
    def width(self): return self._w
    def height(self): return self._h
    def right(self): return self._x + self._w - 1      # convention Qt
    def bottom(self): return self._y + self._h - 1     # convention Qt


class QRectBridgeTests(unittest.TestCase):
    """Le SEUL pont entre Qt et le moteur pur."""

    def test_conversion_keeps_the_four_primitive_values(self):
        rect = rect_from_qrect(_FakeQRect(10, 20, 100, 50))
        self.assertEqual((rect.x, rect.y, rect.w, rect.h), (10, 20, 100, 50))

    def test_conversion_ignores_qt_inclusive_edges(self):
        # Le QRect annonce right()=109 ; notre Rect doit dire 110.
        source = _FakeQRect(10, 20, 100, 50)
        rect = rect_from_qrect(source)
        self.assertEqual(source.right(), 109)
        self.assertEqual(rect.right, 110)


class SnapToGridTests(unittest.TestCase):
    def test_rounds_to_the_nearest_multiple(self):
        self.assertEqual(snap_to_grid(103, 16), 96)    # 103-96=7 < 112-103=9
        self.assertEqual(snap_to_grid(207, 16), 208)

    def test_a_value_already_on_the_grid_does_not_move(self):
        for grid in (8, 10, 12, 16):
            self.assertEqual(snap_to_grid(grid * 5, grid), grid * 5)

    def test_every_supported_grid_size(self):
        self.assertEqual(snap_to_grid(11, 8), 8)
        self.assertEqual(snap_to_grid(11, 10), 10)
        self.assertEqual(snap_to_grid(11, 12), 12)
        self.assertEqual(snap_to_grid(11, 16), 16)

    def test_exactly_halfway_rounds_up_consistently(self):
        # Regle symetrique et previsible, des deux cotes de zero.
        self.assertEqual(snap_to_grid(4, 8), 8)
        self.assertEqual(snap_to_grid(-4, 8), 0)

    def test_negative_values(self):
        self.assertEqual(snap_to_grid(-3, 8), 0)     # -3 est plus pres de 0
        self.assertEqual(snap_to_grid(-5, 8), -8)    # -5 est plus pres de -8
        self.assertEqual(snap_to_grid(-16, 8), -16)

    def test_a_null_or_negative_grid_disables_rounding(self):
        # Un reglage aberrant doit desactiver la grille, pas casser un geste.
        self.assertEqual(snap_to_grid(103, 0), 103)
        self.assertEqual(snap_to_grid(103, -8), 103)

    def test_the_result_is_never_further_than_half_a_step(self):
        for value in range(-40, 41):
            self.assertLessEqual(abs(snap_to_grid(value, 8) - value), 4)


class SnapRectEdgesTests(unittest.TestCase):
    def test_the_four_edges_land_on_grid_lines(self):
        result = snap_rect_edges_to_grid(Rect(13, 19, 101, 77), 16)
        self.assertEqual(result, Rect(16, 16, 96, 80))
        self.assertEqual(
            (result.left % 16, result.top % 16, result.right % 16, result.bottom % 16),
            (0, 0, 0, 0),
        )

    def test_negative_coordinates_are_supported(self):
        result = snap_rect_edges_to_grid(Rect(-101, -29, 83, 47), 16)
        self.assertEqual(
            (result.left % 16, result.top % 16, result.right % 16, result.bottom % 16),
            (0, 0, 0, 0),
        )

    def test_minimum_size_is_rounded_up_to_a_whole_cell(self):
        result = snap_rect_edges_to_grid(
            Rect(3, 5, 30, 20), 16, min_width=41, min_height=33
        )
        self.assertEqual((result.w, result.h), (48, 48))

    def test_maximum_size_is_rounded_down_to_a_whole_cell(self):
        result = snap_rect_edges_to_grid(
            Rect(0, 0, 190, 150), 32, max_width=150, max_height=130
        )
        self.assertEqual((result.w, result.h), (128, 128))

    def test_an_invalid_grid_leaves_the_rectangle_untouched(self):
        rect = Rect(3, 5, 30, 20)
        self.assertEqual(snap_rect_edges_to_grid(rect, 0), rect)


class SnapResizedEdgesTests(unittest.TestCase):
    def test_resizing_from_the_right_keeps_the_left_edge_fixed(self):
        start = Rect(32, 32, 96, 64)
        result = snap_resized_edges_to_grid(start, Rect(32, 32, 109, 64), 16)
        self.assertEqual(result, Rect(32, 32, 112, 64))

    def test_resizing_from_the_left_keeps_the_right_edge_fixed(self):
        start = Rect(32, 32, 96, 64)
        result = snap_resized_edges_to_grid(start, Rect(19, 32, 109, 64), 16)
        self.assertEqual(result, Rect(16, 32, 112, 64))

    def test_corner_resize_aligns_only_the_two_moving_edges(self):
        start = Rect(32, 32, 96, 64)
        result = snap_resized_edges_to_grid(start, Rect(32, 32, 109, 77), 16)
        self.assertEqual(result, Rect(32, 32, 112, 80))


if __name__ == "__main__":
    unittest.main()
