from __future__ import annotations

import unittest

from frontend.sample_gui.waveform.waveform_grid import (
    grid_marker_times,
    grid_slice_count,
    merge_grid_markers,
    slice_duration_s,
    step_duration_s,
)


class StepMathTests(unittest.TestCase):
    """Un step = une double-croche, meme convention que le generateur."""

    def test_step_duration_at_120_bpm(self):
        # 120 BPM -> 0.5 s le temps -> 0.125 s la double-croche.
        self.assertAlmostEqual(step_duration_s(120.0), 0.125)

    def test_one_bar_at_120_bpm_lasts_two_seconds(self):
        self.assertAlmostEqual(slice_duration_s(120.0, 16), 2.0)

    def test_two_bars_are_twice_as_long(self):
        self.assertAlmostEqual(slice_duration_s(90.0, 32), slice_duration_s(90.0, 16) * 2)

    def test_invalid_tempo_has_no_duration(self):
        self.assertEqual(step_duration_s(0.0), 0.0)
        self.assertEqual(slice_duration_s(120.0, 0), 0.0)


class GridMarkerTests(unittest.TestCase):
    """Extrapolation d'une grille depuis un point de depart."""

    def test_grid_starts_on_the_origin_and_steps_regularly(self):
        # 8 s a 120 BPM, tranches d'une mesure (2 s) depuis 0.
        times = grid_marker_times(
            origin_s=0.0, bpm=120.0, steps_per_slice=16, duration_s=8.0
        )
        self.assertEqual([round(t, 3) for t in times], [0.0, 2.0, 4.0, 6.0])

    def test_grid_respects_a_late_origin(self):
        times = grid_marker_times(
            origin_s=1.5, bpm=120.0, steps_per_slice=16, duration_s=8.0
        )
        self.assertEqual([round(t, 3) for t in times], [1.5, 3.5, 5.5, 7.5])

    def test_no_marker_is_glued_to_the_very_end(self):
        # 6 s pile : le marqueur a 6.0 s ne delimiterait aucune tranche.
        times = grid_marker_times(
            origin_s=0.0, bpm=120.0, steps_per_slice=16, duration_s=6.0
        )
        self.assertEqual([round(t, 3) for t in times], [0.0, 2.0, 4.0])

    def test_origin_can_be_excluded(self):
        times = grid_marker_times(
            origin_s=0.0, bpm=120.0, steps_per_slice=16, duration_s=8.0,
            include_origin=False,
        )
        self.assertEqual([round(t, 3) for t in times], [2.0, 4.0, 6.0])

    def test_origin_past_the_end_yields_nothing(self):
        self.assertEqual(
            grid_marker_times(origin_s=9.0, bpm=120.0, steps_per_slice=16, duration_s=8.0),
            [],
        )

    def test_absurd_settings_are_capped_not_hanging(self):
        # Un tempo enorme sur un long fichier ne doit pas produire une liste
        # infinie qui figerait l'interface.
        times = grid_marker_times(
            origin_s=0.0, bpm=400.0, steps_per_slice=1, duration_s=3600.0,
            max_markers=500,
        )
        self.assertEqual(len(times), 500)

    def test_slice_count_matches_the_marker_count(self):
        count = grid_slice_count(
            origin_s=0.0, bpm=140.0, steps_per_slice=16, duration_s=30.0
        )
        times = grid_marker_times(
            origin_s=0.0, bpm=140.0, steps_per_slice=16, duration_s=30.0
        )
        self.assertEqual(count, len(times))


class MergeTests(unittest.TestCase):
    """La grille s'ajoute au decoupage existant sans le detruire."""

    def test_existing_markers_are_kept(self):
        merged = merge_grid_markers([0.75, 3.10], [0.0, 2.0, 4.0])
        self.assertEqual(merged, [0.0, 0.75, 2.0, 3.10, 4.0])

    def test_reapplying_the_same_grid_adds_nothing(self):
        grid = [0.0, 2.0, 4.0]
        once = merge_grid_markers([], grid)
        twice = merge_grid_markers(once, grid)
        self.assertEqual(once, twice)

    def test_near_duplicates_are_absorbed(self):
        # Un marqueur pose a la main a 2.0009 s ne doit pas se doubler.
        merged = merge_grid_markers([2.0009], [2.0])
        self.assertEqual(merged, [2.0009])

    def test_result_stays_sorted(self):
        merged = merge_grid_markers([5.0, 1.0], [3.0, 7.0])
        self.assertEqual(merged, sorted(merged))


class _StubWidget:
    """Waveform reduite aux attributs que lit le choix du point de depart."""

    def __init__(self, markers=(), play_start=0.0):
        self.markers = list(markers)
        self.play_start = play_start


class GridOriginTests(unittest.TestCase):
    """Le depart de la grille : le marqueur pose avant le curseur, sinon le
    curseur lui-meme. C'est le geste vise — poser un marqueur sur le premier
    temps, puis extrapoler."""

    def setUp(self):
        from frontend.sample_gui.waveform.waveform_markers import (
            WaveformMarkersController,
        )

        self._controller_cls = WaveformMarkersController

    def _origin(self, widget) -> float:
        controller = self._controller_cls.__new__(self._controller_cls)
        controller.widget = widget
        return self._controller_cls.grid_origin_s(controller)

    def test_uses_the_marker_before_the_cursor(self):
        widget = _StubWidget(markers=[0.5, 2.0, 6.0], play_start=3.2)
        self.assertEqual(self._origin(widget), 2.0)

    def test_uses_a_marker_exactly_under_the_cursor(self):
        widget = _StubWidget(markers=[0.5, 2.0], play_start=2.0)
        self.assertEqual(self._origin(widget), 2.0)

    def test_falls_back_to_the_cursor_without_a_marker_before_it(self):
        widget = _StubWidget(markers=[5.0], play_start=1.25)
        self.assertEqual(self._origin(widget), 1.25)

    def test_falls_back_to_zero_without_anything(self):
        self.assertEqual(self._origin(_StubWidget()), 0.0)


if __name__ == "__main__":
    unittest.main()
