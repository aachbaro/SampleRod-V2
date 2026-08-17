from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from frontend.dragdrop import DragKind, MaterialOperation, MaterialStatus
from frontend.library_gui.library_widget import LibraryWidget
from frontend.right_panel.directory.directory_item_widget import DirectoryListItemWidget
from frontend.sample_gui.sample.sample_card_interactions import SampleCardInteractions
from frontend.reserve.reserve_entry import ReserveEntry


class _Drag:
    instances = []

    def __init__(self, _source):
        self.mime = None
        self.__class__.instances.append(self)

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, _pixmap):
        pass

    def exec(self, _action):
        return 1


class ReserveDragSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "source.wav")
        open(self.path, "wb").close()
        _Drag.instances.clear()

    def tearDown(self):
        self.temp.cleanup()

    def _patches(self, module):
        captured = []
        return captured, (
            mock.patch.object(module, "QDrag", _Drag),
            mock.patch.object(module, "attach_payload", lambda mime, payload: captured.append(payload)),
            mock.patch.object(module, "drag_preview_pixmap", lambda _payload: None),
            mock.patch.object(module, "drag_session", lambda _payload: nullcontext()),
        )

    def _assert_source_payload(self, payload, expected_module):
        self.assertIs(payload.kind, DragKind.AUDIO_FILE)
        self.assertIs(payload.status, MaterialStatus.SOURCE)
        self.assertIs(payload.provenance.operation, MaterialOperation.IMPORT)
        self.assertEqual(payload.items[0].path, self.path)
        self.assertEqual(payload.source_module, expected_module)

    def test_directory_indexed_and_unindexed_emit_same_source_contract(self):
        import frontend.right_panel.directory.directory_item_widget as module
        for sample_id in (None, 12):
            captured, patches = self._patches(module)
            harness = SimpleNamespace(file_path=self.path, sample_id=sample_id)
            with patches[0], patches[1], patches[2], patches[3]:
                DirectoryListItemWidget._start_drag(harness)
            self._assert_source_payload(captured[0], "directory")
            self.assertTrue(_Drag.instances[-1].mime.hasUrls())
            self.assertEqual(
                _Drag.instances[-1].mime.hasFormat("application/x-sample-card"),
                sample_id is not None,
            )

    def test_recent_card_emits_modern_url_and_legacy_contracts(self):
        import frontend.sample_gui.sample.sample_card_interactions as module
        card = SimpleNamespace(sample=SimpleNamespace(id=8, path=self.path))
        interactions = SampleCardInteractions(card)
        captured, patches = self._patches(module)
        with patches[0], patches[1], patches[2], patches[3]:
            interactions._start_drag()
        self._assert_source_payload(captured[0], "reserve")
        mime = _Drag.instances[-1].mime
        self.assertTrue(mime.hasUrls())
        self.assertTrue(mime.hasFormat("application/x-sample-card"))

    def test_index_emits_modern_url_and_legacy_contracts(self):
        import frontend.library_gui.library_widget as module
        entry = ReserveEntry(
            source_kind="indexed", path=self.path, sample_id=9, indexed=True
        )
        harness = SimpleNamespace(
            table=object(), current_reserve_entry=lambda: entry,
        )
        captured, patches = self._patches(module)
        with patches[0], patches[1], patches[2], patches[3]:
            LibraryWidget._start_drag_from_selection(harness)
        self._assert_source_payload(captured[0], "reserve")
        mime = _Drag.instances[-1].mime
        self.assertTrue(mime.hasUrls())
        self.assertTrue(mime.hasFormat("application/x-sample-card"))


if __name__ == "__main__":
    unittest.main()
