from __future__ import annotations

import datetime as dt
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from frontend.library_gui.library_widget import LibraryWidget
from frontend.library_gui.library_widget import pending_hidden_refresh_requires_render
from frontend.reserve.reserve_entry import ReserveEntry


class ReserveIndexInteractionTests(unittest.TestCase):
    def test_hidden_quick_add_requires_a_real_render_when_shown(self):
        snapshot = [object()]
        self.assertTrue(pending_hidden_refresh_requires_render(
            snapshot,
            quick_update_unrendered=True,
            pending_signature=(1,),
            rendered_signature=(1,),
        ))

    def test_human_date_keeps_numeric_sort_key_available(self):
        value = dt.datetime(2026, 8, 17, 10, 42)
        self.assertEqual(LibraryWidget._format_created_at(value), "17/08/2026 10:42")
        self.assertEqual(LibraryWidget._sort_value_for_created_at(value), value.timestamp())

    def test_duration_formatter_is_human_but_source_value_stays_seconds(self):
        entry = ReserveEntry(
            source_kind="indexed", path="C:/audio/long.wav", sample_id=1,
            indexed=True, duration=62.1435,
        )
        harness = SimpleNamespace()
        text = LibraryWidget._format_duration(harness, entry)
        self.assertNotIn("e+", text.lower())
        self.assertEqual(entry.duration, 62.1435)

    def test_mutating_selected_entry_stops_player_by_path_even_if_id_differs(self):
        player = SimpleNamespace(
            current_sample_id=999,
            current_sample_path=os.path.normpath("C:/audio/kick.wav"),
            clear_audio=mock.Mock(),
        )
        harness = SimpleNamespace(app_context=SimpleNamespace(audio_player=player))
        entry = ReserveEntry(
            source_kind="indexed", path="C:/audio/kick.wav", sample_id=3,
            indexed=True,
        )

        LibraryWidget._stop_audio_for_entry(harness, entry)

        player.clear_audio.assert_called_once_with()

    def test_unrelated_player_is_not_stopped(self):
        player = SimpleNamespace(
            current_sample_id=999,
            current_sample_path=os.path.normpath("C:/audio/other.wav"),
            clear_audio=mock.Mock(),
        )
        harness = SimpleNamespace(app_context=SimpleNamespace(audio_player=player))
        entry = ReserveEntry(
            source_kind="indexed", path="C:/audio/kick.wav", sample_id=3,
            indexed=True,
        )
        LibraryWidget._stop_audio_for_entry(harness, entry)
        player.clear_audio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
