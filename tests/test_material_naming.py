import os
import tempfile
import unittest

from backend.services.material_naming import (
    human_material_base,
    material_display_name,
    promoted_file_stem,
)
from backend.services.sample_service import SampleService


class MaterialNamingTests(unittest.TestCase):
    def test_technical_suffixes_are_hidden_from_human_name(self):
        self.assertEqual(
            human_material_base(
                "SMPL_1003_wav_ccd94e75_wav_12c575c8_0cf1f54a.wav"
            ),
            "SMPL_1003",
        )

    def test_operation_is_short_and_readable(self):
        self.assertEqual(
            material_display_name(
                "C:/audio/SMPL_1003.wav", kind="audio_selection"
            ),
            "SMPL_1003 · sélection",
        )
        self.assertEqual(
            material_display_name("C:/audio/SMPL_1003.wav", kind="current_file"),
            "SMPL_1003 · édition",
        )

    def test_promoted_filename_stays_short_but_unique(self):
        self.assertEqual(
            promoted_file_stem("C:/audio/SMPL_1003.wav", "audio_selection"),
            "SMPL_1003_selection",
        )
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "SMPL_1003_selection.wav")
            open(first, "wb").close()
            self.assertEqual(
                SampleService._unique_promoted_path(
                    folder, "SMPL_1003_selection", ".wav"
                ),
                os.path.join(folder, "SMPL_1003_selection_02.wav"),
            )


if __name__ == "__main__":
    unittest.main()
