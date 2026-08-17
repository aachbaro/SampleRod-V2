from __future__ import annotations

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QProgressBar, QVBoxLayout, QWidget

from frontend.reserve.reserve_entry import ReserveEntry
from frontend.right_panel.directory import directory_ui
from frontend.right_panel.directory.directory_index import DirectoryIndexController
from frontend.right_panel.directory.directory_item_widget import DirectoryListItemWidget, DirectorySectionHeader
from frontend.right_panel.directory.directory_list_builder import DirectoryListBuilder
from frontend.right_panel.directory.directory_list_widget import DirectoryListWidget
from frontend.right_panel.directory.directory_navigation import DirectoryNavigationController
from frontend.right_panel.directory.directory_selection import DirectorySelectionController


class _UiHost(QWidget):
    def __init__(self):
        super().__init__()
        self.root_dir = ""
        self.current_dir = ""
        for name in (
            "choose_root_directory", "go_to_parent_directory", "index_current_directory",
            "clear_compatible_scales_filter", "open_directory",
        ):
            setattr(self, name, mock.Mock())


class DirectoryPhaseETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_is_compact_and_permanent_shortcut_bar_is_hidden(self):
        host = _UiHost()
        self.addCleanup(host.deleteLater)
        directory_ui.build_directory_widget_ui(host)
        self.assertFalse(host.up_button.isHidden())
        self.assertFalse(host.shortcuts_bar.isVisible())
        self.assertIn("Espace", host.help_button.toolTip())
        self.assertEqual(host.index_button.text(), "Synchroniser")

    def test_long_breadcrumb_is_bounded_and_ancestors_are_clickable(self):
        host = _UiHost()
        self.addCleanup(host.deleteLater)
        directory_ui.build_directory_widget_ui(host)
        host.root_dir = os.path.normpath("C:/very-long-root-name-that-must-not-grow")
        path = os.path.join(host.root_dir, "samples-with-a-very-long-name", "drums", "breaks")
        directory_ui.set_directory_path(host, path)
        buttons = host.breadcrumb_widget.findChildren(QPushButton)
        self.assertTrue(buttons)
        self.assertTrue(all(button.maximumWidth() <= 130 for button in buttons))
        clickable = [button for button in buttons if button.cursor().shape() == Qt.CursorShape.PointingHandCursor]
        self.assertTrue(clickable)
        clickable[0].click()
        host.open_directory.assert_called_once()

    def test_parent_navigation_can_leave_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            child = os.path.join(root, "child")
            os.makedirs(child)
            widget = SimpleNamespace(current_dir=root, root_dir=root)
            controller = DirectoryNavigationController(widget)
            controller.open_directory = mock.Mock()
            controller.go_to_parent_directory()
            controller.open_directory.assert_called_once_with(os.path.normpath(temp))

    def test_index_summary_and_sync_states_use_human_wording(self):
        service = SimpleNamespace(
            is_indexing=lambda: False,
            get_folder_index_status=lambda _path: {
                "label": "Non indexe", "on_disk": 8934, "tracked": 680, "missing": 1,
            },
        )
        host = SimpleNamespace(
            current_dir=os.path.normpath("C:/audio"), service=service,
            files_count_label=QLabel(), index_summary_label=QLabel(), status_label=QLabel(),
            progress_label=QLabel(), index_progress=QProgressBar(), index_button=QPushButton(),
        )
        controller = DirectoryIndexController(host)
        controller._refresh_index_status()
        self.assertEqual(host.files_count_label.text(), "8 934 fichiers audio")
        self.assertEqual(host.index_summary_label.text(), "680 indexés · 1 manquant")
        self.assertEqual(host.index_button.text(), "Synchroniser")
        controller._on_index_progress(host.current_dir, 2430, 8934, "technical message")
        self.assertEqual(host.index_summary_label.text(), "Synchronisation…  2 430 / 8 934")
        self.assertEqual(host.index_button.text(), "Synchronisation…")

    def test_section_headers_are_inert_and_keyboard_skips_them(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        view = DirectoryListWidget(parent)
        self.addCleanup(view.deleteLater)
        harness = SimpleNamespace(list_widget=view)
        builder = DirectoryListBuilder(harness)
        builder._add_section_header("Dossiers")
        first = view.item(0)
        self.assertEqual(first.flags(), Qt.ItemFlag.NoItemFlags)
        self.assertIsInstance(view.itemWidget(first), DirectorySectionHeader)

        selectable = view.item(1) if view.count() > 1 else None
        if selectable is None:
            from PySide6.QtWidgets import QListWidgetItem
            selectable = QListWidgetItem(view)
            selectable.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            view.addItem(selectable)
            view.setItemWidget(selectable, QWidget())
        view.setCurrentRow(-1)
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
        self.assertIs(view.currentItem(), selectable)

    def test_sections_only_exist_when_their_content_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            view = QListWidget()
            self.addCleanup(view.deleteLater)
            widget = SimpleNamespace(
                current_dir=temp, list_widget=view, _items_by_id={}, _rows_by_path={},
                _folder_rows_by_path={}, _selected_path=None, _selected_folder_path=None,
                service=SimpleNamespace(list_audio_entries=lambda _folder: []),
                _reserve_query_text="", _reserve_status_filter="all", _compat_filter_scales=set(),
                _update_files_count_label=mock.Mock(), detail_widget=SimpleNamespace(clear_entry=mock.Mock()),
                reserveEntrySelected=SimpleNamespace(emit=mock.Mock()), _sync_detail_preview_state=mock.Mock(),
                _sync_preview_row_state=mock.Mock(), _select_folder_path=mock.Mock(),
            )
            DirectoryListBuilder(widget).refresh_list()
            self.assertEqual(view.count(), 0)

            os.mkdir(os.path.join(temp, "only-folder"))
            widget._on_subfolder_clicked = mock.Mock()
            DirectoryListBuilder(widget).refresh_list()
            labels = [view.itemWidget(view.item(i)).text() for i in range(view.count()) if isinstance(view.itemWidget(view.item(i)), QLabel)]
            self.assertEqual(labels, ["DOSSIERS"])

    def test_narrow_row_keeps_actionable_status_and_hides_secondary_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "a-very-long-file-name-that-needs-elision.wav")
            open(path, "wb").close()
            store = mock.Mock()
            parent = SimpleNamespace(
                embedded_in_reserve=True,
                reserve_actions=SimpleNamespace(is_previewing=lambda _entry: False),
                toggle_preview=mock.Mock(), on_find_compatibles_requested=mock.Mock(),
                send_path_to_composer=mock.Mock(), app_context=SimpleNamespace(
                    audio_player=SimpleNamespace(get_position=lambda: 0), sample_store=store,
                ),
            )
            entry = ReserveEntry(
                source_kind="filesystem", path=path, display_name=os.path.basename(path),
                duration=12.0, indexed=False, status="non_indexed",
            )
            row = DirectoryListItemWidget(entry, parent)
            self.addCleanup(row.deleteLater)
            row.setFixedWidth(245)
            row._apply_compact_visibility()
            QApplication.processEvents()
            self.assertTrue(row.status_badge.isVisibleTo(row))
            self.assertFalse(row.duration_chip.isVisibleTo(row))
            self.assertFalse(row.playback_slider.isVisible())
            store.add.assert_not_called()

    def test_large_flat_folder_does_not_add_extra_scans_or_audio_work(self):
        entries = [ReserveEntry(source_kind="filesystem", path=f"C:/audio/{i}.wav") for i in range(2000)]
        fake_list = SimpleNamespace(
            setUpdatesEnabled=mock.Mock(), clear=mock.Mock(), clearSelection=mock.Mock(),
            setCurrentItem=mock.Mock(),
        )
        widget = SimpleNamespace(
            current_dir="C:/audio", list_widget=fake_list,
            _items_by_id={}, _rows_by_path={}, _folder_rows_by_path={},
            _selected_path=None, _selected_folder_path=None,
            service=SimpleNamespace(list_audio_entries=mock.Mock(return_value=entries)),
            _build_reserve_entry=lambda entry: entry,
            _reserve_query_text="", _reserve_status_filter="all", _compat_filter_scales=set(),
            _update_files_count_label=mock.Mock(), _select_path=mock.Mock(),
            _select_folder_path=mock.Mock(), _sync_preview_row_state=mock.Mock(),
            detail_widget=SimpleNamespace(clear_entry=mock.Mock()),
            _sync_detail_preview_state=mock.Mock(),
            reserveEntrySelected=SimpleNamespace(emit=mock.Mock()),
        )
        builder = DirectoryListBuilder(widget)
        builder._add_section_header = mock.Mock()
        builder._add_row_direct = mock.Mock()
        started = time.perf_counter()
        with mock.patch("frontend.right_panel.directory.directory_list_builder.os.listdir", return_value=[]):
            builder.refresh_list()
        self.assertEqual(builder._add_row_direct.call_count, 2000)
        builder._add_section_header.assert_called_once_with("Fichiers")
        widget.service.list_audio_entries.assert_called_once_with("C:/audio")
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_refresh_does_not_select_first_file_implicitly(self):
        entry = ReserveEntry(source_kind="filesystem", path="C:/audio/one.wav")
        fake_list = SimpleNamespace(
            setUpdatesEnabled=mock.Mock(), clear=mock.Mock(), clearSelection=mock.Mock(),
            setCurrentItem=mock.Mock(),
        )
        widget = SimpleNamespace(
            current_dir="C:/audio", list_widget=fake_list,
            _items_by_id={}, _rows_by_path={}, _folder_rows_by_path={},
            _selected_path=None, _selected_folder_path=None,
            service=SimpleNamespace(list_audio_entries=lambda _folder: [entry]),
            _build_reserve_entry=lambda value: value,
            _reserve_query_text="", _reserve_status_filter="all", _compat_filter_scales=set(),
            _update_files_count_label=mock.Mock(), _select_path=mock.Mock(),
            _select_folder_path=mock.Mock(), _sync_preview_row_state=mock.Mock(),
            detail_widget=SimpleNamespace(clear_entry=mock.Mock()),
            _sync_detail_preview_state=mock.Mock(),
            reserveEntrySelected=SimpleNamespace(emit=mock.Mock()),
        )
        builder = DirectoryListBuilder(widget)
        builder._add_section_header = mock.Mock()
        builder._add_row_direct = mock.Mock()
        with mock.patch("frontend.right_panel.directory.directory_list_builder.os.listdir", return_value=[]):
            builder.refresh_list()
        widget._select_path.assert_not_called()
        fake_list.clearSelection.assert_called_once_with()
        widget.reserveEntrySelected.emit.assert_called_once_with(None)

    def test_incidental_current_item_change_does_not_feed_inspector(self):
        list_widget = SimpleNamespace(
            _keyboard_selection_in_progress=False,
            currentItem=mock.Mock(),
        )
        widget = SimpleNamespace(list_widget=list_widget)
        DirectorySelectionController(widget)._on_list_selection_changed()
        list_widget.currentItem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
