from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
import numpy as np
import soundfile as sf

from backend import db
from backend.db import Base, SessionLocal
from backend.models.sample import Sample
from backend.services.sample_service import SampleService


class _Signal:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class ReserveMutationSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{os.path.join(self.temp.name, 'samples.db')}")
        SessionLocal.configure(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.db_patch = mock.patch.object(db, "engine", self.engine)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def _file(self, name="sample.wav"):
        path = os.path.join(self.temp.name, name)
        sf.write(path, np.zeros(800, dtype="float32"), 8_000)
        return os.path.normpath(os.path.abspath(path))

    def _service(self, sample):
        notifications = SimpleNamespace(notify=mock.Mock())
        return SimpleNamespace(
            _samples=[sample],
            _get=lambda sid: sample if sid == sample.id else None,
            _cleanup_concat_state_for_deleted=mock.Mock(),
            app_context=SimpleNamespace(notifications=notifications),
            sampleUnindexed=_Signal(),
            sampleRemovedFromHistory=_Signal(),
            sampleDeleted=_Signal(),
            samplesChanged=_Signal(),
        )

    def test_remove_from_history_deletes_record_but_preserves_file(self):
        path = self._file()
        sample = Sample(path, duration=1.0, rms_level=0.1)
        service = self._service(sample)

        SampleService.removeFromHistory(service, sample.id)

        self.assertTrue(os.path.isfile(path))
        with SessionLocal() as session:
            self.assertIsNone(session.get(Sample, sample.id))
        self.assertEqual(service._samples, [])
        self.assertEqual(service.sampleUnindexed.values, [(sample.id,)])
        self.assertEqual(service.sampleRemovedFromHistory.values, [(sample.id,)])

    def test_delete_removes_file_record_and_cache(self):
        path = self._file()
        sample = Sample(path, duration=1.0, rms_level=0.1)
        service = self._service(sample)

        SampleService.delete(service, sample.id)

        self.assertFalse(os.path.exists(path))
        with SessionLocal() as session:
            self.assertIsNone(session.get(Sample, sample.id))
        self.assertEqual(service._samples, [])
        self.assertEqual(service.sampleDeleted.values, [(sample.id,)])

    def test_delete_missing_sample_still_removes_database_record(self):
        path = self._file("missing.wav")
        sample = Sample(path, duration=1.0, rms_level=0.0, missing=False)
        os.remove(path)
        sample.missing = True
        with SessionLocal() as session:
            stored = session.get(Sample, sample.id)
            stored.missing = True
            session.commit()
        service = self._service(sample)

        SampleService.delete(service, sample.id)

        with SessionLocal() as session:
            self.assertIsNone(session.get(Sample, sample.id))
        self.assertEqual(service._samples, [])

    def test_delete_unindexed_path_only_removes_the_file(self):
        path = self._file("loose.wav")
        service = SimpleNamespace(
            _samples=[],
            app_context=SimpleNamespace(
                notifications=SimpleNamespace(notify=mock.Mock())
            ),
        )

        success, error = SampleService.delete_by_path(service, path)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
