from __future__ import annotations

import os
import pickle
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QMimeData, QUrl

from backend.services.reserve_import_service import (
    ReserveCopyPolicy,
    ReserveImportRequest,
    ReserveImportService,
    ReserveReimportPolicy,
)
from backend.services.directory_service import DirectoryService
from frontend.dragdrop import (
    AudioSelection,
    DragItem,
    DragKind,
    DragPayload,
    DragProvenance,
    MaterialOperation,
    MaterialStatus,
    attach_payload,
)
from frontend.reserve.reserve_import_adapters import import_request_from_mime


class FakeStore:
    def __init__(self):
        self.samples = []
        self.add_calls = []
        self.promote_calls = []
        self.deleted_records = []

    def get_cached(self):
        return list(self.samples)

    def add(self, path, material_metadata=None):
        sample = SimpleNamespace(id=len(self.samples) + 1, path=os.path.normpath(path))
        self.samples.append(sample)
        self.add_calls.append((sample.path, material_metadata))
        return sample

    def promote_to_source(self, path, metadata):
        self.promote_calls.append((path, metadata))
        promoted = os.path.join(os.path.dirname(path), "promoted.wav")
        return SimpleNamespace(id=99, path=promoted)

    def delete_record_by_path(self, path):
        self.deleted_records.append(os.path.normpath(path))
        self.samples = [sample for sample in self.samples if sample.path != os.path.normpath(path)]
        return True

    def _get(self, sample_id):
        return next((sample for sample in self.samples if sample.id == sample_id), None)


class ReserveImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FakeStore()
        self.service = ReserveImportService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def audio(self, name="audio.wav"):
        path = os.path.join(self.temp.name, name)
        with open(path, "wb") as stream:
            stream.write(b"audio")
        return os.path.normpath(path)

    def test_source_without_destination_is_indexed_in_place(self):
        source = self.audio()
        result = self.service.import_request(ReserveImportRequest((source,)))
        self.assertEqual(result.imported_samples[0].path, source)
        self.assertEqual(result.copied_paths, ())
        self.assertTrue(os.path.isfile(source))

    def test_derived_is_promoted_without_mutating_original(self):
        source = self.audio("slice.wav")
        request = ReserveImportRequest(
            (source,), status="derived", kind="audio_selection",
            provenance={"source_path": "original.wav", "start_seconds": 1.0, "end_seconds": 2.0},
        )
        result = self.service.import_request(request)
        self.assertTrue(result.success)
        self.assertTrue(os.path.isfile(source))
        metadata = self.store.promote_calls[0][1]
        self.assertEqual(metadata["material_status"], "source")
        self.assertEqual(metadata["provenance"]["previous_status"], "derived")
        self.assertEqual(metadata["provenance"]["operation"], "import")
        self.assertNotIn("parent_ids", metadata)

    def test_directory_copy_suffixes_collision_and_indexes_copy(self):
        source = self.audio("kick.wav")
        destination = os.path.join(self.temp.name, "target")
        os.makedirs(destination)
        with open(os.path.join(destination, "kick.wav"), "wb") as stream:
            stream.write(b"existing")
        request = ReserveImportRequest(
            (source,), destination=destination, copy_policy=ReserveCopyPolicy.COPY
        )
        result = self.service.import_request(request)
        self.assertTrue(result.copied_paths[0].endswith("kick_1.wav"))
        self.assertEqual(self.store.add_calls[0][0], result.copied_paths[0])

    def test_reimport_policy_is_explicit(self):
        source = self.audio()
        self.store.add(source)
        skipped = self.service.import_request(ReserveImportRequest((source,)))
        self.assertEqual(skipped.skipped, (source,))
        reimported = self.service.import_request(ReserveImportRequest(
            (source,), reimport_policy=ReserveReimportPolicy.REINDEX
        ))
        self.assertTrue(reimported.imported_samples)
        self.assertEqual(self.store.deleted_records, [source])

    def test_artifact_without_destination_keeps_existing_index_in_place_policy(self):
        artifact = self.audio("artifact.wav")
        result = self.service.import_request(ReserveImportRequest(
            (artifact,), status="artifact", kind="artifact",
            provenance={"source_path": artifact},
        ))
        self.assertEqual(result.imported_samples[0].path, artifact)
        self.assertEqual(self.store.promote_calls, [])
        metadata = self.store.add_calls[0][1]
        self.assertEqual(metadata["material_status"], "source")
        self.assertEqual(metadata["provenance"]["previous_status"], "artifact")
        self.assertEqual(metadata["provenance"]["previous_kind"], "artifact")
        self.assertEqual(metadata["provenance"]["operation"], "import")
        self.assertEqual(metadata["provenance"]["source_path"], artifact)

    def test_modern_payload_adapter_preserves_status_and_bounds(self):
        source = self.audio("selection.wav")
        mime = QMimeData()
        attach_payload(mime, DragPayload(
            DragKind.AUDIO_SELECTION,
            (DragItem(path=source),),
            selection=AudioSelection(1.25, 1.75, "original.wav", 48_000),
            status=MaterialStatus.DERIVED,
            provenance=DragProvenance("original.wav", MaterialOperation.SELECTION),
        ))
        request = import_request_from_mime(mime, sample_path_lookup=lambda _sid: None)
        self.assertEqual(request.paths, (source,))
        self.assertEqual(request.status, "derived")
        self.assertEqual(request.provenance["start_seconds"], 1.25)

    def test_legacy_urls_card_and_slice_are_decoded(self):
        source = self.audio("url.wav")
        url_mime = QMimeData()
        url_mime.setUrls([QUrl.fromLocalFile(source)])
        self.assertEqual(
            import_request_from_mime(url_mime, sample_path_lookup=lambda _sid: None).paths,
            (source,),
        )

        card_mime = QMimeData()
        card_mime.setData("application/x-sample-card", pickle.dumps({"sample_id": 7}))
        card = import_request_from_mime(card_mime, sample_path_lookup=lambda _sid: source)
        self.assertEqual(card.paths, (source,))
        self.assertEqual(card.status, "source")

        slice_mime = QMimeData()
        slice_mime.setData("application/x-sample-slice-data", pickle.dumps({
            "audio_data": np.zeros(16, dtype=np.float32), "sample_rate": 8000, "name": "slice"
        }))
        sliced = import_request_from_mime(slice_mime, sample_path_lookup=lambda _sid: None)
        self.assertEqual(sliced.status, "derived")
        self.assertTrue(sliced.paths and os.path.isfile(sliced.paths[0]))

        text_mime = QMimeData()
        text_mime.setData("application/x-sample-card", source.encode("utf-8"))
        textual = import_request_from_mime(text_mime, sample_path_lookup=lambda _sid: None)
        self.assertEqual(textual.paths, (source,))

    def test_legacy_card_and_slice_complete_the_directory_import(self):
        self.store.app_context = SimpleNamespace()
        self.store.app_context.reserve_imports = self.service
        directory = DirectoryService(self.store)
        destination = os.path.join(self.temp.name, "directory")

        source = self.audio("legacy-card.wav")
        tracked = self.store.add(source)
        card_mime = QMimeData()
        card_mime.setData(
            "application/x-sample-card", pickle.dumps({"sample_id": tracked.id})
        )
        card_result = directory.handle_drop(destination, card_mime)
        self.assertEqual(len(card_result.copied_paths), 1)
        self.assertTrue(os.path.isfile(card_result.copied_paths[0]))

        slice_mime = QMimeData()
        slice_mime.setData("application/x-sample-slice-data", pickle.dumps({
            "audio_data": np.zeros(32, dtype=np.float32),
            "sample_rate": 8000,
            "name": "legacy-slice",
        }))
        slice_result = directory.handle_drop(destination, slice_mime)
        self.assertEqual(len(slice_result.copied_paths), 1)
        self.assertTrue(os.path.isfile(slice_result.copied_paths[0]))
        slice_metadata = self.store.add_calls[-1][1]
        self.assertEqual(slice_metadata["material_status"], "source")
        self.assertEqual(slice_metadata["provenance"]["previous_status"], "derived")


if __name__ == "__main__":
    unittest.main()
