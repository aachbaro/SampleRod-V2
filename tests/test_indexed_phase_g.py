from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QTableWidget

from backend.services.audio_metadata import normalize_audio_path
from frontend.library_gui.library_widget import LibraryTableItem, LibraryWidget
from frontend.reserve import ReserveEntry, ReserveTechnicalStatus


class IndexedPhaseGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "beat.wav")
        with open(self.path, "wb") as stream:
            stream.write(b"audio-data")
        self.view = LibraryWidget.__new__(LibraryWidget)
        self.view._size_cache = {normalize_audio_path(self.path): 10}

    def entry(self, **values):
        defaults = dict(
            source_kind="indexed", sample_id=1, path=self.path,
            display_name="Beat", folder_path=self.temp.name,
            root_path=None, created_at=dt.datetime(2026, 1, 2, 12, 0),
            duration=62.14, rms_level=-13.2, indexed=True,
            dominant_note="C#", detected_scale_label="C# minor",
            detected_scale_kind="scale", status=ReserveTechnicalStatus.NORMAL,
        )
        defaults.update(values)
        return ReserveEntry(**defaults)

    def test_default_and_secondary_columns(self):
        definitions = LibraryWidget.COLUMN_DEFINITIONS
        self.assertEqual(
            [label for _key, label, visible in definitions if visible],
            ["Nom", "Gamme", "Dossier", "Durée", "Date", "Statut"],
        )
        self.assertEqual(
            [label for _key, label, visible in definitions if not visible],
            ["Racine", "Poids", "RMS", "Note dominante"],
        )

    def test_row_preserves_human_text_and_raw_sort_values(self):
        items = self.view._build_row_items(self.entry())
        self.assertEqual(len(items), 10)
        self.assertNotEqual(items[3].text(), "62.14")
        self.assertEqual(items[3].data(LibraryTableItem.SORT_ROLE), 62.14)
        self.assertIsInstance(items[4].data(LibraryTableItem.SORT_ROLE), float)
        self.assertEqual(items[7].data(LibraryTableItem.SORT_ROLE), 10)
        self.assertEqual(items[8].data(LibraryTableItem.SORT_ROLE), -13.2)

    def test_numeric_duration_date_and_size_sorting(self):
        table = QTableWidget(0, 10)
        self.addCleanup(table.deleteLater)
        entries = [
            self.entry(sample_id=1, duration=100.0, created_at=dt.datetime(2025, 1, 1)),
            self.entry(sample_id=2, duration=9.0, created_at=dt.datetime(2026, 1, 1)),
        ]
        table.setSortingEnabled(False)
        for row, entry in enumerate(entries):
            table.insertRow(row)
            for column, item in enumerate(self.view._build_row_items(entry)):
                table.setItem(row, column, item)
        table.setSortingEnabled(True)
        table.sortItems(LibraryWidget.COLUMN_INDEX["duration"], Qt.SortOrder.AscendingOrder)
        self.assertEqual(table.item(0, 0).data(LibraryWidget.TABLE_SAMPLE_ID_ROLE), 2)
        table.sortItems(LibraryWidget.COLUMN_INDEX["date"], Qt.SortOrder.AscendingOrder)
        self.assertEqual(table.item(0, 0).data(LibraryWidget.TABLE_SAMPLE_ID_ROLE), 1)

    def test_missing_and_external_information_remain_available(self):
        entry = self.entry(
            root_path=None, source_kind="indexed", missing=True,
            status=ReserveTechnicalStatus.MISSING,
        )
        items = self.view._build_row_items(entry)
        self.assertEqual(items[5].text(), "Fichier manquant")
        self.assertEqual(items[6].text(), "Externes")
        self.assertIn(self.path, items[0].toolTip())

    def test_table_rows_use_items_not_cell_widgets(self):
        table = QTableWidget(1, 10)
        self.addCleanup(table.deleteLater)
        for column, item in enumerate(self.view._build_row_items(self.entry())):
            table.setItem(0, column, item)
        self.assertTrue(all(table.cellWidget(0, column) is None for column in range(10)))

    def test_column_visibility_is_persisted_with_versioned_key(self):
        settings_path = os.path.join(self.temp.name, "columns.ini")
        settings = QSettings(settings_path, QSettings.Format.IniFormat)
        table = mock.Mock()
        holder = SimpleNamespace(
            table=table,
            _qs=settings,
            COLUMN_VISIBILITY_PREFIX=LibraryWidget.COLUMN_VISIBILITY_PREFIX,
        )
        LibraryWidget._set_column_visible(holder, 6, "root", True)
        table.setColumnHidden.assert_called_once_with(6, False)
        self.assertTrue(settings.value("library_columns_v1/root", False, type=bool))


if __name__ == "__main__":
    unittest.main()
