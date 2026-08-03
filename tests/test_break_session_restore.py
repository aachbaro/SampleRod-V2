from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from PySide6.QtWidgets import QApplication

from backend.services.drum_analysis_service import (
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    DrumAnalysisService,
    DrumSlice,
)

# `break` est un mot-cle Python : import par importlib.
BreakWidget = importlib.import_module("frontend.labo.break.break_widget").BreakWidget

_STARTS = (0.100, 0.350, 0.720, 1.040)


def _analysis(source_path: str) -> DrumAnalysisResult:
    slices = tuple(
        DrumSlice(
            index=index,
            start_s=start,
            end_s=start + 0.05,
            label=label,
            confidence=0.5,
            role="groove",
            rhythmic_position="subdivision",
            secondary_labels=(),
            layer_score=0.0,
        )
        for index, (start, label) in enumerate(
            zip(_STARTS, ("kick", "closed_hat", "snare", "closed_hat")), start=1
        )
    )
    return DrumAnalysisResult(
        source_path=source_path,
        label="break", family="drum", form="loop", confidence=0.8,
        duration_s=2.0, sample_rate=44100, tempo_bpm=90.0, pulse_score=0.5,
        regularity=0.5, onset_count=len(slices), split_density=DEFAULT_SPLIT_DENSITY,
        candidates=(), slices=slices,
    )


class _Player:
    current_sample_path = ""

    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Ctx:
    def __init__(self):
        self.drum_analysis = DrumAnalysisService(None)
        self.audio_player = _Player()
        self.settings = None
        self.sample_store = None


class BreakSessionRestoreTests(unittest.TestCase):
    """Regression : la restauration de session ne doit pas jeter l'analyse.

    `BreakModule.restore_state` fait `open_file(path)` puis `set_markers(...)`.
    Les marqueurs sauvegardes SONT le decoupage de l'analyse restauree depuis
    le cache ; les reposer effacait l'analyse, donc la liste des slices et
    leur classification, a chaque redemarrage de l'application.
    """

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(
            DrumAnalysisService,
            "_manual_labels_dir",
            new_callable=PropertyMock,
            return_value=Path(self._tmp.name) / "labels",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.source = str(Path(self._tmp.name) / "break.wav")
        self.widget = BreakWidget(_Ctx())
        self.addCleanup(self.widget.deleteLater)
        self.widget._current_path = self.source
        self.widget._analysis_result = _analysis(self.source)
        # La waveform est consideree prete : on teste la decision, pas le rendu.
        self.widget._waveform_ready = lambda: True
        self.widget.markers.set_markers = lambda _markers: None

    def test_session_markers_matching_the_analysis_keep_it(self):
        restored = self.widget._analysis_result
        self.widget.set_markers(list(_STARTS))
        self.assertIs(self.widget._analysis_result, restored)
        self.assertEqual(len(self.widget._analysis_result.slices), len(_STARTS))

    def test_markers_in_any_order_still_match(self):
        restored = self.widget._analysis_result
        self.widget.set_markers(list(reversed(_STARTS)))
        self.assertIs(self.widget._analysis_result, restored)

    def test_a_moved_marker_still_invalidates_the_analysis(self):
        moved = list(_STARTS)
        moved[2] += 0.25
        self.widget.set_markers(moved)
        self.assertIsNone(self.widget._analysis_result)
        self.assertIn("Relance l'analyse", self.widget.status_label.text())

    def test_an_extra_marker_still_invalidates_the_analysis(self):
        self.widget.set_markers([*_STARTS, 1.500])
        self.assertIsNone(self.widget._analysis_result)

    def test_markers_without_any_analysis_are_applied_normally(self):
        self.widget._analysis_result = None
        self.widget.set_markers(list(_STARTS))
        self.assertIsNone(self.widget._analysis_result)
        self.assertIn("Marqueurs restaures", self.widget.status_label.text())


if __name__ == "__main__":
    unittest.main()
