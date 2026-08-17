from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
import soundfile as sf

from backend.models.normalize_worker import (
    NormalizeWorker, _apply_rms_normalization, supports_in_place_normalization,
)


class _FakeMeter:
    def integrated_loudness(self, _data):
        raise ValueError("Audio must have length greater than the block size.")


class _FakePyLoudnorm:
    normalize = SimpleNamespace(loudness=lambda data, _loudness, _target_db: data)

    @staticmethod
    def Meter(_sample_rate):
        return _FakeMeter()


class NormalizeWorkerTests(unittest.TestCase):
    def test_in_place_normalization_is_limited_to_wav_container(self):
        self.assertTrue(supports_in_place_normalization("sample.wav"))
        self.assertFalse(supports_in_place_normalization("sample.mp3"))
        self.assertFalse(supports_in_place_normalization("sample.flac"))

    def test_rms_normalization_ignores_empty_audio(self):
        empty = np.empty((0, 1), dtype=np.float32)
        normalized = _apply_rms_normalization(empty, -16.0)
        self.assertEqual(normalized.shape, empty.shape)

    def test_empty_file_emits_failure_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.wav")
            sf.write(path, np.empty((0,), dtype=np.float32), 44100)

            worker = NormalizeWorker(sample_id=7, file_path=path, mode="lufs", target_db=-14.0)
            failures: list[tuple[int, str]] = []
            finished: list[int] = []
            worker.normalizationFailed.connect(lambda sample_id, message: failures.append((sample_id, message)))
            worker.finishedNormalization.connect(lambda sample_id: finished.append(sample_id))

            worker.run()

            self.assertEqual(finished, [])
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], 7)
            self.assertIn("vide", failures[0][1].lower())

    def test_short_lufs_file_falls_back_to_rms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "short.wav")
            data = np.linspace(-0.2, 0.2, 16, dtype=np.float32)
            sf.write(path, data, 44100)

            worker = NormalizeWorker(sample_id=9, file_path=path, mode="lufs", target_db=-14.0)
            failures: list[tuple[int, str]] = []
            finished: list[int] = []
            worker.normalizationFailed.connect(lambda sample_id, message: failures.append((sample_id, message)))
            worker.finishedNormalization.connect(lambda sample_id: finished.append(sample_id))

            with mock.patch("backend.models.normalize_worker._get_pyloudnorm", return_value=_FakePyLoudnorm()):
                worker.run()

            self.assertEqual(failures, [])
            self.assertEqual(finished, [9])


if __name__ == "__main__":
    unittest.main()
