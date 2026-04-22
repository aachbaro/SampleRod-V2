from __future__ import annotations

import unittest

from frontend.labo.lab_artifact import (
    LabArtifact,
    artifact_duration_label,
    artifact_file_path,
    artifact_kind_label,
    artifact_status_label,
    build_artifact_filename,
)


class LabArtifactTests(unittest.TestCase):
    def test_filename_and_labels_are_readable(self):
        artifact = LabArtifact(
            artifact_id="abc123",
            kind="slice",
            display_name="My Slice 01",
            source_path="C:/audio/source.wav",
            duration=1.234,
            persisted=False,
            origin="waveform_selection",
        )

        self.assertEqual(artifact_kind_label(artifact.kind), "Slice")
        self.assertEqual(artifact_status_label(artifact), "Temporaire")
        self.assertEqual(artifact_duration_label(artifact.duration), "1.23s")
        self.assertEqual(build_artifact_filename(artifact), "My_Slice_01.wav")
        self.assertTrue(artifact_file_path(artifact).endswith("source.wav"))

    def test_persisted_status_changes_label(self):
        artifact = LabArtifact(
            artifact_id="def456",
            kind="current_file",
            display_name="Current Mix",
            source_path="C:/audio/source.wav",
            duration=5.0,
            persisted=True,
            origin="waveform_current_file",
        )

        self.assertEqual(artifact_kind_label(artifact.kind), "Fichier courant")
        self.assertEqual(artifact_status_label(artifact), "Persiste")

    def test_stem_artifacts_use_temp_path_as_active_file(self):
        artifact = LabArtifact(
            artifact_id="stem001",
            kind="stem",
            display_name="Amen - drums",
            source_path="C:/audio/source.wav",
            temp_path="C:/temp/source/drums.wav",
            duration=5.0,
            persisted=False,
            origin="stem_separation",
        )

        self.assertEqual(artifact_kind_label(artifact.kind), "Stem")
        self.assertTrue(artifact_file_path(artifact).endswith("drums.wav"))


if __name__ == "__main__":
    unittest.main()
