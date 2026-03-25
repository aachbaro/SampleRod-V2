from __future__ import annotations

import tempfile
import unittest
import warnings

import numpy as np
import soundfile as sf

def _silence_test_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r"n_fft=.*too large for input signal of length=.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        category=UserWarning,
        module=r"librosa\.core\.spectrum",
    )
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"audioread\.rawread",
    )


_silence_test_warnings()

from prototypes.scale_detector.note_segments import detect_note_segments_file


def setUpModule() -> None:
    _silence_test_warnings()


def midi_to_hz(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def synth_note(midi_note: int, *, sample_rate: int = 22050, duration_s: float = 0.32) -> np.ndarray:
    freq = midi_to_hz(midi_note)
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
    envelope = np.ones_like(t)
    attack = max(1, int(sample_rate * 0.01))
    release = max(1, int(sample_rate * 0.03))
    envelope[:attack] = np.linspace(0.0, 1.0, attack, endpoint=False)
    envelope[-release:] = np.linspace(1.0, 0.0, release, endpoint=False)
    tone = (
        (0.75 * np.sin(2.0 * np.pi * freq * t))
        + (0.2 * np.sin(2.0 * np.pi * (freq * 2.0) * t))
        + (0.05 * np.sin(2.0 * np.pi * (freq * 3.0) * t))
    )
    return (tone * envelope).astype(np.float32)


def synth_chord(midi_notes: list[int], *, sample_rate: int = 22050, duration_s: float = 0.45) -> np.ndarray:
    chord = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
    for midi_note in midi_notes:
        chord += synth_note(midi_note, sample_rate=sample_rate, duration_s=duration_s)
    peak = np.max(np.abs(chord))
    return chord / peak if peak > 0 else chord


class NoteSegmentationTests(unittest.TestCase):
    def test_detects_three_note_segments(self) -> None:
        sample_rate = 22050
        silence = np.zeros(int(sample_rate * 0.03), dtype=np.float32)
        audio = np.concatenate(
            [
                synth_note(60, sample_rate=sample_rate),
                silence,
                synth_note(64, sample_rate=sample_rate),
                silence,
                synth_note(67, sample_rate=sample_rate),
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            sf.write(path, audio, sample_rate)
            segments = detect_note_segments_file(path)
        finally:
            import os

            if os.path.exists(path):
                os.remove(path)

        labels = [segment.label for segment in segments]
        self.assertEqual(labels, ["C4", "E4", "G4"])

    def test_detects_polyphonic_chord_segment(self) -> None:
        sample_rate = 22050
        audio = synth_chord([60, 64, 67], sample_rate=sample_rate)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            sf.write(path, audio, sample_rate)
            segments = detect_note_segments_file(path)
        finally:
            import os

            if os.path.exists(path):
                os.remove(path)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "poly")
        self.assertEqual(segments[0].active_notes, ("C", "E", "G"))
        self.assertEqual(segments[0].label, "C+E+G")


if __name__ == "__main__":
    unittest.main()
