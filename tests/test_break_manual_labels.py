from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import PropertyMock, patch

from PySide6.QtWidgets import QApplication

from backend.services.drum_analysis_service import (
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    DrumAnalysisService,
    DrumSlice,
    _load_analyzer_module,
)


def _slice(index: int, start_s: float, label: str) -> DrumSlice:
    return DrumSlice(
        index=index,
        start_s=start_s,
        end_s=start_s + 0.05,
        label=label,
        confidence=0.5,
        role="groove",
        rhythmic_position="subdivision",
        secondary_labels=(),
        layer_score=0.0,
    )


def _result(source_path: str, slices, prototype=None) -> DrumAnalysisResult:
    return DrumAnalysisResult(
        source_path=source_path,
        label="break",
        family="drum",
        form="loop",
        confidence=0.8,
        duration_s=1.0,
        sample_rate=44100,
        tempo_bpm=90.0,
        pulse_score=0.5,
        regularity=0.5,
        onset_count=len(slices),
        split_density=DEFAULT_SPLIT_DENSITY,
        candidates=(),
        slices=tuple(slices),
        prototype_result=prototype,
    )


class BreakManualLabelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Le magasin de corrections est isole du profil utilisateur reel.
        patcher = patch.object(
            DrumAnalysisService,
            "_manual_labels_dir",
            new_callable=PropertyMock,
            return_value=Path(self._tmp.name) / "labels",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DrumAnalysisService(None)
        self.source = str(Path(self._tmp.name) / "break.wav")

    def test_manual_label_survives_a_new_service_instance(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        reloaded = DrumAnalysisService(None).load_manual_labels(self.source)
        self.assertEqual(reloaded, {0.5: "snare"})

    def test_reanalysis_keeps_manual_label_despite_renumbering(self):
        self.service.set_manual_label(self.source, 0.500, "snare")

        # Une re-analyse renumerote les hits et reclasse tout en automatique :
        # un marqueur ajoute en tete decale les index de +1.
        reanalysed = _result(
            self.source,
            [
                _slice(1, 0.100, "kick"),
                _slice(2, 0.500, "closed_hat"),
                _slice(3, 0.900, "closed_hat"),
            ],
        )
        patched = self.service.apply_manual_labels(reanalysed)
        self.assertEqual([s.label for s in patched.slices], ["kick", "snare", "closed_hat"])

    def test_slight_position_drift_still_matches(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        drifted = _result(self.source, [_slice(1, 0.512, "closed_hat")])
        self.assertEqual(self.service.apply_manual_labels(drifted).slices[0].label, "snare")

    def test_distant_hit_is_not_relabelled(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        far = _result(self.source, [_slice(1, 0.800, "closed_hat")])
        self.assertEqual(self.service.apply_manual_labels(far).slices[0].label, "closed_hat")

    def test_correcting_the_same_hit_twice_replaces_the_override(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        self.service.set_manual_label(self.source, 0.508, "clap")
        overrides = self.service.load_manual_labels(self.source)
        self.assertEqual(len(overrides), 1)
        self.assertEqual(list(overrides.values()), ["clap"])

    def test_dropping_a_hit_forgets_only_its_correction(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        self.service.set_manual_label(self.source, 0.900, "clap")
        self.service.drop_manual_label(self.source, 0.502)
        self.assertEqual(self.service.load_manual_labels(self.source), {0.9: "clap"})

    def test_clear_forgets_every_correction(self):
        self.service.set_manual_label(self.source, 0.500, "snare")
        self.service.clear_manual_labels(self.source)
        self.assertEqual(self.service.load_manual_labels(self.source), {})
        untouched = _result(self.source, [_slice(1, 0.500, "closed_hat")])
        self.assertEqual(
            self.service.apply_manual_labels(untouched).slices[0].label, "closed_hat"
        )

    def test_prototype_hits_are_patched_for_the_generator(self):
        analyzer = _load_analyzer_module()
        hits = (
            analyzer.TransientHit(
                index=1, start_s=0.500, end_s=0.550, label="closed_hat",
                confidence=0.5, peak_db=-6.0, low_ratio=0.1, mid_ratio=0.3, high_ratio=0.6,
            ),
        )
        prototype = analyzer.DrumDetectionResult(
            source_path=self.source, loop_score=0.5, drum_score=0.9, break_score=0.7,
            label="break", family="drum", form="loop", confidence=0.8, duration_s=1.0,
            sample_rate=44100, tempo_bpm=90.0, pulse_score=0.5, regularity=0.5,
            onset_count=1, onset_density=1.0, percussive_ratio=0.9, harmonic_ratio=0.1,
            decay_s=0.2, spectral_centroid_hz=3000.0, spectral_flatness=0.3,
            band_energies={}, transient_hits=hits, candidates=(), hit_sequences=(),
        )
        self.service.set_manual_label(self.source, 0.500, "snare")
        patched = self.service.apply_manual_labels(
            _result(self.source, [_slice(1, 0.500, "closed_hat")], prototype)
        )
        self.assertEqual(patched.slices[0].label, "snare")
        self.assertEqual(patched.prototype_result.transient_hits[0].label, "snare")

    def test_result_without_override_is_returned_untouched(self):
        original = _result(self.source, [_slice(1, 0.500, "closed_hat")])
        self.assertIs(self.service.apply_manual_labels(original), original)

    def test_cached_analysis_also_carries_the_correction(self):
        # Le cache d'analyse et le magasin de corrections sont deux choses
        # differentes : une correction doit survivre meme si le cache est jete.
        with patch.object(
            DrumAnalysisService,
            "_cache_dir",
            new_callable=PropertyMock,
            return_value=Path(self._tmp.name) / "cache",
        ):
            base = _result(self.source, [_slice(1, 0.500, "closed_hat")])
            self.service.cache_result(replace(base, slices=(_slice(1, 0.500, "snare"),)))
            self.service.set_manual_label(self.source, 0.500, "snare")
            fresh = DrumAnalysisService(None)
            self.assertEqual(fresh.apply_manual_labels(base).slices[0].label, "snare")


if __name__ == "__main__":
    unittest.main()
