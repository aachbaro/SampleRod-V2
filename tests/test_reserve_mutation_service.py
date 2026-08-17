from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.services.reserve_mutation_service import (
    ReserveMutationService,
    ReserveMutationStatus,
)


class FakePlayer:
    def __init__(self, sample_id=-1, path=""):
        self.current_sample_id = sample_id
        self.current_sample_path = path
        self.clear_count = 0

    def clear_audio(self):
        self.clear_count += 1


class FakeStore:
    def __init__(self):
        self.calls = []

    def unindex(self, sample_id):
        self.calls.append(("unindex", sample_id))
        return True

    def delete(self, sample_id):
        self.calls.append(("delete", sample_id))
        return True

    def delete_by_path(self, path, *, missing_ok=False):
        self.calls.append(("delete_by_path", path, missing_ok))
        return True, None

    def rename(self, sample_id, name):
        self.calls.append(("rename", sample_id, name))
        return True

    def rename_by_path(self, path, name):
        self.calls.append(("rename_by_path", path, name))
        return True, None

    def move(self, sample_id, folder):
        self.calls.append(("move", sample_id, folder))
        return True

    def move_by_path(self, path, folder):
        self.calls.append(("move_by_path", path, folder))
        return True, None


def make_service(player=None):
    store = FakeStore()
    player = player or FakePlayer()
    context = SimpleNamespace(sample_store=store, audio_player=player)
    return ReserveMutationService(context), store, player


def entry(path, sample_id=None, *, missing=False):
    return SimpleNamespace(path=str(path), sample_id=sample_id, missing=missing)


def test_unindex_indexed_stops_by_id_and_preserves_file(tmp_path):
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"audio")
    service, store, player = make_service(FakePlayer(42, ""))

    result = service.unindex(entry(audio, 42))

    assert result.status is ReserveMutationStatus.SUCCESS
    assert result.success
    assert audio.exists()
    assert player.clear_count == 1
    assert store.calls == [("unindex", 42)]


def test_unindex_non_indexed_is_not_applicable_and_does_not_stop(tmp_path):
    audio = tmp_path / "loose.wav"
    audio.write_bytes(b"audio")
    service, store, player = make_service(FakePlayer(-1, str(audio)))

    result = service.unindex(entry(audio))

    assert result.status is ReserveMutationStatus.NOT_APPLICABLE
    assert player.clear_count == 0
    assert store.calls == []


def test_delete_missing_indexed_removes_record_and_stops_by_path(tmp_path):
    missing = tmp_path / "missing.wav"
    service, store, player = make_service(FakePlayer(-1, str(missing)))

    result = service.delete_file_and_record(entry(missing, 8, missing=True))

    assert result.status is ReserveMutationStatus.SUCCESS
    assert player.clear_count == 1
    assert store.calls == [("delete", 8)]


def test_delete_missing_unindexed_treats_absence_as_valid(tmp_path):
    missing = tmp_path / "missing.wav"
    service, store, _player = make_service()

    result = service.delete_file_and_record(entry(missing))

    assert result.success
    assert store.calls[0][0] == "delete_by_path"
    assert store.calls[0][2] is True


def test_rename_uses_indexed_primitive_and_returns_new_path(tmp_path):
    audio = tmp_path / "old.wav"
    audio.write_bytes(b"audio")
    service, store, player = make_service(FakePlayer(-1, str(audio)))

    result = service.rename(entry(audio, 7), "human")

    assert result.success
    assert result.new_path.endswith(os.path.join("", "human.wav"))
    assert player.clear_count == 1
    assert store.calls == [("rename", 7, "human")]


def test_move_unindexed_uses_path_primitive_and_returns_success(tmp_path):
    audio = tmp_path / "old.wav"
    audio.write_bytes(b"audio")
    target = tmp_path / "target"
    service, store, _player = make_service()

    result = service.move(entry(audio), str(target))

    assert result.status is ReserveMutationStatus.SUCCESS
    assert store.calls[0][0] == "move_by_path"


def test_move_indexed_is_reported_as_queued(tmp_path):
    audio = tmp_path / "old.wav"
    audio.write_bytes(b"audio")
    service, store, _player = make_service()

    result = service.move(entry(audio, 3), str(tmp_path / "target"))

    assert result.status is ReserveMutationStatus.QUEUED
    assert store.calls[0][0] == "move"


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for test_function in (
        test_unindex_indexed_stops_by_id_and_preserves_file,
        test_unindex_non_indexed_is_not_applicable_and_does_not_stop,
        test_delete_missing_indexed_removes_record_and_stops_by_path,
        test_delete_missing_unindexed_treats_absence_as_valid,
        test_rename_uses_indexed_primitive_and_returns_new_path,
        test_move_unindexed_uses_path_primitive_and_returns_success,
        test_move_indexed_is_reported_as_queued,
    ):
        def run(function=test_function):
            import tempfile

            with tempfile.TemporaryDirectory() as folder:
                function(Path(folder))

        suite.addTest(unittest.FunctionTestCase(run, description=test_function.__name__))
    return suite
