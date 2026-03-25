from __future__ import annotations

import unittest
import warnings

import numpy as np

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
        module=r"librosa\.core\.intervals",
    )
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"audioread\.rawread",
    )


_silence_test_warnings()


def setUpModule() -> None:
    _silence_test_warnings()

from prototypes.scale_detector.analyzer import detect_scale_from_audio


def midi_to_hz(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def synth_note(midi_note: int, *, sample_rate: int = 22050, duration_s: float = 0.35) -> np.ndarray:
    freq = midi_to_hz(midi_note)
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
    envelope = np.ones_like(t)
    attack = max(1, int(sample_rate * 0.01))
    release = max(1, int(sample_rate * 0.04))
    envelope[:attack] = np.linspace(0.0, 1.0, attack, endpoint=False)
    envelope[-release:] = np.linspace(1.0, 0.0, release, endpoint=False)

    tone = (
        (0.75 * np.sin(2.0 * np.pi * freq * t))
        + (0.2 * np.sin(2.0 * np.pi * (freq * 2.0) * t))
        + (0.05 * np.sin(2.0 * np.pi * (freq * 3.0) * t))
    )
    return (tone * envelope).astype(np.float32)


def synth_sequence(
    midi_notes: list[int],
    *,
    sample_rate: int = 22050,
    note_duration_s: float = 0.28,
    gap_s: float = 0.03,
) -> np.ndarray:
    parts: list[np.ndarray] = []
    gap = np.zeros(int(sample_rate * gap_s), dtype=np.float32)
    for index, midi_note in enumerate(midi_notes):
        parts.append(synth_note(midi_note, sample_rate=sample_rate, duration_s=note_duration_s))
        if index != len(midi_notes) - 1:
            parts.append(gap)
    signal = np.concatenate(parts)
    peak = np.max(np.abs(signal))
    return signal / peak


class ScaleDetectorTests(unittest.TestCase):
    sample_rate = 22050

    def test_detects_c_major_scale(self) -> None:
        audio = synth_sequence([60, 62, 64, 65, 67, 69, 71, 72], sample_rate=self.sample_rate)
        result = detect_scale_from_audio(audio, self.sample_rate)

        self.assertEqual(result.kind, "scale")
        self.assertEqual(result.candidates[0].label, "C major")
        self.assertEqual(result.label, "C major")

    def test_detects_a_natural_minor_scale(self) -> None:
        audio = synth_sequence([57, 59, 60, 62, 64, 65, 67, 69], sample_rate=self.sample_rate)
        result = detect_scale_from_audio(audio, self.sample_rate)

        self.assertEqual(result.kind, "scale")
        self.assertEqual(result.candidates[0].label, "A natural minor")
        self.assertEqual(result.label, "A natural minor")

    def test_detects_c_major_pentatonic_scale(self) -> None:
        audio = synth_sequence([60, 62, 64, 67, 69, 72], sample_rate=self.sample_rate)
        result = detect_scale_from_audio(audio, self.sample_rate)

        self.assertEqual(result.kind, "scale")
        self.assertEqual(result.candidates[0].label, "C major pentatonic")
        self.assertEqual(result.label, "C major pentatonic")

    def test_single_note_returns_note_guess(self) -> None:
        audio = synth_note(69, sample_rate=self.sample_rate, duration_s=1.1)
        result = detect_scale_from_audio(audio, self.sample_rate)

        self.assertEqual(result.kind, "note")
        self.assertEqual(result.label, "A")
        self.assertEqual(result.dominant_note, "A")


if __name__ == "__main__":
    unittest.main()
