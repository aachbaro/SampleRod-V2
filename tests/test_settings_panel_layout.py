from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from frontend.settings_gui.settings_panel import ResponsiveSettingsPage, SettingsCard

_app = QApplication.instance() or QApplication([])


class ResponsiveSettingsPageTests(unittest.TestCase):
    @staticmethod
    def _page():
        return ResponsiveSettingsPage([
            SettingsCard(str(i), "", QLabel("contenu")) for i in range(3)
        ])

    def test_narrow_page_uses_one_column(self):
        page = self._page()
        page.resize(600, 500)
        page.show()
        QTest.qWait(10)
        self.assertEqual(page.column_count, 1)
        page.close()

    def test_wide_page_uses_two_columns(self):
        page = self._page()
        page.resize(1000, 500)
        page.show()
        QTest.qWait(10)
        self.assertEqual(page.column_count, 2)
        page.close()


if __name__ == "__main__":
    unittest.main()
