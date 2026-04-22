from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from backend.services.notification_service import NotificationService, NotificationType
from frontend.notification_widgets import NotificationCenter, NotificationManager


class NotificationManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_silent_notification_goes_to_center_without_popup(self):
        service = NotificationService()
        manager = NotificationManager(service)
        center = NotificationCenter()
        manager.set_center(center)

        service.notify(
            title="Verification",
            message="Notification de fond",
            type=NotificationType.INFO,
            popup=False,
        )

        self.assertEqual(len(center.notifications), 1)
        self.assertEqual(center.notifications[0].title, "Verification")
        self.assertFalse(center.notifications[0].popup)
        self.assertEqual(len(manager.popups), 0)


if __name__ == "__main__":
    unittest.main()
