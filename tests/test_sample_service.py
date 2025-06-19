import os
import wave
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import types
import pytest

from backend import db
from backend.models import sample as sample_module
from backend.services import sample_service as svc_module


class DummyNotifications:
    def notify(self, **kwargs):
        pass


class DummySettings:
    def isAutoNormalizeEnabled(self):
        return False

    def getNormalizationLevel(self):
        return 0

    def getSamplesPerPage(self):
        return 10


class DummyContext:
    def __init__(self):
        self.notifications = DummyNotifications()
        self.settings = DummySettings()
        self.audio_player = types.SimpleNamespace()


class TestableSampleService(svc_module.SampleService):
    def __init__(self, app_context):
        svc_module.QObject.__init__(self)
        self._samples = []
        self._normalize_threads = {}
        self.app_context = app_context
        self._initialize_cache()


def setup_in_memory_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(svc_module, "SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(sample_module, "SessionLocal", SessionLocal, raising=False)
    db.Base.metadata.create_all(bind=engine)
    return SessionLocal


def create_wav(path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 44100)


def test_exists_by_path(monkeypatch, tmp_path):
    SessionLocal = setup_in_memory_db(monkeypatch)
    create_wav(tmp_path / "a.wav")
    # create one sample in DB
    sample_module.Sample(str(tmp_path / "a.wav"))

    service = TestableSampleService(DummyContext())
    assert service.exists_by_path(str(tmp_path / "a.wav")) is True
    assert service.exists_by_path(str(tmp_path / "b.wav")) is False
