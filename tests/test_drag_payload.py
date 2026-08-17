import json
import unittest

from PySide6.QtCore import QMimeData, QUrl

from frontend.dragdrop import (
    AudioSelection,
    DragProvenance,
    DragItem,
    DragKind,
    DragPayload,
    MaterialOperation,
    MaterialStatus,
    PAYLOAD_MIME,
    attach_payload,
    payload_from_mime,
)


class DragPayloadTests(unittest.TestCase):
    def test_payload_json_round_trip_is_descriptive_only(self):
        payload = DragPayload(
            kind=DragKind.AUDIO_SELECTION,
            items=(DragItem(item_id="slice-1", display_name="Kick", duration=0.25),),
            source_id="marker-list",
            source_module="waveform",
            selection=AudioSelection(1.0, 1.25, "C:/audio/source.wav", 48_000),
            status=MaterialStatus.DERIVED,
            provenance=DragProvenance(
                source_path="C:/audio/source.wav",
                operation=MaterialOperation.SELECTION,
            ),
            metadata={"classification": "kick"},
        )
        mime = QMimeData()

        attach_payload(mime, payload)

        encoded = bytes(mime.data(PAYLOAD_MIME))
        self.assertNotIn(b"numpy", encoded.lower())
        self.assertEqual(payload_from_mime(mime), payload)
        self.assertEqual(json.loads(encoded)["version"], 1)

    def test_legacy_payload_infers_status_only_when_missing(self):
        cases = {
            DragKind.AUDIO_FILE: MaterialStatus.SOURCE,
            DragKind.MULTIPLE_AUDIO: MaterialStatus.SOURCE,
            DragKind.AUDIO_SELECTION: MaterialStatus.DERIVED,
            DragKind.STEM: MaterialStatus.DERIVED,
            DragKind.ARTIFACT: MaterialStatus.ARTIFACT,
        }
        for kind, expected in cases.items():
            with self.subTest(kind=kind):
                payload = DragPayload.from_dict({
                    "version": 1,
                    "kind": kind.value,
                    "items": [],
                })
                self.assertIs(payload.status, expected)
                self.assertIsNone(payload.provenance)

    def test_explicit_status_is_never_replaced_by_inference(self):
        payload = DragPayload(
            kind=DragKind.AUDIO_FILE,
            items=(),
            status=MaterialStatus.ARTIFACT,
        )

        self.assertIs(payload.status, MaterialStatus.ARTIFACT)

    def test_invalid_descriptor_does_not_fall_through_to_urls(self):
        mime = QMimeData()
        mime.setData(PAYLOAD_MIME, b'{"version":999}')
        mime.setUrls([QUrl.fromLocalFile("C:/audio/kick.wav")])

        self.assertIsNone(payload_from_mime(mime))

    def test_legacy_multiple_urls_are_adapted_without_mutation(self):
        mime = QMimeData()
        mime.setUrls([
            QUrl.fromLocalFile("C:/audio/kick.wav"),
            QUrl.fromLocalFile("C:/audio/snare.wav"),
        ])

        payload = payload_from_mime(mime)

        self.assertIsNotNone(payload)
        self.assertIs(payload.kind, DragKind.MULTIPLE_AUDIO)
        self.assertEqual(
            [item.display_name for item in payload.items], ["kick.wav", "snare.wav"]
        )
        self.assertTrue(mime.hasUrls())


if __name__ == "__main__":
    unittest.main()
