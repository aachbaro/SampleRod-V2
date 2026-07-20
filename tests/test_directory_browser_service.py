from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf
from sqlalchemy import create_engine

from backend.db import Base, SessionLocal
from backend.models.sample import Sample
from backend.services.directory_service import DirectoryService, _DirectoryIndexWorker


class _FakeSampleStore:
    def __init__(self, samples):
        self._samples = list(samples)

    def get_cached(self):
        return list(self._samples)


class DirectoryBrowserServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.library_dir = os.path.join(self._tmpdir.name, "library")
        os.makedirs(self.library_dir, exist_ok=True)

        self._engine = create_engine(f"sqlite:///{os.path.join(self._tmpdir.name, 'test.db')}")
        SessionLocal.configure(bind=self._engine)
        Base.metadata.create_all(bind=self._engine)

    def tearDown(self):
        self._engine.dispose()
        self._tmpdir.cleanup()

    def test_list_audio_entries_marks_indexed_and_pending_items(self):
        tracked = self._write_tone("tracked.wav", freq=220.0)
        self._write_tone("fresh.wav", freq=330.0)

        worker = _DirectoryIndexWorker(self.library_dir)
        worker.run()

        with SessionLocal() as session:
            samples = session.query(Sample).order_by(Sample.path).all()
        tracked_sample = next(sample for sample in samples if sample.name == "tracked")
        tracked_sample.dominant_note = "Dm"
        tracked_sample.detected_scale_label = "D natural minor"
        tracked_sample.detected_scale_kind = "scale"
        tracked_sample.scale_confidence = 0.91
        tracked_sample.compatible_scales = '["Dm", "F major"]'

        service = DirectoryService(_FakeSampleStore([tracked_sample]))
        entries = service.list_audio_entries(self.library_dir)
        entries_by_name = {entry.name: entry for entry in entries}

        self.assertTrue(entries_by_name["tracked"].indexed)
        self.assertEqual(entries_by_name["tracked"].sample_id, tracked_sample.id)
        self.assertEqual(entries_by_name["tracked"].status_label, "A analyser")
        self.assertEqual(entries_by_name["tracked"].dominant_note, "Dm")
        self.assertEqual(entries_by_name["tracked"].detected_scale_label, "D natural minor")
        self.assertEqual(entries_by_name["tracked"].detected_scale_kind, "scale")
        self.assertEqual(entries_by_name["tracked"].compatible_scales, ("Dm", "F major"))
        self.assertFalse(entries_by_name["fresh"].indexed)
        self.assertIsNone(entries_by_name["fresh"].sample_id)
        self.assertEqual(entries_by_name["fresh"].status_label, "Non indexe")
        self.assertEqual(entries_by_name["tracked"].path, os.path.normpath(os.path.abspath(tracked)))

    def test_describe_audio_entry_reads_filesystem_metadata_for_untracked_file(self):
        loose_path = self._write_tone("loose.wav", freq=110.0)
        service = DirectoryService(_FakeSampleStore([]))

        entry = service.describe_audio_entry(loose_path)

        self.assertFalse(entry.indexed)
        self.assertEqual(entry.name, "loose")
        self.assertGreater(entry.duration or 0.0, 0.0)
        self.assertGreater(entry.rms_level or 0.0, 0.0)
        self.assertIsNotNone(entry.created_at)

    def test_describe_audio_entry_can_skip_deep_probe_for_untracked_file(self):
        loose_path = self._write_tone("loose.wav", freq=110.0)
        service = DirectoryService(_FakeSampleStore([]))

        with mock.patch(
            "backend.services.directory_service.collect_audio_file_metadata",
            side_effect=AssertionError("deep metadata probe should not run"),
        ):
            entry = service.describe_audio_entry(loose_path, probe_filesystem=False)

        self.assertFalse(entry.indexed)
        self.assertEqual(entry.name, "loose")
        self.assertIsNone(entry.duration)
        self.assertIsNone(entry.rms_level)

    def _write_tone(self, relative_path: str, *, freq: float) -> str:
        full_path = os.path.join(self.library_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        sample_rate = 22050
        duration_s = 0.25
        t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
        audio = (0.25 * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
        sf.write(full_path, audio, sample_rate)
        return os.path.normpath(os.path.abspath(full_path))


if __name__ == "__main__":
    unittest.main()
