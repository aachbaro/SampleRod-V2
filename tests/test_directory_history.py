from __future__ import annotations

import tempfile
import unittest

from PySide6.QtCore import QSettings

from frontend.right_panel.directory.directory_history import DirectoryHistory


class DirectoryHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._settings_path = f"{self._tmpdir.name}/directory_history.ini"
        self.settings = QSettings(self._settings_path, QSettings.Format.IniFormat)
        self.history = DirectoryHistory(self.settings)

    def tearDown(self):
        self.settings.clear()
        self.settings.sync()
        self._tmpdir.cleanup()

    def test_last_directory_and_root_directory_are_persisted_separately(self):
        self.history.set_last_root_directory("C:/samples")
        self.history.set_last_directory("C:/samples/drums/amen")
        self.settings.sync()

        restored_settings = QSettings(self._settings_path, QSettings.Format.IniFormat)
        restored = DirectoryHistory(restored_settings)

        self.assertEqual(restored.get_last_root_directory(), "C:/samples")
        self.assertEqual(restored.get_last_directory(), "C:/samples/drums/amen")

    def test_expanded_directories_are_persisted_and_deduplicated(self):
        self.history.add_expanded_directory("C:/samples")
        self.history.add_expanded_directory("C:/samples/drums")
        self.history.add_expanded_directory("C:/samples")
        self.settings.sync()

        restored_settings = QSettings(self._settings_path, QSettings.Format.IniFormat)
        restored = DirectoryHistory(restored_settings)

        self.assertEqual(
            restored.get_expanded_directories(),
            ["C:/samples/drums", "C:/samples"],
        )


if __name__ == "__main__":
    unittest.main()
