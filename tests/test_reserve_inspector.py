from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QApplication

from frontend.reserve.reserve_entry import ReserveEntry, reserve_entry_from_sample
from frontend.reserve.reserve_inspector import ReserveInspector
from frontend.reserve.reserve_preview import ReservePreviewController


class _Player:
    def __init__(self):
        self.current_sample_id = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False
        self.position = 0

    def toggle_play(self, sample_id, path, duration):
        self.current_sample_id = sample_id
        self.current_sample_path = path
        self.is_playing = True
        self.is_paused = False
        return True

    def seek_position(self, sample_id, path, duration, position):
        self.current_sample_id = sample_id
        self.current_sample_path = path
        self.position = position
        self.is_playing = True
        return True

    def clear_audio(self):
        self.current_sample_id = -1
        self.current_sample_path = None
        self.is_playing = False

    def get_position(self):
        return self.position


class ReserveInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "beat.wav")
        with open(self.path, "wb") as stream:
            stream.write(b"audio")
        self.player = _Player()
        self.preview = ReservePreviewController(self.player)
        self.mutations = mock.Mock()
        self.actions = mock.Mock(mutations=self.mutations)
        self.context = SimpleNamespace(
            audio_player=self.player,
            reserve_preview=self.preview,
            reserve_mutations=self.mutations,
            sample_store=mock.Mock(),
        )
        self.widget = ReserveInspector(self.context, reserve_actions=self.actions)

    def tearDown(self):
        self.widget.deleteLater()
        self.preview.stop()
        self.temp.cleanup()

    def entry(self, **values):
        defaults = dict(
            source_kind="filesystem", path=self.path, display_name="Beat",
            duration=2.0, indexed=False, metadata={},
        )
        defaults.update(values)
        return ReserveEntry(**defaults)

    def test_set_clear_and_modes_never_create_a_sample(self):
        entry = self.entry()
        self.widget.set_entry(entry)
        self.assertIs(self.widget.entry, entry)
        self.assertEqual(self.widget.title_label.text(), "Beat")
        self.assertFalse(self.widget.unindex_button.isEnabled())
        self.widget.set_mode("expanded")
        self.widget.set_mode("compact")
        self.widget.clear_entry()
        self.assertIsNone(self.widget.entry)
        self.context.sample_store.add.assert_not_called()

    def test_indexed_missing_and_provenance_are_conditional(self):
        entry = self.entry(
            indexed=True, sample_id=4, missing=True,
            metadata={"provenance": {
                "previous_status": "derived", "source_path": "C:/source.wav",
                "start_seconds": 1.0, "end_seconds": 2.5,
            }},
        )
        self.widget.set_entry(entry)
        self.assertFalse(self.widget.play_button.isEnabled())
        self.assertTrue(self.widget.unindex_button.isEnabled())
        self.assertTrue(self.widget.delete_button.isEnabled())
        self.assertIn("DERIVED", self.widget.provenance_label.text())
        self.assertIn("1.00–2.50 s", self.widget.provenance_label.text())

    def test_preview_and_seek_follow_common_controller(self):
        entry = self.entry()
        other_view = self.entry(source_kind="indexed", sample_id=7)
        self.widget.set_entry(entry)
        self.preview.play_pause(other_view)
        self.assertEqual(self.widget.play_button.text(), "Pause")
        self.preview.seek(other_view, 900)
        self.assertEqual(self.widget.slider.value(), 900)
        self.preview.stop()
        self.assertEqual(self.widget.slider.value(), 0)

    def test_renderer_detaches_when_destroyed(self):
        owner_id = self.widget._owner_id
        self.assertIn(owner_id, self.preview._renderers)
        self.widget.preview.detach_renderer(owner_id)
        self.assertNotIn(owner_id, self.preview._renderers)

    def test_sample_material_metadata_reaches_reserve_entry(self):
        sample = SimpleNamespace(
            id=4, path=self.path, name="Beat", missing=False,
            needs_analysis=False, duration=2.0, rms_level=None,
            created_at=None, dominant_note=None, detected_scale_label=None,
            detected_scale_kind=None, scale_confidence=None,
            compatible_scales=None,
            material_metadata_dict={"material_status": "source", "provenance": {"previous_status": "artifact"}},
        )
        entry = reserve_entry_from_sample(sample, source_kind="indexed")
        self.assertEqual(entry.metadata["provenance"]["previous_status"], "artifact")


if __name__ == "__main__":
    unittest.main()
