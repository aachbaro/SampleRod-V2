# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal de l'onglet "Bibliotheque" (et aussi utilise comme sous-
#   vue dans la Reserve quand embedded_in_reserve=True).
# - Affiche un arbre de navigation (racines / dossiers) a gauche, un tableau
#   de samples au centre, et un panneau de detail a droite.
# - Supporte le glisser-deposer : un sample peut etre glisse vers le Labo ou
#   un autre widget.
#
# FONCTIONS (sommaire)
# - LibraryWidget              : widget principal (arbre + tableau + detail)
# - _configure_table()         : configure les colonnes et les modes de resize
# - _bind_signals()            : connecte store, settings, recherche, selection
# - _refresh_navigation()      : reconstruit l'arbre a partir du LibraryService
# - _refresh_table()           : filtre et peuple le tableau selon le scope actuel
# - _sync_detail_with_selection() : met a jour le panneau de detail
# - set_compatible_scales_filter() : active le filtre de gammes compatibles
# - open_waveform_for_entry()  : selectionne une ligne et ouvre la waveform
# - eventFilter()              : detecte le debut d'un drag depuis le tableau
# - _start_drag_from_selection() : lance un QDrag avec les donnees MIME du sample
#
# LIENS CLES
# - backend/services/library_service.py      : calcul de la navigation et du filtrage
# - frontend/library_gui/library_detail.py   : panneau de detail (detail_widget)
# - frontend/library_gui/library_ui.py       : construction de l'interface
# - frontend/reserve/reserve_entry.py        : type ReserveEntry
# -----------------------------------------------------------------------------

from __future__ import annotations

from collections import Counter
import json
import logging
import os
import pickle
import queue
import threading
from time import perf_counter

from PySide6.QtCore import QEvent, QMimeData, Qt, QTimer, QUrl, Signal, QSettings
from PySide6.QtGui import QColor, QDrag, QKeySequence, QShortcut
from frontend.dragdrop import (
    DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus,
    attach_payload, drag_preview_pixmap, drag_session,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHeaderView,
    QLineEdit,
    QMenu,
    QSlider,
    QTableWidgetItem,
    QTreeWidgetItem,
    QWidget,
)

from backend.services.audio_metadata import normalize_audio_path
from backend.services.library_service import LibraryNavNode, LibraryScope, LibraryService
from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    reserve_entry_from_sample,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
    reserve_status_label,
    reserve_status_tone,
    format_reserve_date,
    format_reserve_duration,
    format_reserve_rms,
    format_reserve_scale,
    format_reserve_size,
    reserve_date_sort_value,
)
from frontend.styles import theme
from frontend.ui import themed_icon

from . import library_ui
from .library_detail import LibraryDetailWidget

logger = logging.getLogger("library_widget")


class LibraryTableItem(QTableWidgetItem):
    """Human-readable cell with an independent deterministic sort value."""

    SORT_ROLE = Qt.ItemDataRole.UserRole + 20

    def __lt__(self, other) -> bool:
        left = self.data(self.SORT_ROLE)
        right = other.data(self.SORT_ROLE) if isinstance(other, QTableWidgetItem) else None
        if left is not None and right is not None:
            try:
                return left < right
            except TypeError:
                return str(left) < str(right)
        return super().__lt__(other)


def pending_hidden_refresh_requires_render(
    pending_snapshot, *, quick_update_unrendered: bool, pending_signature, rendered_signature
) -> bool:
    return pending_snapshot is not None and (
        quick_update_unrendered or pending_signature != rendered_signature
    )


class LibraryWidget(QWidget):
    """Vue bibliotheque pour naviguer dans les samples indexes.

    Peut fonctionner en mode autonome (onglet Bibliotheque de la fenetre
    principale) ou en mode integre dans la Reserve (embedded_in_reserve=True),
    auquel cas la barre de recherche et le filtre sont masques (la Reserve
    les gere elle-meme a travers set_reserve_query / set_reserve_status_filter).

    Signal :
        reserveEntrySelected(ReserveEntry | None) : emis quand la selection change.
    """

    TREE_SCOPE_KIND_ROLE = Qt.ItemDataRole.UserRole
    TREE_SCOPE_VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
    TABLE_SAMPLE_ID_ROLE = Qt.ItemDataRole.UserRole
    SCALE_FILTER_ALL = "__all__"
    SCALE_FILTER_NONE = "__none__"
    COLUMN_DEFINITIONS = (
        ("name", "Nom", True),
        ("scale", "Gamme", True),
        ("folder", "Dossier", True),
        ("duration", "Durée", True),
        ("date", "Date", True),
        ("status", "Statut", True),
        ("root", "Racine", False),
        ("size", "Poids", False),
        ("rms", "RMS", False),
        ("note", "Note dominante", False),
    )
    COLUMN_INDEX = {
        "name": 0, "scale": 1, "folder": 2, "duration": 3, "date": 4,
        "status": 5, "root": 6, "size": 7, "rms": 8, "note": 9,
    }
    COLUMN_VISIBILITY_PREFIX = "library_columns_v1"

    reserveEntrySelected = Signal(object)
    reserveScaleFilterRequested = Signal(str)
    reserveScopeChanged = Signal(str, object)

    def __init__(
        self,
        app_context,
        parent=None,
        reserve_actions: ReserveActions | None = None,
        embedded_in_reserve: bool = False,
    ):
        super().__init__(parent)
        self.app_context = app_context
        self.sample_store = self.app_context.sample_store
        self.settings = self.app_context.settings
        self._qs = QSettings("SampleRod", "Main")
        self.library_service = LibraryService(self.settings, self.sample_store)
        self.reserve_actions = reserve_actions
        self.embedded_in_reserve = embedded_in_reserve
        self.samples = self.library_service.get_cached_samples()
        self.filtered_entries: list[ReserveEntry] = []
        self.current_scope = LibraryScope("all")
        self._selected_sample_id: int | None = None
        self._reserve_query_text = ""
        self._reserve_status_filter = "all"
        self._scale_filter_value = self.SCALE_FILTER_ALL
        self._compat_filter_scales: set[str] = set()
        self._entries_by_sample_id: dict[int, ReserveEntry] = {}
        self._drag_start_pos = None
        self._pending_selected_row: int | None = None
        self._skip_next_full_table_refresh = False
        self._last_render_signature = None
        self._nav_visible = True
        self._nav_last_width = 220
        self._navigation_dirty = False
        self._size_cache: dict[str, int | None] = {}
        self._size_requested: set[str] = set()
        self._size_input_queue: queue.Queue[str | None] = queue.Queue()
        self._size_result_queue: queue.Queue[tuple[str, int | None]] = queue.Queue()
        self._size_worker_stop = threading.Event()
        self._pending_samples_snapshot: list | None = None
        self._store_refresh_timer = QTimer(self)
        self._store_refresh_timer.setSingleShot(True)
        self._store_refresh_timer.setInterval(30)
        self._store_refresh_timer.timeout.connect(self._apply_pending_store_refresh)
        self._navigation_refresh_timer = QTimer(self)
        self._navigation_refresh_timer.setSingleShot(True)
        self._navigation_refresh_timer.setInterval(250)
        self._navigation_refresh_timer.timeout.connect(self._refresh_navigation_if_dirty)
        self._size_result_timer = QTimer(self)
        self._size_result_timer.setInterval(75)
        self._size_result_timer.timeout.connect(self._drain_size_results)
        self._size_result_timer.start()
        self._size_worker = threading.Thread(
            target=self._size_worker_loop,
            daemon=True,
            name="library-size-worker",
        )
        self._size_worker.start()
        self.destroyed.connect(lambda *_args: self._stop_size_worker())

        self.detail_widget = LibraryDetailWidget(
            self.app_context,
            reserve_actions=self.reserve_actions,
        )
        library_ui.build_library_widget_ui(self)
        self._configure_table()
        self._build_shortcuts()
        self._bind_signals()
        self._restore_navigation_visibility()
        self._request_size_scan()
        self._refresh_navigation()
        self._refresh_table()
        theme.manager.themeChanged.connect(self._on_theme_changed)

        if self.embedded_in_reserve:
            self.search_input.hide()
            self.status_filter.hide()
            self.scale_filter.hide()
            self.title_label.hide()
            self.nav_toggle_button.hide()
            self.table_title.hide()
            # ReservePane fournit l'unique inspecteur visible. Le détail
            # historique reste instancié comme adaptateur pendant D2.
            self.detail_widget.hide()

    def _configure_table(self):
        """Configure les modes de redimensionnement des colonnes et installe le filtre d'evenements."""
        header = self.table.horizontalHeader()
        for column in range(len(self.COLUMN_DEFINITIONS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_INDEX["name"], QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COLUMN_INDEX["folder"], QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(self.COLUMN_INDEX["folder"], 150)
        self.table.setMinimumWidth(360)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.viewport().installEventFilter(self)
        self._build_columns_menu()

    def _build_columns_menu(self) -> None:
        menu = QMenu(self.columns_button)
        self._column_actions = {}
        for index, (key, label, default_visible) in enumerate(self.COLUMN_DEFINITIONS):
            visible = self._qs.value(
                f"{self.COLUMN_VISIBILITY_PREFIX}/{key}",
                default_visible,
                type=bool,
            )
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(bool(visible))
            action.toggled.connect(
                lambda checked, column=index, column_key=key: self._set_column_visible(
                    column, column_key, checked
                )
            )
            self._column_actions[key] = action
            self.table.setColumnHidden(index, not visible)
        self.columns_button.setMenu(menu)

    def _set_column_visible(self, column: int, key: str, visible: bool) -> None:
        self.table.setColumnHidden(column, not bool(visible))
        self._qs.setValue(f"{self.COLUMN_VISIBILITY_PREFIX}/{key}", bool(visible))

    def _restore_navigation_visibility(self) -> None:
        visible = self._qs.value("library_nav_visible", True, type=bool)
        self.set_navigation_visible(bool(visible), persist=False)

    def _update_nav_toggle_button(self) -> None:
        if not hasattr(self, "nav_toggle_button"):
            return
        if self._nav_visible:
            self.nav_toggle_button.set_icon_name("chevron-left")
            self.nav_toggle_button.setToolTip("Masquer la navigation")
        else:
            self.nav_toggle_button.set_icon_name("chevron-right")
            self.nav_toggle_button.setToolTip("Afficher la navigation")

    def toggle_navigation_visibility(self) -> None:
        self.set_navigation_visible(not self._nav_visible)

    def set_navigation_visible(self, visible: bool, *, persist: bool = True) -> None:
        """Affiche/masque la colonne de navigation.

        Le splitter n'a que deux volets depuis que le detail est passe sous la
        table : navigation | contenu.
        """
        visible = bool(visible)
        current_sizes = self.splitter.sizes()
        total = sum(current_sizes) or max(self.width(), 1000)
        if visible:
            self.nav_panel.show()
            nav_width = max(180, int(self._nav_last_width or 220))
            self.splitter.setSizes([nav_width, max(480, total - nav_width)])
            self._refresh_navigation_if_dirty()
        else:
            if current_sizes and current_sizes[0] > 0:
                self._nav_last_width = int(current_sizes[0])
            self.nav_panel.hide()
            self.splitter.setSizes([0, max(480, total)])
        self._nav_visible = visible
        self._update_nav_toggle_button()
        if persist:
            self._qs.setValue("library_nav_visible", visible)

    def _bind_signals(self):
        """Connecte le store, les settings, la recherche et la selection."""
        self.sample_store.samplesChanged.connect(self.on_samples_changed)
        self.sample_store.sampleAdded.connect(self._on_sample_added_quick)
        self.sample_store.sampleDeleted.connect(self._on_sample_deleted_quick)
        self.sample_store.sampleRenamed.connect(self._on_sample_renamed_quick)
        self.sample_store.sampleMoved.connect(self._on_sample_moved_quick)
        self.sample_store.sampleDurationChanged.connect(self._on_sample_duration_changed_quick)
        self.settings.librariesChanged.connect(lambda *_args: self._reload_from_store())
        # Refresh de la table quand une analyse de gamme se termine
        self.sample_store.sampleScaleAnalyzed.connect(self._on_sample_scale_analyzed)
        self.search_input.textChanged.connect(lambda *_args: self._refresh_table())
        self.status_filter.currentIndexChanged.connect(lambda *_args: self._refresh_table())
        self.scale_filter.currentIndexChanged.connect(self._on_scale_filter_changed)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_args: self.detail_widget.toggle_waveform())
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.nav_toggle_button.clicked.connect(self.toggle_navigation_visibility)

    def _build_shortcuts(self) -> None:
        self._indexed_shortcuts = []
        bindings = [
            ("Up", lambda: self._select_relative_row(-1)),
            ("Down", lambda: self._select_relative_row(1)),
            ("Left", lambda: self._seek_current_preview(-1000)),
            ("Right", lambda: self._seek_current_preview(1000)),
            ("Space", self._toggle_current_preview),
            ("Shift+Space", self._restart_current_preview),
            ("Ctrl+Right", self._open_current_waveform),
            ("Ctrl+R", self._rename_current_sample),
            ("Ctrl+D", self._delete_current_sample),
            ("Ctrl+Shift+D", self._remove_current_from_history),
        ]
        for seq, handler in bindings:
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self._indexed_shortcuts.append(shortcut)

    def _on_scale_filter_changed(self) -> None:
        self._scale_filter_value = str(self.scale_filter.currentData() or self.SCALE_FILTER_ALL)
        self._refresh_table()

    def _set_scale_filter_value(self, value: str) -> None:
        value = value or self.SCALE_FILTER_ALL
        index = self.scale_filter.findData(value)
        if index >= 0:
            self.scale_filter.setCurrentIndex(index)
            return
        self._scale_filter_value = value
        self._refresh_table()

    def _scale_label_for_entry(self, entry: ReserveEntry) -> str:
        label = format_reserve_scale(entry)
        return "" if label == "-" else label

    def _scale_filter_key_for_entry(self, entry: ReserveEntry) -> str:
        label = self._scale_label_for_entry(entry)
        return label if label else self.SCALE_FILTER_NONE

    def _matches_scale_filter(self, entry: ReserveEntry) -> bool:
        if self._scale_filter_value == self.SCALE_FILTER_ALL:
            return True
        if self._scale_filter_value == self.SCALE_FILTER_NONE:
            return not self._scale_label_for_entry(entry)
        return self._scale_label_for_entry(entry) == self._scale_filter_value

    def _refresh_scale_filter_options(self, entries: list[ReserveEntry]) -> None:
        counts = Counter(self._scale_filter_key_for_entry(entry) for entry in entries)
        previous_value = str(self._scale_filter_value or self.SCALE_FILTER_ALL)

        self.scale_filter.blockSignals(True)
        self.scale_filter.clear()
        self.scale_filter.addItem("Toutes les gammes", self.SCALE_FILTER_ALL)

        if counts.get(self.SCALE_FILTER_NONE):
            self.scale_filter.addItem(
                f"Sans gamme ({counts[self.SCALE_FILTER_NONE]})",
                self.SCALE_FILTER_NONE,
            )

        scale_labels = sorted(
            label
            for label in counts.keys()
            if label not in {self.SCALE_FILTER_ALL, self.SCALE_FILTER_NONE}
        )
        for label in scale_labels:
            self.scale_filter.addItem(f"{label} ({counts[label]})", label)

        if previous_value not in {self.SCALE_FILTER_ALL, self.SCALE_FILTER_NONE} and previous_value not in scale_labels:
            self.scale_filter.addItem(f"{previous_value} (0)", previous_value)

        target_index = self.scale_filter.findData(previous_value)
        if target_index < 0:
            target_index = 0
            previous_value = self.SCALE_FILTER_ALL
        self.scale_filter.setCurrentIndex(target_index)
        self.scale_filter.blockSignals(False)
        self._scale_filter_value = previous_value

    def _format_scale(self, entry: ReserveEntry) -> str:
        label = self._scale_label_for_entry(entry)
        return label or "-"

    @staticmethod
    def _root_label_for_entry(entry: ReserveEntry) -> str:
        if entry.indexed and not entry.root_path:
            return "Externes"
        return entry.root_name

    def _active_query_text(self) -> str:
        return self._reserve_query_text if self.embedded_in_reserve else self.search_input.text()

    def _active_status_filter_value(self) -> str:
        return self._reserve_status_filter if self.embedded_in_reserve else (self.status_filter.currentData() or "all")

    def _matches_current_scope(self, sample) -> bool:
        scoped = self.library_service.filter_samples(
            [sample],
            scope=self.current_scope,
            search_text="",
            status_filter=LibraryService.STATUS_ALL,
        )
        return bool(scoped)

    def _matches_active_filters(self, entry: ReserveEntry, sample) -> bool:
        if not reserve_entry_matches_query(entry, self._active_query_text()):
            return False
        if not reserve_entry_matches_status(entry, self._active_status_filter_value()):
            return False
        if self._compat_filter_scales:
            raw = getattr(sample, "compatible_scales", None) or ""
            try:
                sample_scales = set(json.loads(raw)) if raw else set()
            except (ValueError, TypeError):
                sample_scales = set()
            if not (sample_scales & self._compat_filter_scales):
                return False
        if not self._matches_scale_filter(entry):
            return False
        return True

    def _build_row_items(self, entry: ReserveEntry) -> tuple[QTableWidgetItem, ...]:
        name_item = LibraryTableItem(entry.display_name)
        name_item.setData(self.TABLE_SAMPLE_ID_ROLE, int(entry.sample_id or -1))
        name_item.setData(LibraryTableItem.SORT_ROLE, entry.display_name.casefold())

        scale_item = LibraryTableItem(self._format_scale(entry))
        scale_item.setData(LibraryTableItem.SORT_ROLE, self._scale_label_for_entry(entry).casefold())

        folder_item = LibraryTableItem(entry.folder_name)
        folder_item.setData(LibraryTableItem.SORT_ROLE, entry.folder_name.casefold())
        root_label = self._root_label_for_entry(entry)
        root_item = LibraryTableItem(root_label)
        root_item.setData(LibraryTableItem.SORT_ROLE, root_label.casefold())
        created_item = LibraryTableItem(self._format_created_at(entry.created_at))
        created_item.setData(LibraryTableItem.SORT_ROLE, self._sort_value_for_created_at(entry.created_at))

        duration_item = LibraryTableItem(self._format_duration(entry))
        duration_item.setData(LibraryTableItem.SORT_ROLE, float(entry.duration or 0.0))

        size_value = self._size_cache.get(normalize_audio_path(entry.path))
        size_item = LibraryTableItem(self._size_text_for_path(entry.path))
        size_item.setData(LibraryTableItem.SORT_ROLE, int(size_value) if size_value is not None else -1)

        rms_item = LibraryTableItem(format_reserve_rms(entry.rms_level))
        rms_item.setData(LibraryTableItem.SORT_ROLE, float(entry.rms_level) if entry.rms_level is not None else float("-inf"))
        note_item = LibraryTableItem(entry.dominant_note or "-")
        note_item.setData(LibraryTableItem.SORT_ROLE, (entry.dominant_note or "").casefold())

        status_label = reserve_status_label(entry.status)
        status_value = str(getattr(entry.status, "value", entry.status)).strip().lower()
        status_item = LibraryTableItem("" if status_value == "normal" else status_label)
        status_item.setData(LibraryTableItem.SORT_ROLE, status_label.casefold())

        common_tooltip = f"{entry.path}\nRacine : {root_label}"
        for item in (name_item, folder_item, root_item, created_item, duration_item, status_item, rms_item, note_item):
            item.setToolTip(common_tooltip)
        scale_item.setToolTip(self._format_scale_tooltip(entry))
        size_item.setToolTip(self._size_tooltip_for_path(entry.path))

        tone = reserve_status_tone(entry.status)
        if tone == "error":
            color = QColor(theme.manager.p.ERROR)
        elif tone == "warning":
            color = QColor(theme.manager.p.WARNING)
        elif tone == "info":
            color = QColor(theme.manager.p.INFO)
        else:
            color = QColor(theme.manager.p.TEXT)

        status_item.setForeground(color)

        return (
            name_item,
            scale_item,
            folder_item,
            duration_item,
            created_item,
            status_item,
            root_item,
            size_item,
            rms_item,
            note_item,
        )

    def _apply_row_items_to_table(self, row: int, entry: ReserveEntry) -> None:
        for column, item in enumerate(self._build_row_items(entry)):
            self.table.setItem(row, column, item)

    def _refresh_detail_for_sample(self, sample_id: int, entry: ReserveEntry) -> None:
        if self._selected_sample_id != sample_id:
            return
        sample = next((item for item in self.samples if int(item.id) == sample_id), None)
        if sample is None:
            return
        self.detail_widget.set_sample(sample, entry, self.library_service)

    def _refresh_navigation_if_dirty(self) -> None:
        if not self._navigation_dirty:
            return
        if not self._nav_visible:
            return
        self._refresh_navigation()
        self._navigation_dirty = False

    def _schedule_navigation_refresh(self) -> None:
        if not self._navigation_dirty:
            return
        if not self._nav_visible:
            return
        if not self.isVisible():
            return
        self._navigation_refresh_timer.start()

    def _format_scale_tooltip(self, entry: ReserveEntry) -> str:
        lines = []
        label = self._scale_label_for_entry(entry)
        if label:
            prefix = "Gamme" if entry.detected_scale_kind == "scale" else "Note dominante"
            confidence = (
                f" ({float(entry.scale_confidence):.0%})"
                if entry.scale_confidence is not None
                else ""
            )
            lines.append(f"{prefix}: {label}{confidence}")
        else:
            lines.append("Gamme: non detectee")
        if entry.compatible_scales:
            lines.append("Compatibles: " + ", ".join(entry.compatible_scales))
        lines.append(entry.path)
        return "\n".join(lines)

    @staticmethod
    def _format_created_at(value) -> str:
        return format_reserve_date(value)

    @staticmethod
    def _sort_value_for_created_at(value) -> float:
        return reserve_date_sort_value(value)

    def _stop_size_worker(self) -> None:
        if self._size_worker_stop.is_set():
            return
        self._size_worker_stop.set()
        try:
            self._size_input_queue.put_nowait(None)
        except Exception:
            pass

    def _all_sample_paths(self) -> list[str]:
        paths: list[str] = []
        for sample in self.samples:
            path = str(getattr(sample, "path", "") or "").strip()
            if path:
                paths.append(normalize_audio_path(path))
        return paths

    def _request_size_scan(self) -> None:
        current_paths = set(self._all_sample_paths())
        self._size_cache = {
            path: size
            for path, size in self._size_cache.items()
            if path in current_paths
        }
        self._size_requested.intersection_update(current_paths)
        for path in current_paths:
            if path in self._size_cache or path in self._size_requested:
                continue
            self._size_requested.add(path)
            self._size_input_queue.put(path)
        self._refresh_size_display()

    def _size_worker_loop(self) -> None:
        while not self._size_worker_stop.is_set():
            try:
                path = self._size_input_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if path is None:
                break
            try:
                size = int(os.path.getsize(path))
            except OSError:
                size = None
            self._size_result_queue.put((path, size))

    def _drain_size_results(self) -> None:
        changed = False
        drained = 0
        while drained < 256:
            try:
                path, size = self._size_result_queue.get_nowait()
            except queue.Empty:
                break
            self._size_requested.discard(path)
            self._size_cache[path] = size
            changed = True
            drained += 1
        if changed:
            self._refresh_size_display()

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        return format_reserve_size(size_bytes)

    def _size_text_for_path(self, path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return "-"
        normalized = normalize_audio_path(path)
        if normalized not in self._size_cache:
            return "..."
        size = self._size_cache.get(normalized)
        if size is None:
            return "-"
        return self._format_file_size(size)

    def _size_tooltip_for_path(self, path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return "Poids indisponible"
        normalized = normalize_audio_path(path)
        if normalized not in self._size_cache:
            return "Calcul du poids en cours...\n" + normalized
        size = self._size_cache.get(normalized)
        if size is None:
            return "Poids indisponible (fichier manquant ou inaccessible)\n" + normalized
        return f"{self._format_file_size(size)} ({size} bytes)\n{normalized}"

    def _size_stats_for_paths(self, paths: list[str]) -> tuple[int, int, int]:
        unique_paths: list[str] = []
        seen: set[str] = set()
        for path in paths:
            path = str(path or "").strip()
            if not path:
                continue
            normalized = normalize_audio_path(path)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_paths.append(normalized)

        total_count = len(unique_paths)
        resolved_count = 0
        size_sum = 0
        for path in unique_paths:
            if path not in self._size_cache:
                continue
            resolved_count += 1
            size = self._size_cache.get(path)
            if size is not None:
                size_sum += int(size)
        return total_count, resolved_count, size_sum

    def _format_size_progress(self, paths: list[str]) -> str:
        total_count, resolved_count, size_sum = self._size_stats_for_paths(paths)
        if total_count <= 0:
            return "-"
        if resolved_count <= 0:
            return "calcul..."
        prefix = ">= " if resolved_count < total_count else ""
        return prefix + self._format_file_size(size_sum)

    def _refresh_count_label(self) -> None:
        visible_paths = [entry.path for entry in self.filtered_entries if getattr(entry, "path", "")]
        total_paths = self._all_sample_paths()
        self.count_label.setText(
            " | ".join(
                [
                    f"{len(self.filtered_entries)} sample{'s' if len(self.filtered_entries) != 1 else ''}",
                    f"visible: {self._format_size_progress(visible_paths)}",
                    f"total indexe: {self._format_size_progress(total_paths)}",
                ]
            )
        )

    def _refresh_size_display(self) -> None:
        self._refresh_count_label()
        # The visual row order may differ from filtered_entries while Qt sort
        # is active. Resolve every row through its stable sample id so an async
        # size result never lands on the wrong sample.
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, self.COLUMN_INDEX["name"])
            if id_item is None:
                continue
            sample_id = int(id_item.data(self.TABLE_SAMPLE_ID_ROLE) or -1)
            entry = self._entries_by_sample_id.get(sample_id)
            if entry is None:
                continue
            size_item = self.table.item(row, self.COLUMN_INDEX["size"])
            if size_item is None:
                continue
            size_item.setText(self._size_text_for_path(entry.path))
            size_item.setToolTip(self._size_tooltip_for_path(entry.path))
            path = str(getattr(entry, "path", "") or "").strip()
            normalized = normalize_audio_path(path) if path else ""
            size_value = self._size_cache.get(normalized) if normalized else None
            size_item.setData(
                LibraryTableItem.SORT_ROLE,
                int(size_value) if size_value is not None else -1,
            )

    def _should_handle_shortcuts(self) -> bool:
        if not self.isVisible():
            return False
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return True
        if focus_widget is self:
            return True
        if not self.isAncestorOf(focus_widget):
            return False
        return not isinstance(focus_widget, (QLineEdit, QComboBox, QSlider, QMenu))

    def _select_row(self, row: int) -> bool:
        if row < 0 or row >= self.table.rowCount():
            return False
        self.table.selectRow(row)
        self.table.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def _select_relative_row(self, delta: int) -> None:
        if not self._should_handle_shortcuts():
            return
        row_count = self.table.rowCount()
        if row_count <= 0:
            return
        current_row = self.table.currentRow()
        if current_row < 0:
            target = 0 if delta >= 0 else row_count - 1
        else:
            target = max(0, min(row_count - 1, current_row + delta))
        self._select_row(target)

    def _current_card(self):
        return self.detail_widget.current_card()

    def _toggle_current_preview(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is not None:
            card.togglePlay()
            return
        if self.reserve_actions is not None:
            self.reserve_actions.preview(self.current_reserve_entry())

    def _restart_current_preview(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        entry = self.current_reserve_entry()
        if card is None or entry is None:
            return
        is_playing = self.app_context.reserve_preview.restart(entry)
        card.playback._apply_state(is_playing)
        if is_playing:
            card.playback.update_slider()

    def _seek_current_preview(self, delta_ms: int) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        entry = self.current_reserve_entry()
        if card is None or entry is None:
            return
        duration_ms = max(0, int(float(getattr(card.sample, "duration", 0.0) or 0.0) * 1000))
        if duration_ms <= 0:
            return
        controller = self.app_context.reserve_preview
        current_position = 0
        if controller.is_active(entry):
            current_position = max(0, int(self.app_context.audio_player.get_position()))
        target = max(0, min(duration_ms, current_position + int(delta_ms)))
        is_playing = controller.seek(entry, target)
        card.playback._apply_state(is_playing)
        card.playback.update_slider()

    def _open_current_waveform(self) -> None:
        if not self._should_handle_shortcuts():
            return
        self.detail_widget.toggle_waveform()

    def _rename_current_sample(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is not None:
            card.startRename()

    def _prepare_row_after_mutation(self) -> None:
        current_row = self.table.currentRow()
        row_count = self.table.rowCount()
        if current_row < 0 or row_count <= 0:
            self._pending_selected_row = None
            return
        if current_row < row_count - 1:
            self._pending_selected_row = current_row
        elif current_row > 0:
            self._pending_selected_row = current_row - 1
        else:
            self._pending_selected_row = 0

    def _delete_current_sample(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        entry = self.current_reserve_entry()
        if card is None or entry is None or entry.sample_id is None:
            return
        self._prepare_row_after_mutation()
        self.detail_widget.clear_sample()
        self._selected_sample_id = None
        QTimer.singleShot(
            0,
            lambda current_entry=entry: self.app_context.reserve_mutations.delete_file_and_record(
                current_entry
            ),
        )

    def _remove_current_from_history(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._prepare_row_after_mutation()
        card.onArchiveClicked()

    def _stop_audio_for_entry(self, entry: ReserveEntry) -> None:
        controller = getattr(self.app_context, "reserve_preview", None)
        if controller is not None:
            controller.stop(entry)
            return
        player = self.app_context.audio_player
        target_sample_id = int(entry.sample_id or -1)
        target_path = os.path.normpath(str(entry.path or ""))
        current_sample_id = int(getattr(player, "current_sample_id", -1))
        current_path = os.path.normpath(str(getattr(player, "current_sample_path", "") or ""))
        if current_sample_id != target_sample_id and current_path != target_path:
            return
        try:
            player.clear_audio()
        except Exception:
            pass

    def _show_table_context_menu(self, position) -> None:
        row = self.table.rowAt(position.y())
        if row >= 0:
            self._select_row(row)
        entry = self.current_reserve_entry()
        card = self._current_card()
        if entry is None:
            return

        menu = QMenu(self)
        open_wave_action = menu.addAction(
            themed_icon("wave", size=16, color=theme.manager.p.TEXT_MUTED),
            "Ouvrir dans la waveform\tCtrl+Right",
        )
        open_wave_action.setEnabled(self.reserve_actions.can_open_waveform(entry) if self.reserve_actions else True)
        open_wave_action.triggered.connect(self._open_current_waveform)

        rename_action = menu.addAction(
            themed_icon("pencil", size=16, color=theme.manager.p.TEXT_MUTED),
            "Renommer\tCtrl+R",
        )
        rename_action.setEnabled(card is not None and not entry.missing)
        rename_action.triggered.connect(self._rename_current_sample)

        open_folder_action = menu.addAction(
            themed_icon("folder", size=16, color=theme.manager.p.TEXT_MUTED),
            "Ouvrir le dossier source",
        )
        open_folder_action.setEnabled(self.reserve_actions.can_reveal_in_folder(entry) if self.reserve_actions else True)
        open_folder_action.triggered.connect(self.detail_widget.open_current_folder)

        analyze_action = menu.addAction(
            themed_icon("music", size=16, color=theme.manager.p.INFO),
            "Analyser la gamme",
        )
        analyze_action.setEnabled(entry.sample_id is not None and not entry.missing)
        analyze_action.triggered.connect(
            lambda: self.sample_store.batch_analyze_ids([entry.sample_id])
        )

        scale_label = self._scale_label_for_entry(entry)
        if scale_label:
            filter_scale_action = menu.addAction(
                themed_icon("music", size=16, color=theme.manager.p.INFO),
                f"Filtrer par {scale_label}",
            )
            filter_scale_action.triggered.connect(
                lambda checked=False, value=scale_label: self._request_scale_filter(value)
            )

        menu.addSeparator()

        remove_history_action = menu.addAction(
            themed_icon("x", size=16, color=theme.manager.p.TEXT_MUTED),
            "Désindexer\tCtrl+Shift+D",
        )
        remove_history_action.setEnabled(card is not None)
        remove_history_action.triggered.connect(self._remove_current_from_history)

        delete_action = menu.addAction(
            themed_icon("trash", size=16, color=theme.manager.p.ERROR),
            "Supprimer\tCtrl+D",
        )
        delete_action.setEnabled(card is not None)
        delete_action.triggered.connect(self._delete_current_sample)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _on_theme_changed(self, _name: str):
        library_ui.apply_styles(self)
        self._refresh_table()

    def on_samples_changed(self, samples: list):
        """Slot : reçoit la nouvelle liste de samples depuis le store et rafraichit la vue."""
        signature = self._compute_samples_signature(samples)
        if not self.isVisible():
            if signature == self._last_render_signature:
                self._pending_samples_snapshot = None
                logger.info(
                    "[LibraryWidget][Perf] on_samples_changed skip-hidden-unchanged samples=%s pending_skip=%s",
                    len(samples),
                    self._skip_next_full_table_refresh,
                )
                return
            self._pending_samples_snapshot = list(samples)
            logger.info(
                "[LibraryWidget][Perf] on_samples_changed deferred-hidden samples=%s pending_skip=%s",
                len(samples),
                self._skip_next_full_table_refresh,
            )
            return
        if signature == self._last_render_signature:
            self._pending_samples_snapshot = None
            logger.info(
                "[LibraryWidget][Perf] on_samples_changed skip-visible-unchanged samples=%s pending_skip=%s",
                len(samples),
                self._skip_next_full_table_refresh,
            )
            self._skip_next_full_table_refresh = False
            return
        logger.info(
            "[LibraryWidget][Perf] on_samples_changed received samples=%s visible=%s pending_skip=%s",
            len(samples),
            self.isVisible(),
            self._skip_next_full_table_refresh,
        )
        self._pending_samples_snapshot = list(samples)
        self._store_refresh_timer.start()

    def _upsert_local_sample(self, updated_sample) -> tuple[int, bool]:
        sample_id = int(getattr(updated_sample, "id", -1) or -1)
        for index, sample in enumerate(self.samples):
            if int(getattr(sample, "id", -1) or -1) == sample_id:
                self.samples[index] = updated_sample
                return sample_id, False
        self.samples.append(updated_sample)
        self.samples.sort(key=lambda sample: int(getattr(sample, "id", -1) or -1))
        return sample_id, True

    def _queue_size_for_path(self, path: str) -> None:
        normalized = normalize_audio_path(str(path or ""))
        if not normalized:
            return
        if normalized in self._size_cache or normalized in self._size_requested:
            return
        self._size_requested.add(normalized)
        self._size_input_queue.put(normalized)

    def _upsert_filtered_entry_quick(
        self,
        updated_sample,
        *,
        reason: str,
        navigation_dirty: bool = False,
        queue_size: bool = False,
    ) -> None:
        start = perf_counter()
        sample_id, _is_new = self._upsert_local_sample(updated_sample)
        updated_entry = self._entry_from_sample(updated_sample)
        if queue_size:
            self._queue_size_for_path(updated_entry.path)

        in_scope = self._matches_current_scope(updated_sample)
        in_filters = self._matches_active_filters(updated_entry, updated_sample)
        row = self._find_row_for_sample(sample_id)
        filtered_index = next(
            (index for index, entry in enumerate(self.filtered_entries) if int(entry.sample_id or -1) == sample_id),
            None,
        )

        if navigation_dirty:
            self._navigation_dirty = True

        if not self.isVisible():
            # Le modèle local est à jour, mais le tableau caché ne l'est pas.
            # Conserver un snapshot force un rendu complet au prochain showEvent.
            self._pending_samples_snapshot = list(self.samples)
            self._skip_next_full_table_refresh = True
            self._last_render_signature = self._compute_samples_signature(self.samples)
            logger.info(
                "[LibraryWidget][Perf] %s deferred-hidden sample=%s total=%.1fms",
                reason,
                sample_id,
                (perf_counter() - start) * 1000.0,
            )
            return

        if not in_scope or not in_filters:
            self._entries_by_sample_id.pop(sample_id, None)
            if filtered_index is not None:
                self._skip_next_full_table_refresh = True
                self.filtered_entries.pop(filtered_index)
                if row is not None:
                    self.table.blockSignals(True)
                    self.table.removeRow(row)
                    self.table.blockSignals(False)
                    if self.table.rowCount() > 0:
                        target_row = min(row, self.table.rowCount() - 1)
                        self.table.selectRow(target_row)
                        self._sync_detail_with_selection()
                    else:
                        self._selected_sample_id = None
                        self.detail_widget.clear_sample()
                        self.reserveEntrySelected.emit(None)
            self._refresh_count_label()
            self._last_render_signature = self._compute_samples_signature(self.samples)
            self._schedule_navigation_refresh()
            logger.info(
                "[LibraryWidget][Perf] %s removed sample=%s row=%s total=%.1fms",
                reason,
                sample_id,
                row,
                (perf_counter() - start) * 1000.0,
            )
            return

        self._entries_by_sample_id[sample_id] = updated_entry
        sorting_enabled = self.table.isSortingEnabled()
        current_sort_section = self.table.horizontalHeader().sortIndicatorSection()
        current_sort_order = self.table.horizontalHeader().sortIndicatorOrder()
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        if filtered_index is not None and row is not None:
            self.filtered_entries[filtered_index] = updated_entry
            self._apply_row_items_to_table(row, updated_entry)
        else:
            insert_row = self.table.rowCount()
            self.filtered_entries.append(updated_entry)
            self.table.insertRow(insert_row)
            self._apply_row_items_to_table(insert_row, updated_entry)
        self.table.blockSignals(False)
        self.table.setSortingEnabled(sorting_enabled)

        if sorting_enabled and current_sort_section >= 0:
            self.table.sortItems(current_sort_section, current_sort_order)

        selected_row = self._find_row_for_sample(sample_id)
        if self._selected_sample_id == sample_id:
            if selected_row is not None:
                self.table.selectRow(selected_row)
            self._refresh_detail_for_sample(sample_id, updated_entry)
        elif self.table.currentRow() < 0 and selected_row is not None:
            self.table.selectRow(selected_row)
            self._sync_detail_with_selection()

        self._refresh_count_label()
        self._last_render_signature = self._compute_samples_signature(self.samples)
        self._schedule_navigation_refresh()
        logger.info(
            "[LibraryWidget][Perf] %s upserted sample=%s row=%s total=%.1fms",
            reason,
            sample_id,
            selected_row,
            (perf_counter() - start) * 1000.0,
        )

    def _reload_from_store(self):
        """Recharge les samples depuis le cache du store (sans attendre le signal samplesChanged)."""
        self._pending_samples_snapshot = self.library_service.get_cached_samples()
        self._store_refresh_timer.start()

    def _apply_pending_store_refresh(self) -> None:
        total_start = perf_counter()
        samples = (
            list(self._pending_samples_snapshot)
            if self._pending_samples_snapshot is not None
            else self.library_service.get_cached_samples()
        )
        self._pending_samples_snapshot = None
        previous_scope_key = (self.current_scope.kind, self.current_scope.value)
        quick_delete_refresh = self._skip_next_full_table_refresh
        self._skip_next_full_table_refresh = False
        self.samples = samples
        if quick_delete_refresh and (self.current_scope.kind, self.current_scope.value) == previous_scope_key:
            self._refresh_count_label()
            self._schedule_navigation_refresh()
            total_ms = (perf_counter() - total_start) * 1000.0
            logger.info(
                "[LibraryWidget][Perf] apply_pending_store_refresh skip-heavy-delete samples=%s rows=%s total=%.1fms scope=%s/%s",
                len(self.samples),
                self.table.rowCount(),
                total_ms,
                self.current_scope.kind,
                self.current_scope.value,
            )
            return
        step_start = perf_counter()
        self._request_size_scan()
        size_ms = (perf_counter() - step_start) * 1000.0
        step_start = perf_counter()
        self._refresh_navigation()
        nav_ms = (perf_counter() - step_start) * 1000.0
        step_start = perf_counter()
        self._refresh_table()
        table_ms = (perf_counter() - step_start) * 1000.0
        total_ms = (perf_counter() - total_start) * 1000.0
        logger.info(
            "[LibraryWidget][Perf] apply_pending_store_refresh full samples=%s rows=%s size=%.1fms nav=%.1fms table=%.1fms total=%.1fms scope=%s/%s",
            len(self.samples),
            self.table.rowCount(),
            size_ms,
            nav_ms,
            table_ms,
            total_ms,
            self.current_scope.kind,
            self.current_scope.value,
        )

    def _on_sample_added_quick(self, sample_id: int) -> None:
        updated_sample = next(
            (sample for sample in self.sample_store.get_cached() if int(getattr(sample, "id", -1) or -1) == int(sample_id)),
            None,
        )
        if updated_sample is None:
            return
        self._skip_next_full_table_refresh = True
        self._upsert_filtered_entry_quick(
            updated_sample,
            reason="quick_add",
            navigation_dirty=True,
            queue_size=True,
        )

    def _on_sample_duration_changed_quick(self, sample_id: int, _duration: float) -> None:
        updated_sample = next(
            (sample for sample in self.sample_store.get_cached() if int(getattr(sample, "id", -1) or -1) == int(sample_id)),
            None,
        )
        if updated_sample is None:
            return
        self._upsert_filtered_entry_quick(
            updated_sample,
            reason="quick_duration",
            navigation_dirty=False,
            queue_size=False,
        )

    def _on_sample_renamed_quick(self, sample_id: int, old_path: str, new_path: str) -> None:
        start = perf_counter()
        sample_id = int(sample_id)
        old_normalized = normalize_audio_path(str(old_path or ""))
        new_normalized = normalize_audio_path(str(new_path or ""))
        if old_normalized and new_normalized and old_normalized != new_normalized:
            if old_normalized in self._size_cache:
                self._size_cache[new_normalized] = self._size_cache.pop(old_normalized)
            if old_normalized in self._size_requested:
                self._size_requested.discard(old_normalized)
            if new_normalized not in self._size_cache and new_normalized not in self._size_requested:
                self._size_requested.add(new_normalized)
                self._size_input_queue.put(new_normalized)
        updated_sample = next(
            (sample for sample in self.samples if int(getattr(sample, "id", -1)) == sample_id),
            None,
        )
        if updated_sample is None:
            return

        row = self._find_row_for_sample(sample_id)
        filtered_index = next(
            (index for index, entry in enumerate(self.filtered_entries) if int(entry.sample_id or -1) == sample_id),
            None,
        )
        if row is None or filtered_index is None:
            logger.info(
                "[LibraryWidget][Perf] quick_rename fallback-missing sample=%s row=%s filtered=%s total=%.1fms",
                sample_id,
                row,
                filtered_index,
                (perf_counter() - start) * 1000.0,
            )
            return

        updated_entry = self._entry_from_sample(updated_sample)
        self._entries_by_sample_id[sample_id] = updated_entry

        if not self._matches_active_filters(updated_entry, updated_sample):
            self._skip_next_full_table_refresh = True
            self.filtered_entries.pop(filtered_index)
            self.table.blockSignals(True)
            self.table.removeRow(row)
            self.table.blockSignals(False)
            if self.table.rowCount() > 0:
                target_row = min(row, self.table.rowCount() - 1)
                self.table.selectRow(target_row)
                self._sync_detail_with_selection()
            else:
                self._selected_sample_id = None
                self.detail_widget.clear_sample()
                self.reserveEntrySelected.emit(None)
            self._refresh_count_label()
            self._last_render_signature = self._compute_samples_signature(self.samples)
            logger.info(
                "[LibraryWidget][Perf] quick_rename removed sample=%s row=%s total=%.1fms",
                sample_id,
                row,
                (perf_counter() - start) * 1000.0,
            )
            return

        self.filtered_entries[filtered_index] = updated_entry
        sorting_enabled = self.table.isSortingEnabled()
        current_sort_section = self.table.horizontalHeader().sortIndicatorSection()
        current_sort_order = self.table.horizontalHeader().sortIndicatorOrder()

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self._apply_row_items_to_table(row, updated_entry)
        self.table.blockSignals(False)
        self.table.setSortingEnabled(sorting_enabled)

        if sorting_enabled and current_sort_section >= 0:
            self.table.sortItems(current_sort_section, current_sort_order)

        selected_row = self._find_row_for_sample(sample_id)
        if selected_row is not None:
            self.table.selectRow(selected_row)
        self._refresh_detail_for_sample(sample_id, updated_entry)
        self._refresh_count_label()
        self._last_render_signature = self._compute_samples_signature(self.samples)
        logger.info(
            "[LibraryWidget][Perf] quick_rename updated sample=%s row=%s->%s old=%s new=%s total=%.1fms",
            sample_id,
            row,
            selected_row,
            old_path,
            new_path,
            (perf_counter() - start) * 1000.0,
        )

    def _on_sample_moved_quick(self, sample_id: int, target_folder: str) -> None:
        start = perf_counter()
        sample_id = int(sample_id)
        updated_sample = next(
            (sample for sample in self.samples if int(getattr(sample, "id", -1)) == sample_id),
            None,
        )
        if updated_sample is None:
            return

        row = self._find_row_for_sample(sample_id)
        filtered_index = next(
            (index for index, entry in enumerate(self.filtered_entries) if int(entry.sample_id or -1) == sample_id),
            None,
        )
        if row is None or filtered_index is None:
            logger.info(
                "[LibraryWidget][Perf] quick_move fallback-missing sample=%s row=%s filtered=%s target=%s total=%.1fms",
                sample_id,
                row,
                filtered_index,
                target_folder,
                (perf_counter() - start) * 1000.0,
            )
            return

        old_entry = self.filtered_entries[filtered_index]
        old_normalized = normalize_audio_path(str(old_entry.path or ""))
        updated_entry = self._entry_from_sample(updated_sample)
        new_normalized = normalize_audio_path(str(updated_entry.path or ""))
        if old_normalized and new_normalized and old_normalized != new_normalized:
            if old_normalized in self._size_cache:
                self._size_cache[new_normalized] = self._size_cache.pop(old_normalized)
            if old_normalized in self._size_requested:
                self._size_requested.discard(old_normalized)
            if new_normalized not in self._size_cache and new_normalized not in self._size_requested:
                self._size_requested.add(new_normalized)
                self._size_input_queue.put(new_normalized)

        in_scope = self._matches_current_scope(updated_sample)
        in_filters = self._matches_active_filters(updated_entry, updated_sample)
        self._entries_by_sample_id[sample_id] = updated_entry

        if not in_scope or not in_filters:
            self._skip_next_full_table_refresh = True
            self._navigation_dirty = True
            self.filtered_entries.pop(filtered_index)
            self.table.blockSignals(True)
            self.table.removeRow(row)
            self.table.blockSignals(False)
            if self.table.rowCount() > 0:
                target_row = min(row, self.table.rowCount() - 1)
                self.table.selectRow(target_row)
                self._sync_detail_with_selection()
            else:
                self._selected_sample_id = None
                self.detail_widget.clear_sample()
                self.reserveEntrySelected.emit(None)
            self._refresh_count_label()
            self._last_render_signature = self._compute_samples_signature(self.samples)
            logger.info(
                "[LibraryWidget][Perf] quick_move removed sample=%s row=%s target=%s total=%.1fms",
                sample_id,
                row,
                target_folder,
                (perf_counter() - start) * 1000.0,
            )
            return

        self._skip_next_full_table_refresh = True
        self._navigation_dirty = True
        self.filtered_entries[filtered_index] = updated_entry
        sorting_enabled = self.table.isSortingEnabled()
        current_sort_section = self.table.horizontalHeader().sortIndicatorSection()
        current_sort_order = self.table.horizontalHeader().sortIndicatorOrder()

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self._apply_row_items_to_table(row, updated_entry)
        self.table.blockSignals(False)
        self.table.setSortingEnabled(sorting_enabled)

        if sorting_enabled and current_sort_section >= 0:
            self.table.sortItems(current_sort_section, current_sort_order)

        selected_row = self._find_row_for_sample(sample_id)
        if selected_row is not None:
            self.table.selectRow(selected_row)
        self._refresh_detail_for_sample(sample_id, updated_entry)
        self._refresh_count_label()
        self._last_render_signature = self._compute_samples_signature(self.samples)
        logger.info(
            "[LibraryWidget][Perf] quick_move updated sample=%s row=%s->%s target=%s total=%.1fms",
            sample_id,
            row,
            selected_row,
            target_folder,
            (perf_counter() - start) * 1000.0,
        )

    def _on_sample_deleted_quick(self, sample_id: int) -> None:
        start = perf_counter()
        sample_id = int(sample_id)
        self._skip_next_full_table_refresh = True
        removed_entry = self._entries_by_sample_id.get(sample_id)
        if removed_entry is not None:
            normalized = normalize_audio_path(str(removed_entry.path or ""))
            if normalized:
                self._size_cache.pop(normalized, None)
                self._size_requested.discard(normalized)

        self.samples = [sample for sample in self.samples if int(getattr(sample, "id", -1)) != sample_id]
        self.filtered_entries = [entry for entry in self.filtered_entries if int(entry.sample_id or -1) != sample_id]
        self._entries_by_sample_id.pop(sample_id, None)

        if not self.isVisible():
            logger.info(
                "[LibraryWidget][Perf] quick_delete deferred-hidden sample=%s rows=%s total=%.1fms",
                sample_id,
                self.table.rowCount(),
                (perf_counter() - start) * 1000.0,
            )
            return

        row = self._find_row_for_sample(sample_id)
        if row is None:
            self._refresh_count_label()
            logger.info(
                "[LibraryWidget][Perf] quick_delete sample=%s row=missing rows=%s total=%.1fms",
                sample_id,
                self.table.rowCount(),
                (perf_counter() - start) * 1000.0,
            )
            return

        next_row = row
        row_count_before = self.table.rowCount()
        if self._selected_sample_id == sample_id:
            self.detail_widget.clear_sample()
            self._selected_sample_id = None

        self.table.blockSignals(True)
        self.table.removeRow(row)
        self.table.blockSignals(False)

        if row_count_before <= 1 or self.table.rowCount() <= 0:
            self.table.clearSelection()
            self.reserveEntrySelected.emit(None)
            self._refresh_count_label()
            logger.info(
                "[LibraryWidget][Perf] quick_delete sample=%s cleared_last_row total=%.1fms",
                sample_id,
                (perf_counter() - start) * 1000.0,
            )
            return

        next_row = min(next_row, self.table.rowCount() - 1)
        self.table.selectRow(next_row)
        self._sync_detail_with_selection()
        self._refresh_count_label()
        logger.info(
            "[LibraryWidget][Perf] quick_delete sample=%s row=%s->%s rows_now=%s total=%.1fms",
            sample_id,
            row,
            next_row,
            self.table.rowCount(),
            (perf_counter() - start) * 1000.0,
        )

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._refresh_navigation_if_dirty()
        if self._pending_samples_snapshot is None:
            return
        pending_signature = self._compute_samples_signature(self._pending_samples_snapshot)
        if pending_hidden_refresh_requires_render(
            self._pending_samples_snapshot,
            quick_update_unrendered=self._skip_next_full_table_refresh,
            pending_signature=pending_signature,
            rendered_signature=self._last_render_signature,
        ):
            # Une mise à jour rapide reçue pendant que le widget était caché
            # n'a jamais été appliquée au tableau : elle ne peut pas être
            # traitée comme un refresh déjà rendu.
            self._skip_next_full_table_refresh = False
            self._store_refresh_timer.start()
            return
        if pending_signature == self._last_render_signature:
            logger.info(
                "[LibraryWidget][Perf] showEvent skip-pending-unchanged samples=%s",
                len(self._pending_samples_snapshot),
            )
            self._pending_samples_snapshot = None
            return
        self._store_refresh_timer.start()

    def set_reserve_query(self, query: str) -> None:
        """Fixe le texte de recherche quand la Reserve pilote ce widget en mode integre."""
        query = (query or "").strip()
        if query == self._reserve_query_text:
            return
        self._reserve_query_text = query
        if self.embedded_in_reserve:
            self._refresh_table()

    def set_reserve_status_filter(self, status_filter: str) -> None:
        """Fixe le filtre de statut quand la Reserve pilote ce widget en mode integre."""
        status_filter = status_filter or "all"
        if status_filter == self._reserve_status_filter:
            return
        self._reserve_status_filter = status_filter
        if self.embedded_in_reserve:
            self._refresh_table()

    def set_reserve_scale_filter(self, scale: str) -> None:
        """Applique la gamme partagee sans changer le moteur musical existant."""
        self._set_scale_filter_value(scale or self.SCALE_FILTER_ALL)

    def _request_scale_filter(self, scale: str) -> None:
        if self.embedded_in_reserve:
            self.reserveScaleFilterRequested.emit(scale)
        else:
            self._set_scale_filter_value(scale)

    def set_reserve_scope(self, kind: str, value=None) -> None:
        scope = LibraryScope(kind or "all", value)
        if (scope.kind, scope.value) == (self.current_scope.kind, self.current_scope.value):
            return
        self.current_scope = scope
        target = self._find_matching_tree_item(
            self.tree.invisibleRootItem(), (scope.kind, scope.value)
        )
        if target is not None:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(target)
            self.tree.blockSignals(False)
        self._refresh_table()

    def set_compatible_scales_filter(self, sample_id: int | None) -> None:
        """Active ou efface le filtre de gammes compatibles."""
        if sample_id is None:
            if not self._compat_filter_scales:
                return
            self._compat_filter_scales = set()
        else:
            ref = next((s for s in self.samples if s.id == sample_id), None)
            if ref is None:
                return
            raw = getattr(ref, "compatible_scales", None) or ""
            try:
                scales = set(json.loads(raw)) if raw else set()
            except (ValueError, TypeError):
                scales = set()
            if self._compat_filter_scales == scales:
                return
            self._compat_filter_scales = scales
        self._refresh_table()

    def _on_sample_scale_analyzed(self, sample_id: int) -> None:
        """Actualise les donnees du sample analyse sans rebuild complet."""
        updated = next(
            (s for s in self.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if updated is None:
            return
        self._upsert_filtered_entry_quick(
            updated,
            reason="quick_scale",
            navigation_dirty=False,
            queue_size=False,
        )

    def current_reserve_entry(self) -> ReserveEntry | None:
        if self._selected_sample_id is None:
            return None
        return self._entries_by_sample_id.get(int(self._selected_sample_id))

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        """Selectionne la ligne correspondante dans le tableau et ouvre la waveform.

        Retourne True si la ligne a ete trouvee et la waveform ouverte.
        """
        if entry is None or entry.source_kind != "indexed" or entry.sample_id is None:
            return False
        row = self._find_row_for_sample(int(entry.sample_id))
        if row is None:
            return False
        self.table.selectRow(row)
        self.detail_widget.toggle_waveform()
        return True

    def _refresh_navigation(self):
        """Reconstruit l'arbre de navigation (racines/dossiers) depuis le LibraryService.

        Tente de conserver la selection courante (meme scope) apres le rebuild.
        """
        current_scope = (self.current_scope.kind, self.current_scope.value)
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes = self.library_service.build_navigation(self.samples)
        selected_item = None
        for node in nodes:
            item = self._build_tree_item(node)
            self.tree.addTopLevelItem(item)
            self._expand_top_level_if_needed(item)
            if (
                item.data(0, self.TREE_SCOPE_KIND_ROLE),
                item.data(0, self.TREE_SCOPE_VALUE_ROLE),
            ) == current_scope:
                selected_item = item
            if selected_item is None:
                selected_item = self._find_matching_tree_item(item, current_scope)

        if selected_item is None and self.tree.topLevelItemCount() > 0:
            selected_item = self.tree.topLevelItem(0)

        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
            self.current_scope = LibraryScope(
                str(selected_item.data(0, self.TREE_SCOPE_KIND_ROLE)),
                selected_item.data(0, self.TREE_SCOPE_VALUE_ROLE),
            )
        self.tree.blockSignals(False)

    def _build_tree_item(self, node: LibraryNavNode) -> QTreeWidgetItem:
        """Cree recursivement un item d'arbre a partir d'un LibraryNavNode."""
        missing_suffix = f" - {node.missing_count} manquants" if node.missing_count else ""
        item = QTreeWidgetItem([f"{node.label} ({node.sample_count}){missing_suffix}"])
        item.setData(0, self.TREE_SCOPE_KIND_ROLE, node.scope.kind)
        item.setData(0, self.TREE_SCOPE_VALUE_ROLE, node.scope.value)
        for child in node.children:
            item.addChild(self._build_tree_item(child))
        return item

    def _expand_top_level_if_needed(self, item: QTreeWidgetItem):
        if item.parent() is None:
            item.setExpanded(True)

    def _find_matching_tree_item(self, root: QTreeWidgetItem, scope_key: tuple[str, str | None]):
        if (
            root.data(0, self.TREE_SCOPE_KIND_ROLE),
            root.data(0, self.TREE_SCOPE_VALUE_ROLE),
        ) == scope_key:
            return root
        for index in range(root.childCount()):
            found = self._find_matching_tree_item(root.child(index), scope_key)
            if found is not None:
                return found
        return None

    def _on_tree_selection_changed(self):
        item = self.tree.currentItem()
        if item is None:
            return
        self.current_scope = LibraryScope(
            str(item.data(0, self.TREE_SCOPE_KIND_ROLE)),
            item.data(0, self.TREE_SCOPE_VALUE_ROLE),
        )
        self.reserveScopeChanged.emit(self.current_scope.kind, self.current_scope.value)
        self._refresh_table()

    def _refresh_table(self):
        """Filtre les samples selon le scope, la recherche et le statut, puis peuple le tableau.

        Les samples sont d'abord filtres par scope (racine/dossier/all) via le
        LibraryService, puis par texte de recherche, filtre de statut, et filtre
        de gammes compatibles. Les cellules sont colorees en fonction du statut.
        La selection precedente est restauree si le sample est toujours visible.
        """
        self._entries_by_sample_id.clear()
        query = self._active_query_text()
        status_filter = self._active_status_filter_value()

        scoped_samples = self.library_service.filter_samples(
            self.samples,
            scope=self.current_scope,
            search_text="",
            status_filter=LibraryService.STATUS_ALL,
        )
        candidate_entries: list[ReserveEntry] = []
        for sample in scoped_samples:
            entry = self._entry_from_sample(sample)
            if not reserve_entry_matches_query(entry, query):
                continue
            if not reserve_entry_matches_status(entry, status_filter):
                continue
            if self._compat_filter_scales:
                raw = getattr(sample, "compatible_scales", None) or ""
                try:
                    samp_scales = set(json.loads(raw)) if raw else set()
                except (ValueError, TypeError):
                    samp_scales = set()
                if not (samp_scales & self._compat_filter_scales):
                    continue
            candidate_entries.append(entry)
            if entry.sample_id is not None:
                self._entries_by_sample_id[int(entry.sample_id)] = entry

        self._refresh_scale_filter_options(candidate_entries)
        self.filtered_entries = [entry for entry in candidate_entries if self._matches_scale_filter(entry)]

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_entries))

        selected_sample_id = self._selected_sample_id
        for row, entry in enumerate(self.filtered_entries):
            self._apply_row_items_to_table(row, entry)

        self._refresh_size_display()

        selected_row = self._find_row_for_sample(selected_sample_id)
        if selected_row is None and self._pending_selected_row is not None and self.filtered_entries:
            selected_row = max(0, min(len(self.filtered_entries) - 1, self._pending_selected_row))
            pending_entry = self.filtered_entries[selected_row]
            self._selected_sample_id = pending_entry.sample_id
        if selected_row is None and self.filtered_entries:
            first_entry = self.filtered_entries[0]
            selected_row = self._find_row_for_sample(first_entry.sample_id)
            self._selected_sample_id = first_entry.sample_id
        self._pending_selected_row = None

        if selected_row is not None:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        if selected_row is not None:
            self._sync_detail_with_selection()
        self._last_render_signature = self._compute_samples_signature(self.samples)

    def _entry_from_sample(self, sample) -> ReserveEntry:
        path = getattr(sample, "path", "") or ""
        return reserve_entry_from_sample(
            sample,
            source_kind="indexed",
            root_path=self.library_service.get_root_path(sample),
            folder_path=self.library_service.get_parent_folder_path(sample),
        )

    def _format_duration(self, entry: ReserveEntry) -> str:
        return format_reserve_duration(entry.duration, compact=True)

    def _format_rms(self, entry: ReserveEntry) -> str:
        return format_reserve_rms(entry.rms_level)

    def _on_table_selection_changed(self):
        self._sync_detail_with_selection()

    def _sync_detail_with_selection(self):
        """Lit la ligne selectionnee et met a jour le panneau de detail et le signal."""
        row = self.table.currentRow()
        if row < 0:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        id_item = self.table.item(row, 0)
        if id_item is None:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        sample_id = int(id_item.data(self.TABLE_SAMPLE_ID_ROLE) or -1)
        sample = next((item for item in self.samples if int(item.id) == sample_id), None)
        entry = self._entries_by_sample_id.get(sample_id)
        if sample is None or entry is None:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        self._selected_sample_id = int(sample.id)
        self.detail_widget.set_sample(sample, entry, self.library_service)
        self.reserveEntrySelected.emit(entry)

    def _find_row_for_sample(self, sample_id: int | None) -> int | None:
        """Retourne l'indice de ligne du sample dans le tableau, ou None s'il est absent."""
        if sample_id is None:
            return None
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if int(item.data(self.TABLE_SAMPLE_ID_ROLE) or -1) == int(sample_id):
                return row
        return None

    @staticmethod
    def _compute_samples_signature(samples: list) -> tuple:
        return tuple(
            (
                int(getattr(sample, "id", -1) or -1),
                str(getattr(sample, "path", "") or ""),
                str(getattr(sample, "name", "") or ""),
                str(getattr(sample, "created_at", "") or ""),
                float(getattr(sample, "duration", 0.0) or 0.0),
                bool(getattr(sample, "missing", False)),
                getattr(sample, "dominant_note", None),
                getattr(sample, "detected_scale_label", None),
                getattr(sample, "detected_scale_kind", None),
                getattr(sample, "compatible_scales", None),
            )
            for sample in samples
        )

    def eventFilter(self, watched, event):
        """Detecte le debut d'un drag depuis le viewport du tableau.

        Quand la souris se deplace au-dela du seuil startDragDistance avec le
        bouton gauche enfonce, lance _start_drag_from_selection().
        """
        if watched is self.table.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.position().toPoint()
            elif (
                event.type() == QEvent.Type.MouseMove
                and event.buttons() & Qt.MouseButton.LeftButton
                and self._drag_start_pos is not None
            ):
                if (
                    event.position().toPoint() - self._drag_start_pos
                ).manhattanLength() >= QApplication.startDragDistance():
                    self._drag_start_pos = None
                    self._start_drag_from_selection()
                    return True
        return super().eventFilter(watched, event)

    def _start_drag_from_selection(self) -> None:
        """Lance un QDrag depuis le sample selectionne.

        Inclut deux types de donnees MIME :
        - URL locale du fichier (pour l'import dans un widget standard).
        - 'application/x-sample-card' avec l'ID du sample (pour l'import dans
          les widgets internes qui savent resoudre l'ID en chemin).
        """
        entry = self.current_reserve_entry()
        if entry is None or not getattr(entry, "path", ""):
            return

        drag = QDrag(self.table)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(entry.path)])
        if entry.sample_id is not None:
            mime.setData(
                "application/x-sample-card",
                pickle.dumps({"sample_id": int(entry.sample_id)}),
            )
        descriptor = DragPayload(
            kind=DragKind.AUDIO_FILE,
            items=(DragItem(
                item_id=str(entry.sample_id or ""),
                path=str(entry.path),
                display_name=os.path.basename(str(entry.path)) or "Sample",
            ),),
            source_id=f"library:{entry.sample_id or entry.path}",
            source_module="reserve",
            status=MaterialStatus.SOURCE,
            provenance=DragProvenance(str(entry.path), MaterialOperation.IMPORT),
        )
        attach_payload(mime, descriptor)
        drag.setMimeData(mime)
        drag.setPixmap(drag_preview_pixmap(descriptor))
        with drag_session(descriptor):
            drag.exec(Qt.DropAction.CopyAction)
