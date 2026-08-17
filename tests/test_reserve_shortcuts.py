from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem, QWidget

from frontend.library_gui.library_widget import LibraryWidget
from frontend.sample_gui.sample.sample_list import SampleListWidget
from frontend.right_panel.directory.directory_list_widget import DirectoryListWidget


class _ShortcutHarness(QWidget):
    def __getattr__(self, name):
        if name.startswith("_"):
            handler = mock.Mock(name=name)
            setattr(self, name, handler)
            return handler
        raise AttributeError(name)


class ReserveShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _sequences(self, builder, attribute):
        harness = _ShortcutHarness()
        self.addCleanup(harness.deleteLater)
        builder(harness)
        return {shortcut.key().toString() for shortcut in getattr(harness, attribute)}

    def test_recent_shortcuts_are_locked(self):
        sequences = self._sequences(
            SampleListWidget._build_shortcuts, "_history_shortcuts"
        )
        self.assertEqual(sequences, {
            "Up", "Down", "Left", "Right", "Space", "Shift+Space",
            "Ctrl+Right", "Ctrl+R", "Ctrl+D", "Ctrl+Shift+D",
        })

    def test_index_shortcuts_are_locked(self):
        sequences = self._sequences(
            LibraryWidget._build_shortcuts, "_indexed_shortcuts"
        )
        self.assertEqual(sequences, {
            "Up", "Down", "Left", "Right", "Space", "Shift+Space",
            "Ctrl+Right", "Ctrl+R", "Ctrl+D", "Ctrl+Shift+D",
        })

    def test_directory_action_keys_are_delegated_to_current_row(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        view = DirectoryListWidget(parent)
        self.addCleanup(view.deleteLater)
        row = QWidget()
        row.keyPressEvent = mock.Mock()
        item = QListWidgetItem(view)
        view.addItem(item)
        view.setItemWidget(item, row)
        view.setCurrentItem(item)

        for key in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Right,
            Qt.Key.Key_Return,
            Qt.Key.Key_Left,
            Qt.Key.Key_F2,
            Qt.Key.Key_Delete,
        ):
            event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
            view.keyPressEvent(event)

        self.assertEqual(row.keyPressEvent.call_count, 6)

    def test_directory_alt_left_navigates_even_without_selection(self):
        parent = _ShortcutHarness()
        self.addCleanup(parent.deleteLater)
        parent.go_to_parent_directory = mock.Mock()
        view = DirectoryListWidget(parent)
        self.addCleanup(view.deleteLater)
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.AltModifier,
        )
        view.keyPressEvent(event)
        parent.go_to_parent_directory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
