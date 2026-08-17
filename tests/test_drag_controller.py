import unittest

from PySide6.QtCore import QEvent, QMimeData
from PySide6.QtWidgets import QApplication, QWidget

from frontend.dragdrop import (
    DragDropController,
    DragItem,
    DragKind,
    DragPayload,
    DropAcceptance,
)


def _payload():
    return DragPayload(DragKind.AUDIO_FILE, (DragItem(display_name="Kick"),))


class DragControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_compatible_target_then_hover_and_cleanup(self):
        controller = DragDropController()
        widget = QWidget()
        widget.resize(200, 100)
        widget.show()
        self.app.processEvents()
        controller.register_target(
            "waveform", widget,
            lambda payload: DropAcceptance.accept("open", "Ouvrir")
            if payload.kind is DragKind.AUDIO_FILE else DropAcceptance.reject(),
        )

        controller.start_drag(_payload())
        entry = controller._targets["waveform"]
        self.assertTrue(entry.overlay.isVisible())
        acceptance = controller.enter_target("waveform", QMimeData())
        self.assertTrue(acceptance.accepted)
        self.assertEqual(entry.overlay.text(), "Ouvrir")

        controller.finish_drag()
        self.assertIsNone(controller.payload)
        self.assertFalse(entry.overlay.isVisible())
        widget.close()

    def test_hidden_and_incompatible_targets_are_not_highlighted(self):
        controller = DragDropController()
        hidden = QWidget()
        incompatible = QWidget()
        incompatible.show()
        self.app.processEvents()
        controller.register_target(
            "hidden", hidden, lambda _: DropAcceptance.accept("open", "Ouvrir")
        )
        controller.register_target(
            "no", incompatible, lambda _: DropAcceptance.reject("unsupported")
        )

        controller.start_drag(_payload())

        self.assertFalse(controller._targets["hidden"].overlay.isVisible())
        self.assertFalse(controller._targets["no"].overlay.isVisible())
        controller.finish_drag()
        hidden.close()
        incompatible.close()

    def test_destroyed_target_is_unregistered(self):
        controller = DragDropController()
        widget = QWidget()
        controller.register_target("temporary", widget, lambda _: DropAcceptance.reject())

        widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

        self.assertNotIn("temporary", controller._targets)


if __name__ == "__main__":
    unittest.main()
