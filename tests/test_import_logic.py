import types
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QCoreApplication

from frontend.sample_gui import sample_list as sample_list_module


class DummyService:
    def __init__(self, existing=None):
        self.paths = set(existing or [])
        self.calls = []

    def exists_by_path(self, path):
        return path in self.paths

    def add(self, path):
        self.calls.append(("add", path))
        self.paths.add(path)

    def delete_record_by_path(self, path):
        self.calls.append(("delete", path))
        self.paths.discard(path)

    def get_cached(self):
        return []


class DummySettings:
    def getSamplesPerPage(self):
        return 10


class DummyContext:
    def __init__(self, service):
        self.sample_store = service
        self.settings = DummySettings()
        self.notifications = types.SimpleNamespace()


class TestWidget(sample_list_module.SampleListWidget):
    def init_ui(self):
        pass


def test_import_sample_new(monkeypatch):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    service = DummyService()
    widget = TestWidget(DummyContext(service))
    monkeypatch.setattr(sample_list_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    widget.import_sample("x.wav")
    assert service.calls == [("add", "x.wav")]


def test_import_sample_existing_no(monkeypatch):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    service = DummyService({"x.wav"})
    widget = TestWidget(DummyContext(service))
    monkeypatch.setattr(sample_list_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    widget.import_sample("x.wav")
    assert service.calls == []


def test_import_sample_existing_yes(monkeypatch):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    service = DummyService({"x.wav"})
    widget = TestWidget(DummyContext(service))
    monkeypatch.setattr(sample_list_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    widget.import_sample("x.wav")
    assert service.calls == [("delete", "x.wav"), ("add", "x.wav")]
