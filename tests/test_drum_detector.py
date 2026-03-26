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
        module=r"audioread\.rawread",
    )


_silence_test_warnings()

from prototypes.drum_detector.analyzer import (
    MAX_SEQUENCE_HIT_COUNT,
    TransientHit,
    _assign_hit_roles,
    _extract_hit_sequences,
    analyze_audio_with_preview,
    detect_drum_from_audio,
    detect_drum_from_markers,
)


def setUpModule() -> None:
    _silence_test_warnings()


def _normalize(signal: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(signal))) or 1.0
    return (signal / peak).astype(np.float32)


def _make_kick(sample_rate: int, *, duration_s: float = 0.42, freq_hz: float = 56.0) -> np.ndarray:
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False, dtype=np.float32)
    body = np.sin(2.0 * np.pi * freq_hz * t) * np.exp(-7.0 * t)
    click = np.zeros_like(body)
    click[: max(1, int(sample_rate * 0.008))] = np.linspace(1.0, 0.0, max(1, int(sample_rate * 0.008)))
    return _normalize((0.85 * body) + (0.25 * click))


def _make_snare(sample_rate: int, *, duration_s: float = 0.24) -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False, dtype=np.float32)
    noise = rng.standard_normal(t.size).astype(np.float32) * np.exp(-18.0 * t)
    tone = 0.25 * np.sin(2.0 * np.pi * 190.0 * t) * np.exp(-12.0 * t)
    return _normalize((0.85 * noise) + tone)


def _make_closed_hat(sample_rate: int, *, duration_s: float = 0.11) -> np.ndarray:
    rng = np.random.default_rng(9)
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False, dtype=np.float32)
    noise = rng.standard_normal(t.size).astype(np.float32)
    high = noise - np.concatenate(([0.0], noise[:-1]))
    return _normalize(high * np.exp(-35.0 * t))


def _place(buffer: np.ndarray, hit: np.ndarray, start_s: float, sample_rate: int) -> None:
    start = int(start_s * sample_rate)
    end = min(buffer.size, start + hit.size)
    buffer[start:end] += hit[: end - start]


class DrumDetectorTests(unittest.TestCase):
    def test_classifies_kick_one_shot(self) -> None:
        sample_rate = 22050
        result = detect_drum_from_audio(_make_kick(sample_rate), sample_rate)
        self.assertEqual(result.form, "one_shot")
        self.assertEqual(result.family, "drum")
        self.assertEqual(result.label, "kick")
        self.assertTrue(result.transient_hits)
        self.assertEqual(result.transient_hits[0].role, "pillar")

    def test_classifies_closed_hat_one_shot(self) -> None:
        sample_rate = 22050
        result = detect_drum_from_audio(_make_closed_hat(sample_rate), sample_rate)
        self.assertEqual(result.form, "one_shot")
        self.assertEqual(result.family, "drum")
        self.assertIn(result.label, {"closed_hat", "open_hat", "crash"})
        self.assertGreaterEqual(result.band_energies["high"], 0.45)

    def test_detects_break_loop_and_transients(self) -> None:
        sample_rate = 22050
        duration_s = 1.4
        audio = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
        kick = _make_kick(sample_rate, duration_s=0.28)
        snare = _make_snare(sample_rate, duration_s=0.18)
        hat = _make_closed_hat(sample_rate, duration_s=0.08)

        for start in (0.0, 0.5, 1.0):
            _place(audio, kick, start, sample_rate)
        for start in (0.25, 0.75):
            _place(audio, snare, start, sample_rate)
        for start in (0.125, 0.375, 0.625, 0.875, 1.125):
            _place(audio, hat, start, sample_rate)

        result = detect_drum_from_audio(_normalize(audio), sample_rate)
        self.assertEqual(result.form, "loop")
        self.assertEqual(result.family, "drum")
        self.assertEqual(result.label, "break")
        self.assertGreaterEqual(result.break_score, 0.5)
        self.assertGreaterEqual(result.onset_count, 9)

        labels = [hit.label for hit in result.transient_hits]
        rhythmic_positions = {hit.rhythmic_position for hit in result.transient_hits}
        self.assertGreaterEqual(sum(1 for label in labels if label == "kick"), 2)
        self.assertGreaterEqual(sum(1 for label in labels if label in {"snare", "clap"}), 1)
        self.assertGreaterEqual(
            sum(1 for label in labels if label in {"closed_hat", "open_hat", "crash"}),
            3,
        )
        self.assertIn("downbeat", rhythmic_positions)
        self.assertIn("backbeat", rhythmic_positions)
        self.assertIn("offbeat", rhythmic_positions)
        roles = {hit.role for hit in result.transient_hits}
        self.assertIn("pillar", roles)
        self.assertTrue({"texture", "accent", "punctuation"} & roles)
        self.assertTrue(result.hit_sequences)
        self.assertTrue(all(2 <= sequence.hit_count <= MAX_SEQUENCE_HIT_COUNT for sequence in result.hit_sequences))
        self.assertTrue(
            {sequence.role for sequence in result.hit_sequences}
            & {"groove", "anticipation", "fill", "cadence"}
        )
        self.assertTrue(all(sequence.events[0].start_offset_steps == 0 for sequence in result.hit_sequences))
        self.assertTrue(
            all(
                event.rhythmic_position in {"downbeat", "backbeat", "offbeat", "subdivision"}
                for sequence in result.hit_sequences
                for event in sequence.events
            )
        )

    def test_recovers_hat_over_kick_tail(self) -> None:
        sample_rate = 22050
        duration_s = 0.45
        audio = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
        kick = _make_kick(sample_rate, duration_s=0.28)
        hat = _make_closed_hat(sample_rate, duration_s=0.08)

        _place(audio, kick, 0.0, sample_rate)
        _place(audio, hat, 0.125, sample_rate)

        result = detect_drum_from_audio(_normalize(audio), sample_rate)
        self.assertGreaterEqual(result.onset_count, 2)
        late_hits = [hit for hit in result.transient_hits if hit.start_s >= 0.09]
        self.assertTrue(late_hits, "expected a second hit after the kick transient")
        self.assertIn(late_hits[0].label, {"closed_hat", "open_hat", "crash"})

    def test_rebuilds_hit_list_from_manual_markers(self) -> None:
        sample_rate = 22050
        duration_s = 0.9
        audio = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
        kick = _make_kick(sample_rate, duration_s=0.24)
        snare = _make_snare(sample_rate, duration_s=0.16)
        hat = _make_closed_hat(sample_rate, duration_s=0.08)

        _place(audio, kick, 0.0, sample_rate)
        _place(audio, snare, 0.25, sample_rate)
        _place(audio, hat, 0.5, sample_rate)

        rebuilt = detect_drum_from_markers(
            _normalize(audio),
            sample_rate,
            marker_times=(0.0, 0.25, 0.5),
        )
        merged = detect_drum_from_markers(
            _normalize(audio),
            sample_rate,
            marker_times=(0.0, 0.5),
        )

        self.assertEqual(rebuilt.onset_count, 3)
        self.assertEqual(merged.onset_count, 2)
        self.assertAlmostEqual(merged.transient_hits[0].start_s, 0.0, places=3)
        self.assertAlmostEqual(merged.transient_hits[0].end_s, 0.5, places=3)
        self.assertAlmostEqual(merged.transient_hits[1].start_s, 0.5, places=3)

    def test_split_density_changes_initial_segmentation(self) -> None:
        sample_rate = 22050
        duration_s = 0.9
        audio = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
        kick = _make_kick(sample_rate, duration_s=0.22)
        hat = _make_closed_hat(sample_rate, duration_s=0.06)

        for start in (0.0, 0.4):
            _place(audio, kick, start, sample_rate)
        for start in (0.055, 0.11, 0.165, 0.455, 0.51, 0.565):
            _place(audio, hat, start, sample_rate)

        sparse = detect_drum_from_audio(_normalize(audio), sample_rate, split_density=10.0)
        dense = detect_drum_from_audio(_normalize(audio), sample_rate, split_density=90.0)

        self.assertGreaterEqual(sparse.onset_count, 2)
        self.assertGreater(dense.onset_count, sparse.onset_count)

    def test_analysis_preview_callback_exposes_marker_times_before_final_result(self) -> None:
        sample_rate = 22050
        duration_s = 1.0
        audio = np.zeros(int(sample_rate * duration_s), dtype=np.float32)
        kick = _make_kick(sample_rate, duration_s=0.24)
        snare = _make_snare(sample_rate, duration_s=0.16)
        hat = _make_closed_hat(sample_rate, duration_s=0.08)

        for start in (0.0, 0.5):
            _place(audio, kick, start, sample_rate)
        _place(audio, snare, 0.25, sample_rate)
        for start in (0.125, 0.375, 0.625, 0.875):
            _place(audio, hat, start, sample_rate)

        previews = []
        result = analyze_audio_with_preview(
            _normalize(audio),
            sample_rate,
            preview_callback=previews.append,
        )

        self.assertEqual(len(previews), 1)
        preview = previews[0]
        self.assertGreaterEqual(preview.onset_count, 6)
        self.assertEqual(len(preview.marker_times), preview.onset_count)
        self.assertLess(preview.marker_times[0], 0.03)
        self.assertEqual(result.onset_count, preview.onset_count)

    def test_sequences_follow_quantized_break_grid_not_raw_audio_offsets(self) -> None:
        hits = [
            TransientHit(
                index=1,
                start_s=0.09,
                end_s=0.15,
                label="kick",
                confidence=0.9,
                peak_db=-3.0,
                low_ratio=0.8,
                mid_ratio=0.15,
                high_ratio=0.05,
            ),
            TransientHit(
                index=2,
                start_s=0.34,
                end_s=0.39,
                label="closed_hat",
                confidence=0.82,
                peak_db=-8.0,
                low_ratio=0.05,
                mid_ratio=0.3,
                high_ratio=0.65,
            ),
            TransientHit(
                index=3,
                start_s=0.59,
                end_s=0.68,
                label="snare",
                confidence=0.88,
                peak_db=-4.0,
                low_ratio=0.15,
                mid_ratio=0.65,
                high_ratio=0.2,
            ),
        ]

        updated_hits = _assign_hit_roles(hits, tempo_bpm=120.0, regularity=0.95)
        sequences = _extract_hit_sequences(
            updated_hits,
            tempo_bpm=120.0,
            regularity=0.95,
            min_len=3,
            max_len=3,
        )

        self.assertEqual(
            [hit.rhythmic_position for hit in updated_hits],
            ["downbeat", "offbeat", "backbeat"],
        )
        self.assertEqual(len(sequences), 1)
        sequence = sequences[0]
        self.assertEqual(sequence.start_step_hint, 1)
        self.assertEqual(sequence.end_step_hint, 5)
        self.assertEqual(
            [event.start_offset_steps for event in sequence.events],
            [0, 2, 4],
        )
        self.assertEqual(
            [event.rhythmic_position for event in sequence.events],
            ["downbeat", "offbeat", "backbeat"],
        )


if __name__ == "__main__":
    unittest.main()
