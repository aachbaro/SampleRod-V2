from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from frontend.reserve.reserve_actions import ReserveActions
from frontend.reserve.reserve_entry import ReserveEntry


class _Player:
    def __init__(self):
        self.is_playing = False
        self.current_sample_id = -1
        self.current_sample_path = None
        self.clear_audio = mock.Mock(side_effect=self._clear)
        self.toggle_play = mock.Mock(side_effect=self._toggle)
        self.seek_position = mock.Mock(return_value=True)

    def _clear(self):
        self.is_playing = False
        self.current_sample_id = -1
        self.current_sample_path = None

    def _toggle(self, sample_id, path, _duration):
        self.is_playing = True
        self.current_sample_id = sample_id
        self.current_sample_path = path
        return True


class ReservePreviewContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = []
        for name in ("one.wav", "two.wav"):
            path = os.path.join(self.temp.name, name)
            open(path, "wb").close()
            self.paths.append(path)
        self.player = _Player()
        self.actions = ReserveActions(
            SimpleNamespace(sample_store=SimpleNamespace(), audio_player=self.player)
        )

    def tearDown(self):
        self.temp.cleanup()

    def _entry(self, index, sample_id=None):
        return ReserveEntry(
            source_kind="filesystem",
            path=self.paths[index],
            sample_id=sample_id,
            duration=2.0,
            indexed=sample_id is not None,
        )

    def test_starting_second_entry_clears_global_player_first(self):
        first = self._entry(0, 10)
        second = self._entry(1, 11)
        self.actions.preview(first)

        self.actions.preview(second)

        self.player.clear_audio.assert_called_once()
        self.assertEqual(self.player.current_sample_id, 11)
        self.assertEqual(self.player.current_sample_path, self.paths[1])

    def test_unindexed_entry_uses_a_session_id_and_remains_seekable(self):
        entry = self._entry(0, None)

        self.assertTrue(self.actions.preview(entry))
        generated_id = self.player.current_sample_id
        self.assertIsInstance(generated_id, int)
        self.assertNotEqual(generated_id, -1)
        self.assertTrue(self.actions.seek_preview(entry, 750))
        self.player.seek_position.assert_called_with(
            generated_id, entry.path, 2.0, 750
        )

    def test_missing_file_cannot_start_preview(self):
        entry = ReserveEntry(
            source_kind="indexed",
            path=os.path.join(self.temp.name, "absent.wav"),
            sample_id=4,
            missing=True,
            indexed=True,
        )
        self.assertFalse(self.actions.preview(entry))
        self.player.toggle_play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
