import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend.labo.artifact_tray import ArtifactTrayRow
from frontend.labo.lab_artifact import LabArtifact
from frontend.labo.stem_widgets import StemTile


class MaterialBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_artifact_keeps_status_in_tooltip_without_redundant_badge(self):
        artifact = LabArtifact(
            artifact_id="artifact-1",
            kind="slice",
            display_name="Slice",
            source_path="C:/audio/source.wav",
            origin="waveform_selection",
            operation="selection",
        )
        row = ArtifactTrayRow(artifact, None)

        self.assertFalse(hasattr(row, "material_badge"))
        self.assertIn("Matière : ARTEFACT", row.toolTip())
        self.assertIn("Opération : selection", row.toolTip())
        row.close()

    def test_stem_exposes_status_and_provenance_only_in_tooltip(self):
        tile = StemTile("drums", "C:/audio/drums.wav")

        self.assertIn("DÉRIVÉ · STEM", tile.toolTip())
        self.assertIn("stem_separation", tile.toolTip())
        self.assertNotIn("ART", tile.name)
        tile.close()

    def test_artifact_row_hides_secondary_playback_data_when_narrow(self):
        artifact = LabArtifact(
            artifact_id="artifact-compact",
            kind="current_file",
            display_name="Un nom volontairement long",
            source_path="C:/audio/source.wav",
        )
        row = ArtifactTrayRow(artifact, None)

        row.show()
        row.setFixedWidth(240)
        row._update_compact_layout()
        self.app.processEvents()
        self.assertFalse(row.slider.isVisible())
        self.assertFalse(row.time_label.isVisible())
        self.assertTrue(row.play_button.isVisible())
        self.assertTrue(row.kind_label.isVisible())
        self.assertTrue(row.delete_button.isVisible())
        row.close()


if __name__ == "__main__":
    unittest.main()
