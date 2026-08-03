from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from backend.services.drum_analysis_service import (
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    DrumAnalysisService,
    DrumSlice,
)

_SR = 44100


def _click(duration_s: float, freq: float, decay: float) -> np.ndarray:
    """Petit transitoire synthetique : attaque nette puis decroissance."""
    n = int(duration_s * _SR)
    t = np.arange(n, dtype="float32") / _SR
    return (np.sin(2 * np.pi * freq * t) * np.exp(-decay * t)).astype("float32")


def _slice(index: int, start_s: float, end_s: float, label: str) -> DrumSlice:
    return DrumSlice(
        index=index, start_s=start_s, end_s=end_s, label=label, confidence=0.5,
        role="groove", rhythmic_position="subdivision", secondary_labels=(),
        layer_score=0.0,
    )


class BreakSliceEditsTests(unittest.TestCase):
    """Editions de la liste de slices sans re-analyse complete."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = str(Path(self._tmp.name) / "break.wav")
        # Trois coups : grave, aigu, grave.
        audio = np.concatenate([
            _click(0.25, 60.0, 25.0),
            _click(0.25, 6000.0, 60.0),
            _click(0.25, 55.0, 25.0),
        ])
        sf.write(self.source, audio, _SR)
        self.service = DrumAnalysisService(None)
        self.result = DrumAnalysisResult(
            source_path=self.source, label="break", family="drum", form="loop",
            confidence=0.8, duration_s=0.75, sample_rate=_SR, tempo_bpm=90.0,
            pulse_score=0.5, regularity=0.5, onset_count=3,
            split_density=DEFAULT_SPLIT_DENSITY, candidates=(),
            slices=(
                _slice(1, 0.00, 0.25, "kick"),
                _slice(2, 0.25, 0.50, "closed_hat"),
                _slice(3, 0.50, 0.75, "kick"),
            ),
        )

    # -- Fusion (suppression d'une slice) -----------------------------------
    def test_removing_a_slice_merges_it_into_the_previous_one(self):
        merged = self.service.merge_slice_into_previous(self.result, 2)
        self.assertIsNotNone(merged)
        self.assertEqual(len(merged.slices), 2)
        first = merged.slices[0]
        # La slice 1 garde sa classe et s'etend jusqu'a la fin de l'ancienne 2.
        self.assertEqual(first.label, "kick")
        self.assertAlmostEqual(first.start_s, 0.00, places=6)
        self.assertAlmostEqual(first.end_s, 0.50, places=6)
        # Aucun trou : la suivante enchaine.
        self.assertAlmostEqual(merged.slices[1].start_s, 0.50, places=6)

    def test_removing_the_first_slice_merges_into_the_next(self):
        merged = self.service.merge_slice_into_previous(self.result, 1)
        self.assertIsNotNone(merged)
        self.assertEqual(len(merged.slices), 2)
        self.assertAlmostEqual(merged.slices[0].start_s, 0.00, places=6)
        self.assertEqual(merged.slices[0].label, "closed_hat")

    def test_indices_are_renumbered_after_a_merge(self):
        merged = self.service.merge_slice_into_previous(self.result, 2)
        self.assertEqual([s.index for s in merged.slices], [1, 2])

    def test_merge_refuses_when_a_single_slice_is_left(self):
        single = replace(self.result, slices=(_slice(1, 0.0, 0.75, "kick"),))
        self.assertIsNone(self.service.merge_slice_into_previous(single, 1))

    def test_merge_ignores_an_unknown_index(self):
        self.assertIsNone(self.service.merge_slice_into_previous(self.result, 99))

    # -- Ajout d'un marqueur ------------------------------------------------
    def test_adding_a_marker_splits_and_classifies_in_place(self):
        updated = self.service.split_slice_at(self.result, 0.125)
        self.assertIsNotNone(updated)
        self.assertEqual(len(updated.slices), 4)
        # La nouvelle frontiere est a la bonne place dans la liste.
        self.assertAlmostEqual(updated.slices[0].end_s, 0.125, places=6)
        self.assertAlmostEqual(updated.slices[1].start_s, 0.125, places=6)
        self.assertEqual([s.index for s in updated.slices], [1, 2, 3, 4])
        # Les deux moities ont recu une classe detectee (pas une copie vide).
        self.assertTrue(all(s.label for s in updated.slices[:2]))

    def test_split_outside_any_slice_is_refused(self):
        self.assertIsNone(self.service.split_slice_at(self.result, 5.0))

    def test_split_on_an_existing_boundary_is_refused(self):
        self.assertIsNone(self.service.split_slice_at(self.result, 0.25))

    # -- Deplacement d'un marqueur ------------------------------------------
    def test_moving_a_marker_moves_both_neighbouring_boundaries(self):
        updated = self.service.move_slice_boundary(self.result, 0.25, 0.30)
        self.assertIsNotNone(updated)
        self.assertEqual(len(updated.slices), 3)
        self.assertAlmostEqual(updated.slices[0].end_s, 0.30, places=6)
        self.assertAlmostEqual(updated.slices[1].start_s, 0.30, places=6)
        # Les slices non concernees ne bougent pas.
        self.assertAlmostEqual(updated.slices[2].start_s, 0.50, places=6)

    def test_moving_a_marker_past_a_neighbour_is_refused(self):
        # 0.60 depasserait la fin de la slice 2 (0.50).
        self.assertIsNone(self.service.move_slice_boundary(self.result, 0.25, 0.60))

    def test_moving_an_unknown_boundary_is_refused(self):
        self.assertIsNone(self.service.move_slice_boundary(self.result, 0.42, 0.44))

    def test_moving_a_boundary_reclassifies_the_two_slices(self):
        updated = self.service.move_slice_boundary(self.result, 0.25, 0.30)
        # Les deux slices touchees portent une classe issue de la mesure, pas
        # forcement identique a l'ancienne etiquette posee a la main.
        self.assertTrue(updated.slices[0].label)
        self.assertTrue(updated.slices[1].label)

    # -- Coherence avec le generateur ---------------------------------------
    def test_prototype_hits_follow_the_new_cutting(self):
        analyzer_result = self.service.split_slice_at(self.result, 0.125)
        # Sans prototype d'origine, il n'y a rien a resynchroniser : le
        # decoupage des slices reste la source de verite.
        self.assertIsNone(analyzer_result.prototype_result)
        self.assertEqual(analyzer_result.onset_count, len(analyzer_result.slices))


class ClassifySegmentTests(unittest.TestCase):
    """Le point d'entree de classification d'un segment isole."""

    def test_classifies_a_low_and_a_high_transient_differently(self):
        from prototypes.drum_detector import analyzer

        low = _click(0.25, 60.0, 25.0)
        high = _click(0.25, 7000.0, 70.0)
        audio = np.concatenate([low, high])
        low_hit = analyzer.classify_segment(audio, _SR, 0.0, 0.25)
        high_hit = analyzer.classify_segment(audio, _SR, 0.25, 0.50)
        self.assertTrue(low_hit.label)
        self.assertTrue(high_hit.label)
        # Le contenu spectral doit se refleter dans les ratios mesures.
        self.assertGreater(low_hit.low_ratio, high_hit.low_ratio)

    def test_empty_segment_raises(self):
        from prototypes.drum_detector import analyzer

        audio = _click(0.25, 60.0, 25.0)
        with self.assertRaises(ValueError):
            analyzer.classify_segment(audio, _SR, 0.20, 0.20000001)


if __name__ == "__main__":
    unittest.main()
