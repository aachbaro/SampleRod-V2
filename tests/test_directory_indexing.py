from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np
import soundfile as sf
from sqlalchemy import create_engine

from backend.db import Base, SessionLocal
from backend.models.sample import Sample
from backend.services.directory_service import DirectoryService, _DirectoryIndexWorker


class _DummySampleStore:
    def load_all(self):
        return None


class DirectoryIndexingTests(unittest.TestCase):
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

    def test_index_worker_adds_audio_files_with_rms_and_analysis_pending(self):
        first = self._write_tone("kick.wav", freq=110.0)
        second = self._write_tone(os.path.join("drums", "snare.wav"), freq=220.0)

        events = []
        worker = _DirectoryIndexWorker(self.library_dir)
        worker.completed.connect(lambda _folder, summary: events.append(summary))
        worker.run()

        with SessionLocal() as session:
            samples = session.query(Sample).order_by(Sample.path).all()

        self.assertEqual(len(samples), 2)
        self.assertEqual({sample.path for sample in samples}, {first, second})
        self.assertTrue(all(sample.analyzed_at is None for sample in samples))
        self.assertTrue(all(sample.needs_analysis for sample in samples))
        self.assertTrue(all(sample.rms_level is not None and sample.rms_level > 0 for sample in samples))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["added"], 2)
        self.assertEqual(events[0]["errors"], 0)

    def test_index_worker_marks_deleted_files_missing_and_recovers_when_they_return(self):
        target = self._write_tone("loop.wav", freq=165.0)

        first_run = _DirectoryIndexWorker(self.library_dir)
        first_run.run()

        os.remove(target)
        missing_events = []
        missing_run = _DirectoryIndexWorker(self.library_dir)
        missing_run.completed.connect(lambda _folder, summary: missing_events.append(summary))
        missing_run.run()

        with SessionLocal() as session:
            sample = session.query(Sample).one()
            self.assertTrue(sample.missing)

        self._write_tone("loop.wav", freq=165.0)
        recovered_events = []
        recovered_run = _DirectoryIndexWorker(self.library_dir)
        recovered_run.completed.connect(lambda _folder, summary: recovered_events.append(summary))
        recovered_run.run()

        with SessionLocal() as session:
            sample = session.query(Sample).one()
            self.assertFalse(sample.missing)
            self.assertTrue(sample.needs_analysis)

        self.assertEqual(missing_events[0]["marked_missing"], 1)
        self.assertEqual(recovered_events[0]["recovered"], 1)

    def test_directory_status_reports_indexed_after_sync(self):
        self._write_tone("texture.wav", freq=330.0)
        worker = _DirectoryIndexWorker(self.library_dir)
        worker.run()

        service = DirectoryService(_DummySampleStore())
        status = service.get_folder_index_status(self.library_dir)

        self.assertTrue(status["indexed"])
        self.assertEqual(status["label"], "Indexe")
        self.assertEqual(status["on_disk"], 1)
        self.assertEqual(status["tracked"], 1)
        self.assertEqual(status["missing"], 0)

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
