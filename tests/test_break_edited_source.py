from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

from backend.services.drum_analysis_service import DrumAnalysisService

BreakWidget = importlib.import_module("frontend.labo.break.break_widget").BreakWidget

_SR = 44100


class _FakeWaveform:
    """Waveform reduite au strict necessaire : le buffer affiche et son taux."""

    def __init__(self, data: np.ndarray, sample_rate: int = _SR):
        self.waveform_data = data
        self.sample_rate = sample_rate
        self.duration = float(data.shape[0]) / sample_rate


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


class BreakEditedSourceTests(unittest.TestCase):
    """Une waveform editee n'est qu'en memoire : l'analyse, la quantize, le
    rendu et le drag d'une slice relisent tous le fichier source. Sans
    materialisation, couper la waveform sortait des slices hors du break vu."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = str(Path(self._tmp.name) / "break.wav")
        # 2 secondes stereo, comme un vrai fichier ouvert dans le Labo.
        self.full = np.tile(
            np.sin(2 * np.pi * 110.0 * np.arange(2 * _SR, dtype="float32") / _SR)[:, None],
            (1, 2),
        ).astype("float32")
        sf.write(self.source, self.full, _SR)

        self.widget = BreakWidget(_Ctx())
        self.addCleanup(self.widget.deleteLater)
        self.widget._current_path = self.source
        self.widget._working_path = self.source

    def _set_buffer(self, data: np.ndarray) -> None:
        self.widget._waveform_widget = _FakeWaveform(data)

    def test_untouched_waveform_analyses_the_original_file(self):
        self._set_buffer(self.full)
        self.assertEqual(self.widget.analysis._resolve_working_path(), self.source)

    def test_cut_waveform_is_materialised_before_analysis(self):
        half = self.full[: self.full.shape[0] // 2]
        self._set_buffer(half)
        resolved = self.widget.analysis._resolve_working_path()

        self.assertNotEqual(resolved, self.source)
        self.assertIn("break_edits", resolved)
        info = sf.info(resolved)
        self.assertEqual(int(info.frames), half.shape[0])
        self.assertEqual(int(info.samplerate), _SR)
        self.assertEqual(int(info.channels), 2)
        # Le widget retient ce chemin pour les consommateurs suivants.
        self.assertEqual(self.widget._working_path, resolved)

    def test_materialised_audio_is_the_displayed_audio(self):
        half = self.full[: self.full.shape[0] // 2]
        self._set_buffer(half)
        resolved = self.widget.analysis._resolve_working_path()
        written, _sr = sf.read(resolved, dtype="float32", always_2d=True)
        np.testing.assert_allclose(written, half, atol=1e-6)

    def test_second_call_reuses_the_materialised_file(self):
        half = self.full[: self.full.shape[0] // 2]
        self._set_buffer(half)
        first = self.widget.analysis._resolve_working_path()
        second = self.widget.analysis._resolve_working_path()
        self.assertEqual(first, second)

    def test_editing_again_produces_a_new_source(self):
        self._set_buffer(self.full[: self.full.shape[0] // 2])
        first = self.widget.analysis._resolve_working_path()
        self._set_buffer(self.full[: self.full.shape[0] // 4])
        second = self.widget.analysis._resolve_working_path()
        self.assertNotEqual(first, second)
        self.assertEqual(int(sf.info(second).frames), self.full.shape[0] // 4)

    def test_results_stamped_with_the_edited_source_are_accepted(self):
        # Les resultats reviennent estampilles avec le chemin temporaire :
        # _matches_path doit les reconnaitre, sinon ils sont ignores.
        self._set_buffer(self.full[: self.full.shape[0] // 2])
        resolved = self.widget.analysis._resolve_working_path()
        self.assertTrue(self.widget._matches_path(resolved))
        self.assertTrue(self.widget._matches_path(self.source))
        self.assertFalse(self.widget._matches_path(str(Path(self._tmp.name) / "autre.wav")))

    def test_mono_buffer_is_written_as_mono(self):
        mono = self.full[: self.full.shape[0] // 2, 0]
        self._set_buffer(mono)
        resolved = self.widget.analysis._resolve_working_path()
        self.assertEqual(int(sf.info(resolved).channels), 1)


if __name__ == "__main__":
    unittest.main()
