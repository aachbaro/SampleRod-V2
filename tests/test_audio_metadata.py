from __future__ import annotations

import io
import subprocess
import unittest
from unittest import mock

import numpy as np

import backend.services.audio_metadata as audio_metadata


class _FakeProcess:
    def __init__(self, payload: bytes, returncode: int = 0):
        self.stdout = io.BytesIO(payload)
        self.stderr = io.BytesIO(b"")
        self._returncode = returncode
        self.killed = False

    def wait(self):
        return self._returncode

    def kill(self):
        self.killed = True


class AudioMetadataTests(unittest.TestCase):
    def test_ffmpeg_fallback_uses_hidden_process_and_computes_duration_and_rms(self):
        samples = np.array([0.5, -0.5, 0.5, -0.5], dtype=np.float32)
        fake_process = _FakeProcess(samples.tobytes())
        popen_kwargs = {}

        def _fake_popen(*args, **kwargs):
            popen_kwargs.update(kwargs)
            return fake_process

        with mock.patch.object(audio_metadata, "_resolve_ffmpeg_executable", return_value="ffmpeg.exe"):
            with mock.patch.object(audio_metadata.subprocess, "Popen", side_effect=_fake_popen):
                duration, rms_level = audio_metadata._probe_with_fallback(
                    "dummy.m4a",
                    include_rms=True,
                )

        self.assertAlmostEqual(duration or 0.0, 4 / audio_metadata._FFMPEG_MONO_RATE)
        self.assertAlmostEqual(rms_level or 0.0, 0.5, places=6)
        self.assertEqual(
            popen_kwargs.get("creationflags", None),
            getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


if __name__ == "__main__":
    unittest.main()
