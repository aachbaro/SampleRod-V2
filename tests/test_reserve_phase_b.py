from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

from frontend.dragdrop import MaterialStatus
from frontend.reserve.reserve_capabilities import reserve_capabilities_for
from frontend.reserve.reserve_formatters import (
    format_reserve_date,
    format_reserve_duration,
    format_reserve_rms,
    format_reserve_scale,
    format_reserve_size,
    reserve_date_sort_value,
)
from frontend.reserve.reserve_status import (
    ReserveTechnicalStatus,
    coerce_reserve_technical_status,
)
from frontend.reserve.reserve_entry import (
    STATUS_MISSING,
    STATUS_NEEDS_ANALYSIS,
    STATUS_NON_INDEXED,
    STATUS_NORMAL,
    ReserveEntry,
    reserve_status_label,
)
from frontend.sample_gui.sample.sample_card_ui import SampleCardUIBuilder


class ReservePhaseBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_technical_status_is_string_compatible_and_distinct_from_material(self):
        self.assertEqual(ReserveTechnicalStatus.NEEDS_ANALYSIS, "needs_analysis")
        self.assertIsNot(ReserveTechnicalStatus.NORMAL, MaterialStatus.SOURCE)
        self.assertIs(
            coerce_reserve_technical_status("missing"),
            ReserveTechnicalStatus.MISSING,
        )
        self.assertEqual(STATUS_NORMAL, "normal")
        self.assertEqual(STATUS_NON_INDEXED, "non_indexed")
        self.assertEqual(STATUS_NEEDS_ANALYSIS, "needs_analysis")
        self.assertEqual(STATUS_MISSING, "missing")
        self.assertEqual(reserve_status_label("missing"), "Fichier manquant")

    def test_entry_exposes_pure_capabilities_and_recent_source_label(self):
        entry = ReserveEntry(
            source_kind="history",
            path="C:/audio/kick.wav",
            sample_id=2,
            indexed=True,
        )
        self.assertEqual(entry.source_label, "Récents")
        self.assertTrue(entry.capabilities.has_database_record)
        self.assertTrue(entry.capabilities.can_unindex)

    def test_capabilities_are_descriptive_for_unindexed_and_missing_entries(self):
        loose = SimpleNamespace(
            path="C:/audio/loose.wav", indexed=False, sample_id=None, missing=False
        )
        missing = SimpleNamespace(
            path="C:/audio/missing.wav", indexed=True, sample_id=4, missing=True
        )
        loose_caps = reserve_capabilities_for(loose)
        missing_caps = reserve_capabilities_for(missing)
        self.assertTrue(loose_caps.can_preview)
        self.assertTrue(loose_caps.can_drag)
        self.assertFalse(loose_caps.can_unindex)
        self.assertTrue(missing_caps.can_unindex)
        self.assertFalse(missing_caps.can_preview)
        self.assertFalse(missing_caps.can_analyze)

    def test_common_formatters_keep_human_text_and_numeric_sort_value(self):
        date = dt.datetime(2026, 8, 17, 10, 42)
        self.assertEqual(format_reserve_date(date), "17/08/2026 10:42")
        self.assertEqual(reserve_date_sort_value(date), date.timestamp())
        self.assertEqual(format_reserve_duration(62.14), "1 min 02 s")
        self.assertEqual(format_reserve_duration(1.5, compact=True), "1.5s")
        self.assertEqual(format_reserve_size(5_161_004), "4.9 Mo")
        self.assertEqual(format_reserve_rms(0.12345), "0.123")
        self.assertEqual(
            format_reserve_scale(SimpleNamespace(
                detected_scale_label="C# phrygian", dominant_note="C#"
            )),
            "C# phrygian",
        )

    def test_card_menu_says_unindex_but_keeps_existing_callback(self):
        card = QWidget()
        self.addCleanup(card.deleteLater)
        card.onNormalizeButtonClicked = mock.Mock()
        card.toggleWaveform = mock.Mock()
        card.header_actions = SimpleNamespace(start_rename=mock.Mock())
        card.change_dir_combobox = SimpleNamespace()
        card.onArchiveClicked = mock.Mock()
        card.confirmDelete = mock.Mock()

        menu = SampleCardUIBuilder(card)._build_options_menu(card)
        texts = [action.text() for action in menu.actions()]

        self.assertIn("Désindexer\tCtrl+Shift+D", texts)
        unindex_action = next(
            action for action in menu.actions() if action.text().startswith("Désindexer")
        )
        unindex_action.trigger()
        card.onArchiveClicked.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
