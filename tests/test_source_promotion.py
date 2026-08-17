import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from sqlalchemy import create_engine

from frontend.dragdrop import (
    AudioSelection, DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus, source_promotion_metadata,
)
from backend.services.reserve_import_service import ReserveImportRequest, ReserveImportService
from backend.models.sample import Sample, decode_material_metadata, encode_material_metadata
from backend.services.sample_service import SampleService
from backend import db


class SourcePromotionMetadataTests(unittest.TestCase):
    def _payload(self):
        return DragPayload(
            DragKind.AUDIO_SELECTION,
            (DragItem(display_name="slice"),),
            selection=AudioSelection(1.25, 1.75, "C:/audio/source.wav", 48_000),
            status=MaterialStatus.DERIVED,
            provenance=DragProvenance(
                "C:/audio/source.wav", MaterialOperation.SELECTION
            ),
        )

    def test_metadata_contains_only_the_lightweight_provenance(self):
        metadata = source_promotion_metadata(self._payload())

        self.assertEqual(metadata["material_status"], "source")
        self.assertEqual(metadata["provenance"], {
            "previous_status": "derived",
            "previous_kind": "audio_selection",
            "operation": "import",
            "source_path": "C:/audio/source.wav",
            "start_seconds": 1.25,
            "end_seconds": 1.75,
        })
        self.assertNotIn("parent_ids", metadata)
        self.assertNotIn("generation", metadata)

    def test_old_empty_or_invalid_metadata_remains_readable(self):
        self.assertIn("material_metadata", Sample.__table__.columns)
        self.assertEqual(decode_material_metadata(None), {})
        self.assertEqual(decode_material_metadata("not-json"), {})
        self.assertEqual(decode_material_metadata("[]"), {})
        encoded = encode_material_metadata({"material_status": "source"})
        self.assertEqual(decode_material_metadata(encoded), {"material_status": "source"})

    def test_legacy_sqlite_schema_gains_nullable_metadata_column(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "legacy.db")
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE samples (id INTEGER PRIMARY KEY, path VARCHAR(200))"
                )
                connection.exec_driver_sql(
                    "INSERT INTO samples (id, path) VALUES (1, 'old.wav')"
                )
            with mock.patch.object(db, "engine", engine), mock.patch.object(
                db, "DATABASE_URL", f"sqlite:///{path}"
            ):
                db.ensure_sqlite_schema()
            with engine.begin() as connection:
                columns = {
                    row[1] for row in connection.exec_driver_sql(
                        "PRAGMA table_info(samples)"
                    ).fetchall()
                }
                old = connection.exec_driver_sql(
                    "SELECT path, material_metadata FROM samples WHERE id=1"
                ).fetchone()
            self.assertIn("material_metadata", columns)
            self.assertEqual(tuple(old), ("old.wav", None))
            engine.dispose()

    def test_reserve_promotes_derived_but_not_regular_source(self):
        promoted = []
        store = SimpleNamespace(
            promote_to_source=lambda path, metadata: (
                promoted.append((path, metadata)) or SimpleNamespace(path="promoted.wav")
            ),
            get_cached=lambda: [],
            add=lambda path: SimpleNamespace(path=path),
        )
        service = ReserveImportService(store)
        with mock.patch("backend.services.reserve_import_service.os.path.isfile", return_value=True):
            service.import_request(ReserveImportRequest(
                ("slice.wav",), status="derived", kind="audio_selection",
                provenance={"source_path": "C:/audio/source.wav"},
            ))
        self.assertEqual(os.path.basename(promoted[0][0]), "slice.wav")
        with mock.patch("backend.services.reserve_import_service.os.path.isfile", return_value=True):
            service.import_request(ReserveImportRequest(("source.wav",), status="source"))
        self.assertEqual(len(promoted), 1)

    def test_service_copies_before_adding_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "derived.wav")
            with open(source, "wb") as handle:
                handle.write(b"derived-audio")
            durable = os.path.join(folder, "durable")
            added = []
            fake_service = SimpleNamespace(
                add=lambda path, material_metadata=None: (
                    added.append((path, material_metadata)) or SimpleNamespace(path=path)
                )
            )
            with mock.patch(
                "backend.services.sample_service.QStandardPaths.writableLocation",
                return_value=durable,
            ):
                result = SampleService.promote_to_source(
                    fake_service, source, {"material_status": "source"}
                )

            self.assertIsNotNone(result)
            self.assertTrue(os.path.isfile(source))
            self.assertNotEqual(added[0][0], source)
            self.assertTrue(os.path.isfile(added[0][0]))
            self.assertIn(
                os.path.join("SampleRod", "promoted_sources"), added[0][0]
            )


if __name__ == "__main__":
    unittest.main()
