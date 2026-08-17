from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from frontend.ui.lazy_widget import LazyWidgetHost

_app = QApplication.instance() or QApplication([])


class LazyWidgetHostTests(unittest.TestCase):
    def test_hidden_host_does_not_construct_its_content(self):
        calls = []
        host = LazyWidgetHost(lambda: calls.append(1) or QLabel("pret"), "chargement")
        QTest.qWait(45)
        self.assertEqual(calls, [])
        self.assertIsNone(host.loaded_widget)
        host.deleteLater()

    def test_first_visibility_loads_after_the_placeholder_can_render(self):
        calls = []
        host = LazyWidgetHost(lambda: calls.append(1) or QLabel("pret"), "chargement")
        host.show()
        self.assertEqual(calls, [])
        QTest.qWait(45)
        self.assertEqual(calls, [1])
        self.assertEqual(host.loaded_widget.text(), "pret")
        host.close()
        host.deleteLater()

    def test_content_is_constructed_only_once(self):
        calls = []
        host = LazyWidgetHost(lambda: calls.append(1) or QLabel("pret"), "chargement")
        host.show()
        QTest.qWait(45)
        host.hide()
        host.show()
        host.ensure_loaded()
        QTest.qWait(45)
        self.assertEqual(calls, [1])
        host.close()
        host.deleteLater()


if __name__ == "__main__":
    unittest.main()
