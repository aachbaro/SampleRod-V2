from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import backend.services.drum_analysis_service as drum_service


class DrumAnalysisServiceTests(unittest.TestCase):
    def _raw_result(self):
        hit1 = SimpleNamespace(
            index=1,
            start_s=0.0,
            end_s=0.18,
            label="kick",
            confidence=0.91,
            role="downbeat",
            rhythmic_position="downbeat",
            secondary_labels=("sub",),
            layer_score=0.22,
        )
        hit2 = SimpleNamespace(
            index=2,
            start_s=0.25,
            end_s=0.41,
            label="snare",
            confidence=0.84,
            role="backbeat",
            rhythmic_position="backbeat",
            secondary_labels=(),
            layer_score=0.08,
        )
        candidate = SimpleNamespace(label="break")
        return SimpleNamespace(
            source_path="C:/audio/break.wav",
            label="break",
            family="drum",
            form="loop",
            confidence=0.95,
            duration_s=1.2,
            sample_rate=44100,
            tempo_bpm=168.0,
            pulse_score=0.77,
            regularity=0.71,
            onset_count=2,
            candidates=(candidate,),
            transient_hits=(hit1, hit2),
        )

    def test_adapt_drum_detection_result_maps_proto_hits(self):
        result = drum_service.adapt_drum_detection_result(
            self._raw_result(),
            split_density=42.0,
        )

        self.assertEqual(result.label, "break")
        self.assertEqual(result.family, "drum")
        self.assertEqual(result.form, "loop")
        self.assertAlmostEqual(result.tempo_bpm, 168.0)
        self.assertEqual(result.candidates, ("break",))
        self.assertEqual(len(result.slices), 2)
        self.assertEqual(result.slices[0].label, "kick")
        self.assertEqual(result.slices[0].secondary_labels, ("sub",))
        self.assertEqual(result.slices[1].role, "backbeat")

    def test_project_quantized_slices_applies_schedule_positions(self):
        raw_result = self._raw_result()
        result = drum_service.adapt_drum_detection_result(
            raw_result,
            split_density=50.0,
        )
        fake_preview_module = SimpleNamespace(
            PREVIEW_MODE_QUANTIZE="quantize",
            build_retimed_preview_schedule=mock.Mock(
                return_value=(
                    SimpleNamespace(
                        step_index=1,
                        preview_start_s=0.0,
                        preview_end_s=0.18,
                    ),
                    SimpleNamespace(
                        step_index=5,
                        preview_start_s=0.50,
                        preview_end_s=0.66,
                    ),
                )
            ),
        )

        with mock.patch.object(drum_service, "_load_preview_module", return_value=fake_preview_module):
            projected = drum_service.project_quantized_slices(
                result,
                target_bpm=170.0,
                grid_division=16,
                quantize_strength=0.7,
            )

        self.assertEqual(len(projected), 2)
        self.assertEqual(projected[0].step_index, 1)
        self.assertAlmostEqual(projected[1].preview_start_s or 0.0, 0.50)
        self.assertAlmostEqual(projected[1].preview_end_s or 0.0, 0.66)


if __name__ == "__main__":
    unittest.main()
