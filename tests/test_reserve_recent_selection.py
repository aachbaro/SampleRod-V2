from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from frontend.sample_gui.sample.sample_list_selection import SampleListSelection
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination


class _CheckBox:
    def __init__(self):
        self.checked = False

    def setChecked(self, checked):
        self.checked = bool(checked)


class ReserveRecentSelectionTests(unittest.TestCase):
    def _widget(self):
        actions = {
            name: SimpleNamespace(setEnabled=mock.Mock())
            for name in (
                "bulk_delete_act", "bulk_move_act", "bulk_normalize_act",
                "bulk_archive_act", "select_all_btn", "deselect_all_btn",
            )
        }
        cards = {sid: SimpleNamespace(checkbox=_CheckBox()) for sid in (51, 52)}
        return SimpleNamespace(
            selected_ids=set(),
            _card_widgets=cards,
            **actions,
        )

    def test_select_all_only_checks_instantiated_current_page_cards(self):
        widget = self._widget()
        selection = SampleListSelection(widget)

        selection.select_all()

        self.assertTrue(all(card.checkbox.checked for card in widget._card_widgets.values()))
        self.assertEqual(set(widget._card_widgets), {51, 52})

    def test_checkbox_selection_enables_all_bulk_actions(self):
        widget = self._widget()
        selection = SampleListSelection(widget)

        selection.on_selection_changed(51, True)

        self.assertEqual(widget.selected_ids, {51})
        for name in (
            "bulk_delete_act", "bulk_move_act", "bulk_normalize_act",
            "bulk_archive_act",
        ):
            getattr(widget, name).setEnabled.assert_called_with(True)

    def test_deselecting_last_item_disables_all_bulk_actions(self):
        widget = self._widget()
        widget.selected_ids.add(51)
        selection = SampleListSelection(widget)

        selection.on_selection_changed(51, False)

        self.assertEqual(widget.selected_ids, set())
        for name in (
            "bulk_delete_act", "bulk_move_act", "bulk_normalize_act",
            "bulk_archive_act",
        ):
            getattr(widget, name).setEnabled.assert_called_with(False)

    def test_pagination_uses_configured_page_size_and_stops_at_last_page(self):
        widget = SimpleNamespace(
            current_page=1,
            samples_per_page=50,
            filtered_samples=[SimpleNamespace(id=index) for index in range(120)],
            get_filtered_samples=lambda: [],
        )
        pagination = SampleListPagination(widget)
        pagination.change_page = mock.Mock()

        pagination.next_page()
        pagination.change_page.assert_called_once_with(2)

        pagination.change_page.reset_mock()
        widget.current_page = 3
        pagination.next_page()
        pagination.change_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
