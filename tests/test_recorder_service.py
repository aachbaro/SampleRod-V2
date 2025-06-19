import os
import sys
import wave
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytest.importorskip("PyQt6")

from backend.services.recorder_service import RecorderService


def _write_wav(path, frames):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(frames)


def test_is_wav_silent_true(tmp_path):
    silent = bytes([0]*100)
    f = tmp_path / "silent.wav"
    _write_wav(str(f), silent)
    assert RecorderService._is_wav_silent(str(f)) is True


def test_is_wav_silent_false(tmp_path):
    data = bytearray([0]*98 + [1, 0])
    f = tmp_path / "sound.wav"
    _write_wav(str(f), data)
    assert RecorderService._is_wav_silent(str(f)) is False
