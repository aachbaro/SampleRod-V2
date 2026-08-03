"""Grille au tempo reglable en direct : maths, session, et cout de pose.

Le point sensible est la PERFORMANCE : poser 200 marqueurs reconstruisait la
liste 200 fois en recopiant l'audio a chaque tour, ce qui gelait l'interface
plusieurs secondes. Les tests de cout ci-dessous verrouillent le correctif.
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QListWidget
import pyqtgraph as pg

from frontend.sample_gui.marker_manager import MarkerManager, materialize_slice_payload
from frontend.sample_gui.waveform.waveform_grid import (
    bpm_from_span,
    grid_marker_times,
    shift_grid_times,
    slice_duration_s,
)
from frontend.sample_gui.waveform.waveform_grid_session import GridSession, GridSettings

_app = QApplication.instance() or QApplication([])


class TempoFromSpanTests(unittest.TestCase):
    """Deduire le tempo d'un passage dont on affirme le nombre de steps."""

    def test_one_bar_of_two_seconds_is_120_bpm(self):
        # 16 steps en 2 s -> 120 BPM.
        self.assertAlmostEqual(bpm_from_span(2.0, 16), 120.0)

    def test_half_the_span_doubles_the_tempo(self):
        self.assertAlmostEqual(bpm_from_span(1.0, 16), 240.0)

    def test_two_bars_over_the_same_span_double_the_tempo(self):
        self.assertAlmostEqual(bpm_from_span(2.0, 32), 240.0)

    def test_it_is_the_inverse_of_slice_duration(self):
        # Aller-retour : un tempo deduit doit reproduire la duree de depart.
        span = slice_duration_s(174.0, 16)
        self.assertAlmostEqual(bpm_from_span(span, 16), 174.0, places=6)

    def test_a_degenerate_span_has_no_tempo(self):
        self.assertEqual(bpm_from_span(0.0, 16), 0.0)
        self.assertEqual(bpm_from_span(2.0, 0), 0.0)


class GridSpreadsBothWaysTests(unittest.TestCase):
    """L'ancrage n'est pas un debut : la grille couvre tout le fichier.

    Le geste vise : caler sur un passage franc en plein milieu du morceau,
    plutot que d'avoir a identifier le tout premier temps — justement le
    passage le moins lisible d'un enregistrement.
    """

    def test_an_anchor_mid_file_slices_before_and_after(self):
        times = grid_marker_times(
            origin_s=5.0, bpm=120.0, steps_per_slice=16, duration_s=10.0
        )
        # Tranches de 2 s, ancrage a 5 s : 1.0 et 3.0 en amont, 7.0 et 9.0 apres.
        self.assertEqual([round(t, 3) for t in times], [1.0, 3.0, 5.0, 7.0, 9.0])

    def test_the_anchor_is_always_on_the_grid(self):
        times = grid_marker_times(
            origin_s=5.0, bpm=120.0, steps_per_slice=16, duration_s=10.0
        )
        self.assertIn(5.0, times)

    def test_the_result_stays_sorted(self):
        times = grid_marker_times(
            origin_s=7.3, bpm=174.0, steps_per_slice=16, duration_s=20.0
        )
        self.assertEqual(times, sorted(times))

    def test_nothing_is_placed_before_the_file_starts(self):
        times = grid_marker_times(
            origin_s=5.0, bpm=120.0, steps_per_slice=16, duration_s=10.0
        )
        self.assertTrue(all(t >= 0.0 for t in times))

    def test_an_anchor_at_zero_only_goes_forward(self):
        times = grid_marker_times(
            origin_s=0.0, bpm=120.0, steps_per_slice=16, duration_s=8.0
        )
        self.assertEqual([round(t, 3) for t in times], [0.0, 2.0, 4.0, 6.0])

    def test_upstream_spacing_matches_downstream(self):
        times = grid_marker_times(
            origin_s=5.0, bpm=120.0, steps_per_slice=16, duration_s=10.0
        )
        gaps = [round(b - a, 6) for a, b in zip(times, times[1:])]
        self.assertEqual(set(gaps), {2.0})

    def test_extension_can_be_turned_off(self):
        times = grid_marker_times(
            origin_s=5.0, bpm=120.0, steps_per_slice=16, duration_s=10.0,
            extend_before=False,
        )
        self.assertEqual([round(t, 3) for t in times], [5.0, 7.0, 9.0])

    def test_a_late_anchor_still_fills_the_whole_file(self):
        # Ancrage a 19 s sur 20 s : presque tout est en amont.
        times = grid_marker_times(
            origin_s=19.0, bpm=120.0, steps_per_slice=16, duration_s=20.0
        )
        self.assertEqual([round(t, 3) for t in times], [1.0, 3.0, 5.0, 7.0, 9.0,
                                                        11.0, 13.0, 15.0, 17.0, 19.0])


class GridSessionSpreadTests(unittest.TestCase):
    """Le decalage re-ancre la grille au lieu de la translater."""

    def test_offsetting_keeps_covering_the_whole_file(self):
        session = GridSession(origin_s=5.0, duration_s=10.0)
        base = session.planned_times(GridSettings(bpm=120.0, steps_per_slice=16))
        shifted = session.planned_times(
            GridSettings(bpm=120.0, steps_per_slice=16, offset_s=0.5)
        )
        # Meme couverture, juste decalee : on ne perd pas le marqueur du bord.
        self.assertEqual(len(base), len(shifted))
        self.assertEqual([round(t, 3) for t in shifted], [1.5, 3.5, 5.5, 7.5, 9.5])

    def test_a_negative_offset_also_stays_covered(self):
        session = GridSession(origin_s=5.0, duration_s=10.0)
        shifted = session.planned_times(
            GridSettings(bpm=120.0, steps_per_slice=16, offset_s=-0.5)
        )
        self.assertEqual([round(t, 3) for t in shifted], [0.5, 2.5, 4.5, 6.5, 8.5])


class ShiftGridTests(unittest.TestCase):
    """Translation d'une grille entiere."""

    def test_every_marker_moves_by_the_same_amount(self):
        self.assertEqual(shift_grid_times([0.0, 2.0, 4.0], 0.25, 10.0), [0.25, 2.25, 4.25])

    def test_markers_pushed_before_zero_are_dropped(self):
        self.assertEqual(shift_grid_times([0.0, 2.0], -0.5, 10.0), [1.5])

    def test_markers_pushed_past_the_end_are_dropped(self):
        self.assertEqual(shift_grid_times([0.0, 9.5], 1.0, 10.0), [1.0])

    def test_a_null_shift_changes_nothing(self):
        self.assertEqual(shift_grid_times([0.0, 2.0], 0.0, 10.0), [0.0, 2.0])


class GridSessionTests(unittest.TestCase):
    """L'etat 'grille en cours de reglage'."""

    def _session(self):
        return GridSession(origin_s=0.0, duration_s=8.0)

    def test_planned_times_follow_the_settings(self):
        session = self._session()
        times = session.planned_times(GridSettings(bpm=120.0, steps_per_slice=16))
        self.assertEqual([round(t, 3) for t in times], [0.0, 2.0, 4.0, 6.0])

    def test_the_offset_moves_the_whole_grid(self):
        session = self._session()
        times = session.planned_times(
            GridSettings(bpm=120.0, steps_per_slice=16, offset_s=0.5)
        )
        self.assertEqual([round(t, 3) for t in times], [0.5, 2.5, 4.5, 6.5])

    def test_only_the_offset_changing_is_detected(self):
        session = self._session()
        session.opened([0.0, 2.0], GridSettings(bpm=120.0, steps_per_slice=16))
        same_shape = GridSettings(bpm=120.0, steps_per_slice=16, offset_s=0.3)
        self.assertTrue(session.is_offset_only(same_shape))
        self.assertAlmostEqual(session.offset_delta(same_shape), 0.3)

    def test_a_tempo_change_is_not_offset_only(self):
        session = self._session()
        session.opened([0.0, 2.0], GridSettings(bpm=120.0, steps_per_slice=16))
        self.assertFalse(session.is_offset_only(GridSettings(bpm=140.0, steps_per_slice=16)))

    def test_a_steps_change_is_not_offset_only(self):
        session = self._session()
        session.opened([0.0, 2.0], GridSettings(bpm=120.0, steps_per_slice=16))
        self.assertFalse(session.is_offset_only(GridSettings(bpm=120.0, steps_per_slice=32)))

    def test_an_idle_session_is_never_offset_only(self):
        # Rien n'est pose : il faut une pose complete, pas une translation.
        self.assertFalse(self._session().is_offset_only(GridSettings()))

    def test_closing_forgets_what_it_owned(self):
        session = self._session()
        session.opened([0.0, 2.0], GridSettings())
        session.closed()
        self.assertEqual(session.owned, ())
        self.assertFalse(session.active)


class _StubRegion:
    """Region minimale : juste ses bornes."""

    def __init__(self, start, end):
        self._bounds = (float(start), float(end))

    def getRegion(self):
        return self._bounds


class _StubWidget:
    """Le minimum que MarkerManager touche."""

    def __init__(self, duration=30.0, sample_rate=44100):
        self.plot = pg.PlotWidget()
        self.marker_list = QListWidget()
        self.sample_rate = sample_rate
        self.duration = duration
        self.waveform_data = (
            np.random.randn(int(sample_rate * duration), 2) * 0.1
        ).astype("float32")
        self.audio_file_path = "stub.wav"
        self.region = None
        self.markers = []
        self._record_history = False
        self.history = []

    def _push_history(self, cmd):
        self.history.append(cmd)


class LazySlicePayloadTests(unittest.TestCase):
    """Les items de liste ne portent que des bornes, pas des copies d'audio."""

    def setUp(self):
        self.widget = _StubWidget()
        self.manager = MarkerManager(self.widget)

    def test_list_items_carry_bounds_not_audio(self):
        with self.manager.batch_updates():
            for t in (0.0, 1.0, 2.0):
                self.manager.add_marker(t)
        item = self.manager.marker_list.item(0)
        payload = item.data(0x0100)  # Qt.ItemDataRole.UserRole
        self.assertIsNone(payload["audio_data"])
        self.assertEqual(payload["s0"], 0)
        self.assertEqual(payload["s1"], 44100)

    def test_materializing_produces_the_expected_slice(self):
        payload = {"s0": 100, "s1": 400, "audio_data": None}
        resolved = materialize_slice_payload(payload, self.widget.waveform_data)
        self.assertEqual(resolved["audio_data"].shape[0], 300)
        self.assertEqual(resolved["audio_data"].dtype, np.dtype("float32"))

    def test_materializing_twice_keeps_the_first_slice(self):
        payload = {"s0": 0, "s1": 10, "audio_data": None}
        once = materialize_slice_payload(payload, self.widget.waveform_data)
        twice = materialize_slice_payload(once, self.widget.waveform_data)
        self.assertIs(once["audio_data"], twice["audio_data"])

    def test_missing_audio_yields_an_empty_slice(self):
        resolved = materialize_slice_payload({"s0": 0, "s1": 10, "audio_data": None}, None)
        self.assertEqual(resolved["audio_data"].size, 0)


class BatchUpdateTests(unittest.TestCase):
    """La pose groupee ne reconstruit la liste qu'une fois."""

    def setUp(self):
        self.widget = _StubWidget()
        self.manager = MarkerManager(self.widget)

    def test_the_list_is_rebuilt_once_not_per_marker(self):
        calls = {"n": 0}
        real = self.manager.refresh_marker_list

        def counted():
            if self.manager._batch_depth <= 0:
                calls["n"] += 1
            return real()

        self.manager.refresh_marker_list = counted
        with self.manager.batch_updates():
            for i in range(50):
                self.manager.add_marker(i * 0.1)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(self.manager.markers), 50)

    def test_every_marker_still_lands_in_the_list(self):
        with self.manager.batch_updates():
            for i in range(20):
                self.manager.add_marker(i * 0.1)
        # 20 marqueurs, pas de ligne de selection (region None).
        self.assertEqual(self.manager.marker_list.count(), 20)

    def test_nested_batches_only_refresh_at_the_outermost_exit(self):
        with self.manager.batch_updates():
            with self.manager.batch_updates():
                self.manager.add_marker(1.0)
            self.assertEqual(self.manager.marker_list.count(), 0)  # encore suspendu
        self.assertEqual(self.manager.marker_list.count(), 1)


class ShiftMarkersTests(unittest.TestCase):
    """Translation en bloc des lignes deja posees."""

    def setUp(self):
        self.widget = _StubWidget()
        self.manager = MarkerManager(self.widget)
        with self.manager.batch_updates():
            for t in (1.0, 2.0, 3.0):
                self.manager.add_marker(t)

    def test_markers_pushed_out_of_the_file_are_removed_not_stacked(self):
        # Rabattre sur 0 empilerait plusieurs marqueurs au meme endroit et
        # laisserait des lignes orphelines dans le plot.
        moved = self.manager.shift_markers([1.0, 2.0, 3.0], -2.5)
        self.assertEqual([round(t, 3) for t in moved], [0.5])
        self.assertEqual([round(t, 3) for t in self.manager.markers], [0.5])
        self.assertEqual(sorted(round(t, 3) for t in self.manager.marker_lines), [0.5])

    def test_all_markers_move_together(self):
        moved = self.manager.shift_markers([1.0, 2.0, 3.0], 0.5)
        self.assertEqual([round(t, 3) for t in moved], [1.5, 2.5, 3.5])
        self.assertEqual([round(t, 3) for t in self.manager.markers], [1.5, 2.5, 3.5])

    def test_the_plot_lines_follow(self):
        self.manager.shift_markers([1.0, 2.0, 3.0], 0.5)
        self.assertEqual(sorted(round(t, 3) for t in self.manager.marker_lines), [1.5, 2.5, 3.5])
        self.assertAlmostEqual(self.manager.marker_lines[1.5].value(), 1.5)

    def test_untouched_markers_stay_put(self):
        # Un marqueur pose a la main ne doit pas suivre la grille.
        self.manager.add_marker(9.0)
        self.manager.shift_markers([1.0, 2.0], 0.5)
        self.assertIn(9.0, self.manager.markers)

    def test_shifting_nothing_is_a_no_op(self):
        self.assertEqual(self.manager.shift_markers([], 0.5), [])
        self.assertEqual(self.manager.shift_markers([1.0], 0.0), [])


class GridPlacementCostTests(unittest.TestCase):
    """Verrous de performance : la pose de grille doit rester interactive.

    Avant correctif, 213 marqueurs prenaient ~7 s (reconstruction de liste par
    marqueur + recopie integrale de l'audio + auto-range quadratique de
    pyqtgraph). Les seuils sont larges pour rester stables en CI.
    """

    def test_placing_two_hundred_markers_stays_under_a_second(self):
        widget = _StubWidget()
        manager = MarkerManager(widget)
        times = [i * 0.14 for i in range(200)]
        start = time.perf_counter()
        with manager.batch_updates():
            for t in times:
                manager.add_marker(t)
        elapsed = time.perf_counter() - start
        self.assertEqual(len(manager.markers), 200)
        self.assertLess(elapsed, 1.0, f"pose de 200 marqueurs trop lente: {elapsed:.2f}s")

    def test_shifting_two_hundred_markers_is_fast_enough_to_be_live(self):
        widget = _StubWidget()
        manager = MarkerManager(widget)
        times = [i * 0.14 for i in range(200)]
        with manager.batch_updates():
            for t in times:
                manager.add_marker(t)
        start = time.perf_counter()
        manager.shift_markers(list(manager.markers), 0.01)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.35, f"translation trop lente pour du direct: {elapsed:.2f}s")

    def test_refreshing_the_list_never_touches_the_audio(self):
        """Fil-piege : un tableau qui hurle des qu'on le decoupe.

        C'etait la depense dominante — chaque rafraichissement recopiait le
        fichier entier en tranches float32 pour des payloads que personne ne
        lisait tant qu'on ne glissait pas un item.
        """

        class _Tripwire(np.ndarray):
            def __getitem__(self, key):
                if isinstance(key, slice):
                    raise AssertionError("l'audio a ete decoupe pendant un refresh")
                return super().__getitem__(key)

        widget = _StubWidget()
        widget.waveform_data = widget.waveform_data.view(_Tripwire)
        # Une region active force aussi la construction de la ligne de selection.
        widget.region = _StubRegion(1.0, 2.0)
        manager = MarkerManager(widget)
        with manager.batch_updates():
            for i in range(100):
                manager.add_marker(i * 0.2)

        manager.refresh_marker_list()   # ne doit rien decouper

        # ... mais l'audio reste disponible a la demande, au moment du drag.
        payload = manager.marker_list.item(1).data(0x0100)
        raw = np.asarray(widget.waveform_data).view(np.ndarray)
        resolved = materialize_slice_payload(payload, raw)
        self.assertGreater(resolved["audio_data"].size, 0)


if __name__ == "__main__":
    unittest.main()
