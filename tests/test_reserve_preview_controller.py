from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QCoreApplication, QObject

from backend.services.reserve_mutation_service import ReserveMutationService
from frontend.reserve.reserve_entry import ReserveEntry
from frontend.reserve.reserve_actions import ReserveActions
from frontend.reserve.reserve_preview import ReservePreviewController, ReservePreviewKey
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination


class FakePlayer:
    def __init__(self):
        self.current_sample_id = -1
        self.current_sample_path = None
        self.current_sample_duration = -1
        self.is_playing = False
        self.is_paused = False
        self.position = 0
        self.clear_count = 0

    def toggle_play(self, sample_id, path, duration):
        if self.current_sample_id == sample_id and self.is_playing:
            self.is_paused = not self.is_paused
            return not self.is_paused
        self.current_sample_id = sample_id
        self.current_sample_path = path
        self.current_sample_duration = duration
        self.is_playing = True
        self.is_paused = False
        return True

    def seek_position(self, sample_id, path, duration, position):
        self.current_sample_id = sample_id
        self.current_sample_path = path
        self.current_sample_duration = duration
        self.position = position
        self.is_playing = True
        self.is_paused = False
        return True

    def clear_audio(self):
        self.clear_count += 1
        self.current_sample_id = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False

    def get_position(self):
        return self.position


class ReservePreviewControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.a = self._entry("a.wav", 1)
        self.b = self._entry("b.wav", 2)
        self.player = FakePlayer()
        self.controller = ReservePreviewController(self.player)

    def tearDown(self):
        self.controller.stop()
        self.temp.cleanup()

    def _entry(self, name, sample_id=None, *, missing=False):
        path = os.path.join(self.temp.name, name)
        if not missing:
            with open(path, "wb") as stream:
                stream.write(b"audio")
        return ReserveEntry(
            source_kind="indexed" if sample_id is not None else "filesystem",
            path=path, sample_id=sample_id, indexed=sample_id is not None,
            duration=2.0, missing=missing,
        )

    def test_indexed_and_non_indexed_use_explicit_session_ids(self):
        self.assertTrue(self.controller.play_pause(self.a))
        self.assertEqual(self.player.current_sample_id, 1)
        loose = self._entry("loose.wav")
        self.assertTrue(self.controller.play_pause(loose))
        first_session_id = self.player.current_sample_id
        self.assertLess(first_session_id, -1)
        self.controller.stop()
        self.controller.play_pause(loose)
        self.assertEqual(self.player.current_sample_id, first_session_id)
        self.assertNotIn("hash", ReservePreviewController._player_id.__doc__ or "")

    def test_same_path_in_multiple_views_is_the_same_active_material(self):
        self.controller.play_pause(self.a)
        filesystem_view = ReserveEntry(source_kind="filesystem", path=self.a.path, duration=2.0)
        self.assertTrue(self.controller.is_active(filesystem_view))
        self.assertTrue(ReservePreviewKey.from_entry(self.a).matches(filesystem_view))
        self.controller.play_pause(filesystem_view)
        self.assertTrue(self.player.is_paused)

    def test_switching_view_keeps_playback_and_shared_active_state(self):
        context = SimpleNamespace(
            audio_player=self.player,
            sample_store=SimpleNamespace(),
            reserve_mutations=SimpleNamespace(),
            reserve_preview=self.controller,
        )
        folders = ReserveActions(context)
        indexed = ReserveActions(context)
        folders.preview(self.a)
        same_file = ReserveEntry(source_kind="indexed", path=self.a.path, sample_id=1, duration=2.0)
        self.assertTrue(indexed.is_previewing(same_file))
        self.assertTrue(self.player.is_playing)

    def test_exclusivity_play_pause_seek_and_restart(self):
        self.controller.play_pause(self.a)
        self.controller.play_pause(self.a)
        self.assertTrue(self.player.is_paused)
        self.controller.seek(self.a, 750)
        self.assertEqual(self.player.position, 750)
        self.controller.restart(self.a)
        self.assertEqual(self.player.position, 0)
        self.controller.play_pause(self.b)
        self.assertTrue(self.controller.is_active(self.b))
        self.assertFalse(self.controller.is_active(self.a))

    def test_play_at_end_restarts_from_zero(self):
        self.controller.play_pause(self.a)
        self.controller.seek(self.a, 999999)
        self.assertEqual(self.player.position, 2000)
        self.assertTrue(self.controller.play_pause(self.a))
        self.assertEqual(self.player.position, 0)

    def test_missing_file_is_not_playable_and_creates_no_sample(self):
        missing = self._entry("missing.wav", 9, missing=True)
        self.assertFalse(self.controller.play_pause(missing))
        self.assertIsNone(self.controller.active_entry)

    def test_mutation_only_interrupts_matching_entry_by_path(self):
        self.controller.play_pause(self.a)
        store = SimpleNamespace(rename=mock.Mock(return_value=True))
        context = SimpleNamespace(
            sample_store=store, audio_player=self.player, reserve_preview=self.controller
        )
        mutations = ReserveMutationService(context)
        with mock.patch("backend.services.reserve_mutation_service.os.path.isfile", return_value=True):
            mutations.rename(self.b, "other")
            self.assertTrue(self.controller.is_active(self.a))
            mutations.rename(self.a, "renamed")
            self.assertIsNone(self.controller.active_entry)

    def test_renderer_can_detach_and_destroy_without_stale_callback(self):
        owner = QObject()
        callback = mock.Mock()
        self.controller.attach_renderer("owner", owner, active=callback)
        self.controller.play_pause(self.a)
        self.assertEqual(callback.call_count, 1)
        self.controller.detach_renderer("owner")
        self.controller.play_pause(self.b)
        self.assertEqual(callback.call_count, 1)

    def test_page_change_stops_only_when_active_entry_leaves_page(self):
        controller = mock.Mock()
        controller.active_entry = self.a
        widget = SimpleNamespace(
            filtered_samples=[SimpleNamespace(id=2)], samples_per_page=1,
            _card_widgets={}, app_context=SimpleNamespace(reserve_preview=controller),
            get_filtered_samples=lambda: [],
        )
        pagination = SampleListPagination(widget)
        pagination.set_current_page = mock.Mock()
        pagination.change_page(1)
        controller.stop.assert_called_once_with(self.a)

        controller.reset_mock()
        controller.active_entry = self.b
        pagination.change_page(1)
        controller.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
