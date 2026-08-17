import unittest

from frontend.dragdrop import (
    DragItem, DragKind, DragPayload, DropAction,
    DropAcceptance, MaterialStatus, describe_drop,
)


class DragDescriptionTests(unittest.TestCase):
    def _payload(self, status, kind=DragKind.AUDIO_FILE):
        return DragPayload(kind, (DragItem(display_name="audio"),), status=status)

    def test_create_artifact_label_varies_without_changing_action(self):
        action = DropAction.CREATE_ARTIFACT
        self.assertEqual(
            describe_drop(action, self._payload(MaterialStatus.SOURCE)),
            "Créer un artefact depuis la source",
        )
        self.assertEqual(
            describe_drop(action, self._payload(MaterialStatus.DERIVED)),
            "Conserver cette transformation",
        )
        source_acceptance = DropAcceptance.accept(
            action, describe_drop(action, self._payload(MaterialStatus.SOURCE))
        )
        derived_acceptance = DropAcceptance.accept(
            action, describe_drop(action, self._payload(MaterialStatus.DERIVED))
        )
        self.assertIs(source_acceptance.action, DropAction.CREATE_ARTIFACT)
        self.assertIs(derived_acceptance.action, DropAction.CREATE_ARTIFACT)
        self.assertTrue(source_acceptance.accepted)
        self.assertTrue(derived_acceptance.accepted)

    def test_reserve_describes_derived_as_a_new_source(self):
        label = describe_drop(
            DropAction.IMPORT_AS_SOURCE,
            self._payload(MaterialStatus.DERIVED, DragKind.AUDIO_SELECTION),
        )
        self.assertEqual(label, "Ajouter comme nouvelle source")


if __name__ == "__main__":
    unittest.main()
