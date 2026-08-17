import unittest

from PySide6.QtWidgets import QApplication

from frontend.dragdrop import DragItem, DragKind, DragPayload, MaterialStatus
from frontend.dragdrop.preview import _status_label, drag_preview_pixmap


class DragPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _payload(self, kind, status):
        return DragPayload(kind, (DragItem(display_name="break.wav"),), status=status)

    def test_status_vocabulary_is_explicit(self):
        self.assertEqual(
            _status_label(self._payload(DragKind.AUDIO_FILE, MaterialStatus.SOURCE)),
            "SOURCE",
        )
        self.assertEqual(
            _status_label(self._payload(DragKind.AUDIO_SELECTION, MaterialStatus.DERIVED)),
            "DÉRIVÉ · SÉLECTION",
        )
        self.assertEqual(
            _status_label(self._payload(DragKind.STEM, MaterialStatus.DERIVED)),
            "DÉRIVÉ · STEM",
        )
        self.assertEqual(
            _status_label(self._payload(DragKind.ARTIFACT, MaterialStatus.ARTIFACT)),
            "ARTEFACT",
        )

    def test_each_status_renders_a_non_empty_preview(self):
        for kind, status in (
            (DragKind.AUDIO_FILE, MaterialStatus.SOURCE),
            (DragKind.AUDIO_SELECTION, MaterialStatus.DERIVED),
            (DragKind.ARTIFACT, MaterialStatus.ARTIFACT),
        ):
            with self.subTest(status=status):
                pixmap = drag_preview_pixmap(self._payload(kind, status))
                self.assertEqual((pixmap.width(), pixmap.height()), (248, 62))
                self.assertFalse(pixmap.isNull())


if __name__ == "__main__":
    unittest.main()
