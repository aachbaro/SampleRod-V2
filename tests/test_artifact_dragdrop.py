import unittest

from frontend.dragdrop import DragItem, DragKind, DragPayload, MaterialStatus
from frontend.labo.artifact_tray import _payload_is_existing_artifact


class ArtifactDragDropTests(unittest.TestCase):
    def test_same_artifact_is_rejected_by_its_current_tray(self):
        payload = DragPayload(
            DragKind.ARTIFACT,
            (DragItem(item_id="artifact-1"),),
            status=MaterialStatus.ARTIFACT,
        )

        self.assertTrue(_payload_is_existing_artifact(payload, {"artifact-1": object()}))

    def test_another_artifact_can_still_be_received(self):
        payload = DragPayload(
            DragKind.ARTIFACT,
            (DragItem(item_id="artifact-2"),),
            status=MaterialStatus.ARTIFACT,
        )

        self.assertFalse(_payload_is_existing_artifact(payload, {"artifact-1": object()}))


if __name__ == "__main__":
    unittest.main()
