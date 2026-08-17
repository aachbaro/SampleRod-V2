"""Moteur de magnetisme : relations, priorites, seuils, grille.

Aucun import Qt. Chaque scenario est construit pour qu'UN SEUL candidat soit
sous le seuil sur l'axe teste, sans quoi l'assertion serait ambigue.
"""

from __future__ import annotations

import unittest

from frontend.modular.layout.geometry import Rect
from frontend.modular.layout.snap_engine import (
    CandidateKind,
    Relation,
    SnapSettings,
    resolve_snap,
)


def _settings(**overrides) -> SnapSettings:
    """Reglages de test : grille COUPEE par defaut.

    La grille comblerait l'axe libre et brouillerait les assertions ; on
    l'active explicitement dans les tests qui la concernent.
    """
    base = {"grid_enabled": False}
    base.update(overrides)
    return SnapSettings(**base)


class AbutmentTests(unittest.TestCase):
    """Accolement : les fenetres se touchent, a `gap_px` pres."""

    def test_left_edge_against_right_edge(self):
        target = Rect(0, 0, 100, 100)                 # right = 100
        moving = Rect(105, 0, 50, 50)                 # vise 108, delta = +3
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.left, 108)
        self.assertEqual(result.rect.left - target.right, 8)
        self.assertEqual(result.horizontal_target.relation, Relation.ABUT_LEFT_TO_RIGHT)

    def test_right_edge_against_left_edge(self):
        target = Rect(200, 0, 100, 100)               # left = 200
        moving = Rect(140, 0, 50, 50)                 # right = 190, vise 192
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.right, 192)
        self.assertEqual(target.left - result.rect.right, 8)
        self.assertEqual(result.horizontal_target.relation, Relation.ABUT_RIGHT_TO_LEFT)

    def test_top_edge_against_bottom_edge(self):
        target = Rect(0, 0, 100, 100)                 # bottom = 100
        moving = Rect(0, 104, 50, 50)                 # vise 108, delta = +4
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.top, 108)
        self.assertEqual(result.rect.top - target.bottom, 8)
        self.assertEqual(result.vertical_target.relation, Relation.ABUT_TOP_TO_BOTTOM)

    def test_bottom_edge_against_top_edge(self):
        target = Rect(0, 200, 100, 100)               # top = 200
        moving = Rect(0, 140, 50, 50)                 # bottom = 190, vise 192
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.bottom, 192)
        self.assertEqual(target.top - result.rect.bottom, 8)
        self.assertEqual(result.vertical_target.relation, Relation.ABUT_BOTTOM_TO_TOP)


class ParallelAlignmentTests(unittest.TestCase):
    """Alignement parallele : les aretes se confondent, SANS espacement."""

    def test_left_edges_align(self):
        target = Rect(200, 0, 100, 100)
        moving = Rect(205, 0, 50, 50)
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.left, target.left)
        self.assertEqual(result.horizontal_target.relation, Relation.ALIGN_LEFT)

    def test_right_edges_align(self):
        target = Rect(200, 0, 100, 100)               # right = 300
        moving = Rect(245, 0, 50, 50)                 # right = 295
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.right, target.right)
        self.assertEqual(result.horizontal_target.relation, Relation.ALIGN_RIGHT)

    def test_top_edges_align(self):
        target = Rect(0, 200, 100, 100)
        moving = Rect(0, 205, 50, 50)
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.top, target.top)
        self.assertEqual(result.vertical_target.relation, Relation.ALIGN_TOP)

    def test_bottom_edges_align(self):
        target = Rect(0, 200, 100, 100)               # bottom = 300
        moving = Rect(0, 245, 50, 50)                 # bottom = 295
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.rect.bottom, target.bottom)
        self.assertEqual(result.vertical_target.relation, Relation.ALIGN_BOTTOM)

    def test_the_gap_never_applies_to_a_parallel_alignment(self):
        # Avec un espacement de 8, un alignement de bords gauches doit donner
        # exactement target.left, jamais target.left + 8.
        target = Rect(200, 0, 100, 100)
        moving = Rect(205, 0, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=_settings(gap_px=8),
        )
        self.assertEqual(result.rect.left, 200)


class GapTests(unittest.TestCase):
    """L'espacement global s'applique a l'accolement, et exactement."""

    def test_each_supported_gap_value(self):
        target = Rect(0, 0, 100, 100)                 # right = 100
        for gap in (0, 6, 8, 10):
            with self.subTest(gap=gap):
                moving = Rect(100 + gap - 3, 0, 50, 50)   # delta = +3
                result = resolve_snap(
                    moving_rect=moving,
                    other_rects=[("t", target)],
                    settings=_settings(gap_px=gap),
                )
                self.assertEqual(result.rect.left - target.right, gap)

    def test_an_eight_pixel_gap_is_exact_with_no_off_by_one(self):
        # Le piege classique : QRect.right() vaut x + w - 1. Si la conversion
        # ou le moteur melangeait les conventions, on obtiendrait 7 ou 9.
        target = Rect(0, 0, 100, 100)
        moving = Rect(105, 0, 50, 50)
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings(gap_px=8)
        )
        self.assertEqual(result.rect.left - target.right, 8)
        self.assertNotEqual(result.rect.left - target.right, 7)
        self.assertNotEqual(result.rect.left - target.right, 9)

    def test_a_zero_gap_makes_windows_touch(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(97, 0, 50, 50)
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings(gap_px=0)
        )
        self.assertEqual(result.rect.left, target.right)


class ScreenEdgeTests(unittest.TestCase):
    """Bords d'ecran : alignement A RAS, l'espacement ne s'y applique pas."""

    def test_window_aligns_flush_with_the_left_screen_edge(self):
        screen = Rect(0, 0, 1920, 1040)
        moving = Rect(3, 500, 400, 300)
        result = resolve_snap(
            moving_rect=moving, screen_rects=[("s", screen)], settings=_settings(gap_px=8)
        )
        self.assertEqual(result.rect.left, 0)          # a ras, PAS 8
        self.assertEqual(result.horizontal_target.kind, CandidateKind.SCREEN)

    def test_window_aligns_flush_with_the_right_screen_edge(self):
        screen = Rect(0, 0, 1920, 1040)
        moving = Rect(1515, 500, 400, 300)             # right = 1915
        result = resolve_snap(
            moving_rect=moving, screen_rects=[("s", screen)], settings=_settings(gap_px=8)
        )
        self.assertEqual(result.rect.right, 1920)

    def test_window_aligns_with_the_bottom_of_the_usable_area(self):
        # availableGeometry : la barre des taches est deja exclue en amont.
        screen = Rect(0, 0, 1920, 1040)
        moving = Rect(500, 735, 400, 300)              # bottom = 1035
        result = resolve_snap(
            moving_rect=moving, screen_rects=[("s", screen)], settings=_settings()
        )
        self.assertEqual(result.rect.bottom, 1040)

    def test_several_screens_the_nearest_edge_wins(self):
        left_screen = Rect(-1920, 0, 1920, 1080)
        main_screen = Rect(0, 0, 1920, 1040)
        moving = Rect(4, 500, 300, 200)                # 4 px du bord de main
        result = resolve_snap(
            moving_rect=moving,
            screen_rects=[("left", left_screen), ("main", main_screen)],
            settings=_settings(),
        )
        self.assertEqual(result.rect.left, 0)
        self.assertEqual(result.horizontal_target.target_id, "main")

    def test_negative_coordinates_on_a_secondary_screen(self):
        left_screen = Rect(-1920, 0, 1920, 1080)
        moving = Rect(-1917, 300, 400, 300)
        result = resolve_snap(
            moving_rect=moving, screen_rects=[("left", left_screen)], settings=_settings()
        )
        self.assertEqual(result.rect.left, -1920)


class PriorityTests(unittest.TestCase):
    """C'est la PROXIMITE qui decide, pas le type de cible."""

    def test_a_nearer_screen_beats_a_further_window(self):
        # Ecran a 2 px, fenetre a 5 px : l'ecran gagne.
        window = Rect(200, 500, 100, 100)              # ALIGN_LEFT -> delta -5
        screen = Rect(207, 0, 1000, 1000)              # ALIGN_LEFT -> delta +2
        moving = Rect(205, 500, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("w", window)],
            screen_rects=[("s", screen)],
            settings=_settings(),
        )
        self.assertEqual(result.rect.left, 207)
        self.assertEqual(result.horizontal_target.kind, CandidateKind.SCREEN)

    def test_at_equal_distance_the_window_wins(self):
        # Fenetre a -5, ecran a +5 : egalite stricte, la fenetre l'emporte.
        window = Rect(200, 500, 100, 100)              # ALIGN_LEFT -> delta -5
        screen = Rect(210, 0, 1000, 1000)              # ALIGN_LEFT -> delta +5
        moving = Rect(205, 500, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("w", window)],
            screen_rects=[("s", screen)],
            settings=_settings(),
        )
        self.assertEqual(result.rect.left, 200)
        self.assertEqual(result.horizontal_target.kind, CandidateKind.WINDOW)

    def test_a_perfect_tie_between_windows_is_deterministic(self):
        # Deux fenetres proposent exactement le meme deplacement : c'est
        # l'identifiant qui departage, pour que le resultat soit reproductible.
        first = Rect(200, 0, 100, 100)
        second = Rect(200, 400, 100, 100)
        moving = Rect(205, 200, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("b_window", first), ("a_window", second)],
            settings=_settings(),
        )
        self.assertEqual(result.horizontal_target.target_id, "a_window")
        # L'ordre de la liste ne doit rien changer.
        reversed_result = resolve_snap(
            moving_rect=moving,
            other_rects=[("a_window", second), ("b_window", first)],
            settings=_settings(),
        )
        self.assertEqual(reversed_result.horizontal_target.target_id, "a_window")


class GridTests(unittest.TestCase):
    """La grille comble un axe libre, elle ne concourt jamais."""

    def test_the_grid_applies_when_nothing_else_matched(self):
        moving = Rect(103, 207, 400, 300)
        result = resolve_snap(
            moving_rect=moving, settings=SnapSettings(grid_px=8, grid_enabled=True)
        )
        self.assertEqual(result.rect.x, 104)
        self.assertEqual(result.rect.y, 208)
        self.assertEqual(result.horizontal_target.kind, CandidateKind.GRID)

    def test_the_grid_never_overrides_an_alignment_already_found(self):
        # X accroche une fenetre (205 -> 200, non multiple de 8) : la grille
        # ne doit PAS repasser derriere pour arrondir a 200... ni a 208.
        target = Rect(205, 0, 100, 100)
        moving = Rect(202, 1000, 50, 50)               # ALIGN_LEFT -> delta +3
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=SnapSettings(grid_px=8, grid_enabled=True),
        )
        self.assertEqual(result.rect.left, 205)        # la fenetre, pas la grille
        self.assertEqual(result.horizontal_target.kind, CandidateKind.WINDOW)

    def test_the_grid_fills_only_the_free_axis(self):
        # X accroche une fenetre, Y n'a rien : seul Y est arrondi.
        target = Rect(205, 0, 100, 100)
        moving = Rect(202, 1003, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=SnapSettings(grid_px=8, grid_enabled=True),
        )
        self.assertEqual(result.horizontal_target.kind, CandidateKind.WINDOW)
        self.assertEqual(result.vertical_target.kind, CandidateKind.GRID)
        self.assertEqual(result.rect.y, 1000)          # 1003 -> 1000 (a 3 px)
        self.assertEqual(result.rect.y % 8, 0)

    def test_the_grid_never_changes_the_dimensions(self):
        moving = Rect(103, 207, 401, 303)
        result = resolve_snap(
            moving_rect=moving, settings=SnapSettings(grid_px=8, grid_enabled=True)
        )
        self.assertEqual(result.rect.w, 401)
        self.assertEqual(result.rect.h, 303)

    def test_a_position_already_on_the_grid_does_not_move(self):
        moving = Rect(104, 208, 400, 300)
        result = resolve_snap(
            moving_rect=moving, settings=SnapSettings(grid_px=8, grid_enabled=True)
        )
        self.assertEqual((result.rect.x, result.rect.y), (104, 208))
        self.assertFalse(result.snapped_x)
        self.assertFalse(result.snapped_y)

    def test_the_grid_moves_a_window_by_at_most_half_a_step(self):
        # Critere de ressenti : l'arrondi doit etre imperceptible.
        for x in range(0, 64):
            moving = Rect(x, 0, 400, 300)
            result = resolve_snap(
                moving_rect=moving, settings=SnapSettings(grid_px=8, grid_enabled=True)
            )
            self.assertLessEqual(abs(result.rect.x - x), 4)


class ThresholdTests(unittest.TestCase):
    def test_beyond_the_threshold_nothing_is_proposed(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(121, 500, 50, 50)                # accolement a 13 px
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=_settings(threshold_px=12),
        )
        self.assertEqual(result.rect, moving)
        self.assertFalse(result.snapped_x)

    def test_exactly_at_the_threshold_still_snaps(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(120, 500, 50, 50)                # accolement a 12 px
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=_settings(threshold_px=12),
        )
        self.assertEqual(result.rect.left, 108)


class AxisIndependenceTests(unittest.TestCase):
    def test_one_candidate_per_axis_at_most(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(105, 104, 50, 50)
        result = resolve_snap(
            moving_rect=moving, other_rects=[("t", target)], settings=_settings()
        )
        self.assertEqual(result.horizontal_target.axis, "x")
        self.assertEqual(result.vertical_target.axis, "y")

    def test_horizontal_on_one_target_vertical_on_another(self):
        # Composition libre : rien n'oblige les deux axes a suivre la meme cible.
        horizontal = Rect(500, 0, 100, 100)            # ALIGN_LEFT
        vertical = Rect(0, 700, 100, 100)              # ALIGN_TOP
        moving = Rect(505, 705, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("h", horizontal), ("v", vertical)],
            settings=_settings(),
        )
        self.assertEqual(result.horizontal_target.target_id, "h")
        self.assertEqual(result.vertical_target.target_id, "v")
        self.assertEqual((result.rect.x, result.rect.y), (500, 700))


class SafetyTests(unittest.TestCase):
    def test_snapping_disabled_is_strict_identity(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(105, 104, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=SnapSettings(enabled=False),
        )
        self.assertEqual(result.rect, moving)
        self.assertFalse(result.snapped_x)
        self.assertFalse(result.snapped_y)
        self.assertIsNone(result.horizontal_target)

    def test_window_magnetism_can_be_turned_off_alone(self):
        target = Rect(0, 0, 100, 100)
        moving = Rect(105, 500, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", target)],
            settings=_settings(windows_enabled=False),
        )
        self.assertEqual(result.rect, moving)

    def test_screen_magnetism_can_be_turned_off_alone(self):
        screen = Rect(0, 0, 1920, 1040)
        moving = Rect(3, 500, 400, 300)
        result = resolve_snap(
            moving_rect=moving,
            screen_rects=[("s", screen)],
            settings=_settings(screens_enabled=False),
        )
        self.assertEqual(result.rect, moving)

    def test_an_invalid_moving_rect_produces_no_movement(self):
        moving = Rect(105, 104, 0, 0)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", Rect(0, 0, 100, 100))],
            settings=_settings(),
        )
        self.assertEqual(result.rect, moving)

    def test_invalid_targets_are_ignored(self):
        moving = Rect(105, 500, 50, 50)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("degenerate", Rect(0, 0, 0, 0))],
            settings=_settings(),
        )
        self.assertEqual(result.rect, moving)

    def test_no_target_rect_is_ever_modified(self):
        # Regle cardinale : SEULE la fenetre deplacee bouge. C'est ce qui
        # ecarte par construction les attractions circulaires.
        target = Rect(0, 0, 100, 100)
        screen = Rect(0, 0, 1920, 1040)
        targets = [("t", target)]
        screens = [("s", screen)]
        resolve_snap(
            moving_rect=Rect(105, 104, 50, 50),
            other_rects=targets,
            screen_rects=screens,
            settings=_settings(),
        )
        self.assertEqual(targets, [("t", Rect(0, 0, 100, 100))])
        self.assertEqual(screens, [("s", Rect(0, 0, 1920, 1040))])

    def test_no_targets_at_all_is_harmless(self):
        moving = Rect(104, 208, 50, 50)
        result = resolve_snap(moving_rect=moving, settings=_settings())
        self.assertEqual(result.rect, moving)

    def test_the_moving_dimensions_are_never_altered(self):
        moving = Rect(105, 104, 137, 89)
        result = resolve_snap(
            moving_rect=moving,
            other_rects=[("t", Rect(0, 0, 100, 100))],
            settings=_settings(),
        )
        self.assertEqual((result.rect.w, result.rect.h), (137, 89))


if __name__ == "__main__":
    unittest.main()
