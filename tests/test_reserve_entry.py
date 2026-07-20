from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from backend.services.directory_service import DirectoryAudioEntry
from frontend.reserve.reserve_entry import (
    STATUS_MISSING,
    STATUS_NEEDS_ANALYSIS,
    STATUS_NON_INDEXED,
    reserve_entry_from_directory,
    reserve_entry_from_sample,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
)


class ReserveEntryTests(unittest.TestCase):
    def test_build_entry_from_directory_uses_common_statuses(self):
        entry = reserve_entry_from_directory(
            DirectoryAudioEntry(
                path=os.path.abspath("C:/samples/kick.wav"),
                name="kick",
                sample_id=None,
                indexed=False,
                missing=False,
                needs_analysis=False,
                duration=0.5,
                rms_level=0.12,
            )
        )

        self.assertEqual(entry.status, STATUS_NON_INDEXED)
        self.assertEqual(entry.status_label, "Non indexe")
        self.assertFalse(entry.indexed)

    def test_build_entry_from_directory_preserves_scale_metadata(self):
        entry = reserve_entry_from_directory(
            DirectoryAudioEntry(
                path=os.path.abspath("C:/samples/chord.wav"),
                name="chord",
                sample_id=12,
                indexed=True,
                missing=False,
                needs_analysis=False,
                dominant_note="Am",
                detected_scale_label="A natural minor",
                detected_scale_kind="scale",
                scale_confidence=0.84,
                compatible_scales=("Am", "C major"),
            )
        )

        self.assertEqual(entry.dominant_note, "Am")
        self.assertEqual(entry.detected_scale_label, "A natural minor")
        self.assertEqual(entry.detected_scale_kind, "scale")
        self.assertEqual(entry.compatible_scales, ("Am", "C major"))
        self.assertTrue(reserve_entry_matches_query(entry, "natural minor c major"))

    def test_build_entry_from_sample_marks_analysis_and_missing(self):
        pending_sample = SimpleNamespace(
            id=1,
            name="snare",
            path=os.path.abspath("C:/samples/snare.wav"),
            duration=1.2,
            rms_level=0.25,
            missing=False,
            needs_analysis=True,
        )
        missing_sample = SimpleNamespace(
            id=2,
            name="texture",
            path=os.path.abspath("C:/textures/texture.wav"),
            duration=2.4,
            rms_level=None,
            missing=True,
            needs_analysis=False,
        )

        pending_entry = reserve_entry_from_sample(pending_sample, source_kind="history")
        missing_entry = reserve_entry_from_sample(missing_sample, source_kind="indexed")

        self.assertEqual(pending_entry.status, STATUS_NEEDS_ANALYSIS)
        self.assertEqual(missing_entry.status, STATUS_MISSING)

    def test_query_and_status_filters_share_same_logic(self):
        sample = SimpleNamespace(
            id=7,
            name="Warm Pad",
            path=os.path.abspath("C:/Library/Pads/warm_pad.wav"),
            duration=3.5,
            rms_level=0.18,
            missing=False,
            needs_analysis=True,
        )
        entry = reserve_entry_from_sample(
            sample,
            source_kind="indexed",
            root_path=os.path.abspath("C:/Library"),
            folder_path=os.path.abspath("C:/Library/Pads"),
        )

        self.assertTrue(reserve_entry_matches_query(entry, "warm pads indexe"))
        self.assertTrue(reserve_entry_matches_query(entry, "library warm"))
        self.assertFalse(reserve_entry_matches_query(entry, "texture drums"))
        self.assertTrue(reserve_entry_matches_status(entry, STATUS_NEEDS_ANALYSIS))
        self.assertFalse(reserve_entry_matches_status(entry, STATUS_MISSING))


if __name__ == "__main__":
    unittest.main()
