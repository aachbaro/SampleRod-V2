from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend.reserve.reserve_entry import ReserveEntry
from frontend.right_panel.directory.directory_item_widget import DirectoryListItemWidget


class DirectoryRowSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "kick.wav")
        with open(self.path, "wb") as stream:
            stream.write(b"audio")
        actions = SimpleNamespace(is_previewing=lambda _entry: False)
        self.parent = SimpleNamespace(
            reserve_actions=actions,
            toggle_preview=mock.Mock(),
            on_find_compatibles_requested=mock.Mock(),
            send_path_to_composer=mock.Mock(),
            app_context=SimpleNamespace(audio_player=SimpleNamespace(get_position=lambda: 0)),
            seek_preview=mock.Mock(return_value=True),
            go_to_parent_directory=mock.Mock(),
        )
        entry = ReserveEntry(
            source_kind="filesystem", path=self.path, display_name="Kick", duration=1.0,
        )
        self.row = DirectoryListItemWidget(entry, self.parent)
        self.row.resize(420, self.row.sizeHint().height())
        self.row.show()
        QApplication.processEvents()

    def tearDown(self):
        self.row.close()
        self.row.deleteLater()
        self.temp.cleanup()

    def test_clicking_name_selects_row_without_starting_preview(self):
        selected = mock.Mock()
        self.row.clicked.connect(selected)
        QTest.mouseClick(self.row.name_label, Qt.MouseButton.LeftButton)
        self.assertEqual(selected.call_count, 1)
        self.parent.toggle_preview.assert_not_called()

    def test_play_button_selects_and_starts_preview(self):
        selected = mock.Mock()
        self.row.clicked.connect(selected)
        QTest.mouseClick(self.row.play_button, Qt.MouseButton.LeftButton)
        self.assertEqual(selected.call_count, 1)
        self.parent.toggle_preview.assert_called_once_with(self.row)

    def test_hover_never_selects_or_starts_preview(self):
        selected = mock.Mock()
        self.row.clicked.connect(selected)
        QTest.mouseMove(self.row.name_label, self.row.name_label.rect().center())
        QApplication.processEvents()
        selected.assert_not_called()
        self.parent.toggle_preview.assert_not_called()

    def test_plain_arrows_seek_one_second_and_alt_left_navigates(self):
        self.row._duration_ms = 10_000
        self.parent.reserve_actions.is_previewing = lambda _entry: True
        self.parent.app_context.audio_player.get_position = lambda: 2_000
        self.row.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))
        self.parent.seek_preview.assert_called_with(self.row.entry, 1_000)
        self.row.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
        self.parent.seek_preview.assert_called_with(self.row.entry, 3_000)
        self.row.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier))
        self.parent.go_to_parent_directory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
