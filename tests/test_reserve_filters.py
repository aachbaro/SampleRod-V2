from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend.reserve import ReserveFilterController, ReserveFilterState
from frontend.sample_gui.sample.sample_list import SampleListWidget


class ReserveFilterControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_and_spaces_are_the_same_neutral_query(self):
        controller = ReserveFilterController(debounce_ms=5)
        changed = mock.Mock()
        controller.queryChanged.connect(changed)
        controller.set_query("   ")
        QTest.qWait(10)
        changed.assert_not_called()
        self.assertEqual(controller.state.query, "")

    def test_rapid_typing_emits_only_the_last_query(self):
        controller = ReserveFilterController(debounce_ms=20)
        changed = mock.Mock()
        controller.queryChanged.connect(changed)
        for query in ("a", "am", "ame", "amen"):
            controller.set_query(query)
        QTest.qWait(35)
        changed.assert_called_once_with("amen")

    def test_new_query_after_expiration_emits_again(self):
        controller = ReserveFilterController(debounce_ms=5)
        changed = mock.Mock()
        controller.queryChanged.connect(changed)
        controller.set_query("amen")
        QTest.qWait(25)
        controller.set_query("break")
        QTest.qWait(25)
        self.assertEqual([call.args[0] for call in changed.call_args_list], ["amen", "break"])

    def test_explicit_filters_are_immediate_and_deduplicated(self):
        controller = ReserveFilterController(debounce_ms=100)
        status = mock.Mock()
        scale = mock.Mock()
        controller.statusChanged.connect(status)
        controller.scaleChanged.connect(scale)
        controller.set_status("missing")
        controller.set_status("missing")
        controller.set_scale("C# minor")
        controller.set_scale("C# minor")
        status.assert_called_once_with("missing")
        scale.assert_called_once_with("C# minor")

    def test_clear_all_restores_the_complete_neutral_state(self):
        controller = ReserveFilterController(debounce_ms=5)
        controller.set_query("amen")
        controller.flush_query()
        controller.set_status("missing")
        controller.set_scale("D minor")
        controller.set_compatibility(42)
        controller.set_scope("external")
        controller.clear_all()
        self.assertEqual(controller.state, ReserveFilterState())

    def test_recent_selection_drops_entries_hidden_by_a_filter(self):
        holder = SimpleNamespace(
            selected_ids={1, 2},
            setCurrentPage=mock.Mock(),
            get_filtered_samples=lambda: [SimpleNamespace(id=2)],
            updateSelectActions=mock.Mock(),
        )
        SampleListWidget._refresh_after_filter_change(holder)
        self.assertEqual(holder.selected_ids, {2})
        holder.setCurrentPage.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
