# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal de la liste des samples (toolbar, scroll, pagination).
# - Fichier "facade" : delegue toute la logique aux sous-modules.
#
# SOUS-MODULES
# - SampleListUIBuilder      : creation UI (toolbar / scroll / pagination)
# - SampleListPagination     : logique de pagination + navigation
# - SampleListSelection      : selection + actions bulk
# - SampleListDragDrop       : import par glisser-deposer (.wav)
# - SampleListImport         : import manuel via QFileDialog
# - SampleListNormalize      : normalisation + workers
# - SampleListServiceActions : delete/rename/move via SampleStore
# - SampleListCards          : cycle de vie des SampleCard (creation/animation)
#
# SIGNAUX EMIS
# - reserveEntrySelected(ReserveEntry)  : carte selectionnee -> panneau detail
# - compatFilterChanged(int)            : filtre gamme compatible (0=efface)
# - openInFoldersRequested(str)         : ouvrir le dossier dans l'onglet Dossiers
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py   : SampleCard utilisees dans la liste
# - frontend/reserve/reserve_pane.py            : ReservePane (parent en mode reserve)
# -----------------------------------------------------------------------------

import json
import logging
import os
from time import perf_counter

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMenu, QSizePolicy, QSlider, QWidget
from PySide6.QtCore import Qt, Signal, Slot, QSettings
from PySide6.QtGui import QKeySequence, QShortcut

from backend.models.AppContext import AppContext
from backend.services.sample_service import SampleService
from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    reserve_entry_from_sample,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
)
from frontend.sample_gui.sample.sample_list_ui import SampleListUIBuilder
from frontend.styles import theme
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination
from frontend.sample_gui.sample.sample_list_selection import SampleListSelection
from frontend.sample_gui.sample.sample_list_dragdrop import SampleListDragDrop
from frontend.sample_gui.sample.sample_list_import import SampleListImport
from frontend.sample_gui.sample.sample_list_normalize import SampleListNormalize
from frontend.sample_gui.sample.sample_list_service import SampleListServiceActions
from frontend.sample_gui.sample.sample_list_cards import SampleListCards
from frontend.sample_gui.sample.sample_card import SampleCard

logger = logging.getLogger("sample_list")


class SampleListWidget(QWidget):
    """Liste scrollable de SampleCard avec toolbar, pagination et actions bulk.

    Utilise comme onglet "Indexe" dans ReservePane ou en mode standalone.
    La logique est repartie dans 8 sous-modules (voir header du fichier).
    """

    reserveEntrySelected = Signal(object)
    compatFilterChanged = Signal(int)   # emet l'ID de reference (0 = filtre efface)
    openInFoldersRequested = Signal(str)  # emet le dossier a ouvrir dans l'onglet Dossiers

    def __init__(
        self,
        app_context: AppContext,
        parent=None,
        reserve_actions: ReserveActions | None = None,
    ):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # stocke le contexte et le service metier
        self.app_context  = app_context
        self.sample_store: SampleService = app_context.sample_store
        self.settings = self.app_context.settings
        self.reserve_actions = reserve_actions
        self.samples = []  # liste des samples a afficher
        self.filtered_samples = []
        self.selected_ids  = set()        # ensemble des IDs coches
        self._reserve_query_text = ""
        self._reserve_status_filter = "all"
        self._compat_filter_sample_id: int | None = None  # ID reference pour filtre gamme
        self._compat_filter_scales: set[str] = set()       # gammes compatibles du sample ref
        self._current_sample_id: int | None = None
        self._pending_focus_sample_id: int | None = None
        self._pending_hidden_samples_refresh: list | None = None
        self._last_render_signature = None
        self._qs = QSettings("SampleRod", "Main")
        self.samples_per_page = self.settings.getSamplesPerPage()
        self.current_page = 1

        # 1) abonnements aux signaux du service
        self.sample_store.samplesChanged.   connect(self.onSamplesChanged)
        self.sample_store.sampleAdded.      connect(self.onSampleAdded)
        self.sample_store.sampleDeleted.    connect(self.onSampleDeleted)
        self.sample_store.sampleRenamed.    connect(self.onSampleRenamed)
        self.sample_store.sampleMoved.      connect(self.onSampleMoved)
        self.sample_store.sampleDurationChanged.connect(self.onSampleDurationChanged)
        # -> Abonnement aux nouveaux signaux de normalisation
        self.sample_store.sampleStartedNormalization.connect(self.onStartedNormalization)
        self.sample_store.sampleFinishedNormalization.connect(self.onFinishedNormalization)
        self.sample_store.sampleNormalizationFailed.connect(self.onNormalizationFailed)
        self.sample_store.sampleRemovedFromHistory.connect(self.onSampleRemovedFromHistory)
        self.sample_store.sampleConcatCandidateChanged.connect(
            self.onSampleConcatCandidateChanged
        )
        self.sample_store.sampleNormalizationLockChanged.connect(
            self.onSampleNormalizationLockChanged
        )
        self.sample_store.sampleScaleAnalyzed.connect(self.onSampleScaleAnalyzed)
        # 2) stockage des cartes existantes
        self._card_widgets = {}
        self.pagination = SampleListPagination(self)
        self.selection = SampleListSelection(self)
        self.dragdrop = SampleListDragDrop(self)
        self.cards = SampleListCards(self)
        self.importer = SampleListImport(self)
        self.normalizer = SampleListNormalize(self)
        self.service_actions = SampleListServiceActions(self)

        # mise a jour en cas de changement de parametres
        self.settings.samplesPerPageChanged.connect(self.onSamplesPerPageChanged)

        # 3) creation de l'UI
        self.init_ui()

        # 4) initialisation de la liste avec le cache actuel
        self.onSamplesChanged(self.sample_store.get_cached())

    def init_ui(self):
        """Construit l'UI (toolbar, scroll, pagination)."""
        self.ui_builder = SampleListUIBuilder(self)
        self.ui_builder.build()
        self._build_shortcuts()
        theme.manager.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name: str):
        SampleListUIBuilder.restyle(self)

    def _build_shortcuts(self) -> None:
        self._history_shortcuts = []
        bindings = [
            ("Up", lambda: self._focus_relative(-1)),
            ("Down", lambda: self._focus_relative(1)),
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
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self._history_shortcuts.append(shortcut)

    def _should_handle_shortcuts(self) -> bool:
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return True
        if focus_widget is self:
            return True
        if not self.isAncestorOf(focus_widget):
            return False
        return not isinstance(focus_widget, (QLineEdit, QComboBox, QSlider, QMenu))

    def _visible_cards_in_order(self) -> list[SampleCard]:
        cards: list[SampleCard] = []
        for index in range(self.content_layout.count()):
            widget = self.content_layout.itemAt(index).widget()
            if isinstance(widget, SampleCard) and widget.isVisible():
                cards.append(widget)
        return cards

    def _current_card(self) -> SampleCard | None:
        if self._current_sample_id is not None:
            card = self._card_widgets.get(int(self._current_sample_id))
            if isinstance(card, SampleCard):
                return card
        focus_widget = QApplication.focusWidget()
        while focus_widget is not None:
            if isinstance(focus_widget, SampleCard):
                return focus_widget
            focus_widget = focus_widget.parentWidget()
        cards = self._visible_cards_in_order()
        return cards[0] if cards else None

    def _focus_card(self, card: SampleCard | None) -> bool:
        if card is None:
            return False
        self.set_current_reserve_sample(int(card.sample.id))
        card.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.scroll_area.ensureWidgetVisible(card, 0, 24)
        return True

    def _focus_relative(self, delta: int) -> None:
        if not self._should_handle_shortcuts():
            return
        cards = self._visible_cards_in_order()
        if not cards:
            return
        current = self._current_card()
        if current not in cards:
            self._focus_card(cards[0] if delta >= 0 else cards[-1])
            return
        index = cards.index(current)
        target = cards[max(0, min(len(cards) - 1, index + delta))]
        self._focus_card(target)

    def _toggle_current_preview(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        card.togglePlay()

    def _restart_current_preview(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        try:
            self.app_context.audio_player.clear_audio()
        except Exception:
            pass
        is_playing = self.app_context.audio_player.seek_position(
            card.sample.id,
            card.sample.path,
            card.sample.duration,
            0,
        )
        card.playback._apply_state(is_playing)
        if is_playing:
            card.playback.update_slider()

    def _seek_current_preview(self, delta_ms: int) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        duration_ms = max(
            0,
            int(float(getattr(card.sample, "duration", 0.0) or 0.0) * 1000),
        )
        if duration_ms <= 0:
            return
        player = self.app_context.audio_player
        current_position = 0
        if (
            int(getattr(player, "current_sample_id", -1)) == int(card.sample.id)
            and os.path.normpath(getattr(player, "current_sample_path", "") or "")
            == os.path.normpath(card.sample.path or "")
        ):
            current_position = max(0, int(player.get_position()))
        target = max(0, min(duration_ms, current_position + int(delta_ms)))
        is_playing = player.seek_position(
            card.sample.id,
            card.sample.path,
            card.sample.duration,
            target,
        )
        card.playback._apply_state(is_playing)
        card.playback.update_slider()

    def _open_current_waveform(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        card.toggleWaveform()

    def _rename_current_sample(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        card.startRename()

    def _delete_current_sample(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        card.confirmDelete()

    def _remove_current_from_history(self) -> None:
        if not self._should_handle_shortcuts():
            return
        card = self._current_card()
        if card is None:
            return
        self._focus_card(card)
        card.onArchiveClicked()

    # ---- Service slots (cache / cards)
    @Slot(list)
    def onSamplesChanged(self, samples: list):
        start = perf_counter()
        signature = self._compute_samples_signature(samples)
        if not self.isVisible():
            self.samples = list(samples)
            if signature == self._last_render_signature:
                self._pending_hidden_samples_refresh = None
                logger.info(
                    "[SampleList][Perf] onSamplesChanged skip-hidden-unchanged samples=%s visible=%s total=%.1fms",
                    len(samples),
                    self.isVisible(),
                    (perf_counter() - start) * 1000.0,
                )
                return
            self._pending_hidden_samples_refresh = list(samples)
            logger.info(
                "[SampleList][Perf] onSamplesChanged deferred-hidden samples=%s visible=%s total=%.1fms",
                len(samples),
                self.isVisible(),
                (perf_counter() - start) * 1000.0,
            )
            return
        self._pending_hidden_samples_refresh = None
        self.cards.on_samples_changed(samples)
        logger.info(
            "[SampleList][Perf] onSamplesChanged samples=%s filtered=%s cards=%s visible=%s total=%.1fms",
            len(samples),
            len(self.filtered_samples),
            len(self._card_widgets),
            self.isVisible(),
            (perf_counter() - start) * 1000.0,
        )

    def set_reserve_query(self, query: str) -> None:
        query = (query or "").strip()
        if query == self._reserve_query_text:
            return
        self._reserve_query_text = query
        self.setCurrentPage(1)

    def set_reserve_status_filter(self, status_filter: str) -> None:
        status_filter = status_filter or "all"
        if status_filter == self._reserve_status_filter:
            return
        self._reserve_status_filter = status_filter
        self.setCurrentPage(1)

    def current_reserve_entry(self) -> ReserveEntry | None:
        if self._current_sample_id is None:
            return None
        sample = next((item for item in self.samples if int(item.id) == int(self._current_sample_id)), None)
        if sample is None:
            return None
        return self._entry_from_sample(sample)

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        if entry is None or entry.sample_id is None:
            return False
        filtered = self.get_filtered_samples()
        for index, sample in enumerate(filtered):
            if int(sample.id) != int(entry.sample_id):
                continue
            target_page = (index // self.samples_per_page) + 1
            if target_page != self.current_page:
                self.setCurrentPage(target_page)
            card = self._card_widgets.get(int(entry.sample_id))
            if card is None:
                return False
            card.setFocus()
            if not card.showWaveform:
                card.toggleWaveform()
            return True
        return False

    @Slot(int)
    def onSampleAdded(self, sample_id: int):
        self.cards.on_sample_added(sample_id)

    # ---- Service actions (delete / rename / move)
    @Slot(int)
    def delete_sample(self, sample_id: int):
        self.service_actions.delete_sample(sample_id)

    @Slot(int, str)
    def rename_sample(self, sample_id: int, new_name: str):
        self.service_actions.rename_sample(sample_id, new_name)

    @Slot(int, str)
    def move_sample(self, sample_id: int, target_folder: str):
        self.service_actions.move_sample(sample_id, target_folder)

    # ---- Normalisation
    @Slot(int)
    def onStartedNormalization(self, sample_id: int):
        self.normalizer.on_started(sample_id)

    @Slot(int)
    def onFinishedNormalization(self, sample_id: int):
        self.normalizer.on_finished(sample_id)

    @Slot(int)
    def onNormalizeClicked(self, sample_id: int):
        self.normalizer.on_clicked(sample_id)

    @Slot(int, str)
    def onNormalizationFailed(self, sample_id: int, message: str):
        self.normalizer.on_failed(sample_id, message)

    # ---- Selection / bulk
    @Slot(int, bool)
    def onSelectionChanged(self, sample_id: int, checked: bool):
        self.selection.on_selection_changed(sample_id, checked)

    # ---- Import manuel
    @Slot()
    def onAddFiles(self):
        self.importer.add_files()

    # ---- Cards (retours service)
    @Slot(int)
    def onSampleRemovedFromHistory(self, sample_id: int):
        self.cards.on_sample_removed_from_history(sample_id)

    @Slot()
    def bulkRemoveFromHistory(self):
        self.selection.bulk_remove_from_history()

    def refreshList(self):
        self.cards.refresh_list()

    def get_filtered_samples(self) -> list:
        ordered_samples = sorted(self.samples, key=lambda s: s.id, reverse=True)
        result = []
        for sample in ordered_samples:
            entry = self._entry_from_sample(sample)
            if not reserve_entry_matches_query(entry, self._reserve_query_text):
                continue
            if not reserve_entry_matches_status(entry, self._reserve_status_filter):
                continue
            if self._compat_filter_scales:
                # Garde uniquement les samples dont les gammes compatibles se recoupent
                raw = getattr(sample, "compatible_scales", None) or ""
                try:
                    samp_scales = set(json.loads(raw)) if raw else set()
                except (ValueError, TypeError):
                    samp_scales = set()
                if not (samp_scales & self._compat_filter_scales):
                    continue
            result.append(sample)
        return result

    def set_compatible_scales_filter(self, sample_id: int | None) -> None:
        """Active ou efface le filtre de gammes compatibles."""
        if sample_id is None:
            if self._compat_filter_sample_id is None and not self._compat_filter_scales:
                return
            self._compat_filter_sample_id = None
            self._compat_filter_scales = set()
            self.compatFilterChanged.emit(0)
            self.setCurrentPage(1)
            return
        ref = next((s for s in self.samples if s.id == sample_id), None)
        if ref is None:
            return
        raw = getattr(ref, "compatible_scales", None) or ""
        try:
            scales = set(json.loads(raw)) if raw else set()
        except (ValueError, TypeError):
            scales = set()
        if not scales:
            return
        if self._compat_filter_sample_id == sample_id and self._compat_filter_scales == scales:
            return
        self._compat_filter_sample_id = sample_id
        self._compat_filter_scales = scales
        self.compatFilterChanged.emit(sample_id)
        self.setCurrentPage(1)

    @Slot(int)
    def onFindCompatiblesRequested(self, sample_id: int) -> None:
        """Slot appele quand on clique le badge de gamme d'une carte."""
        self.set_compatible_scales_filter(sample_id)

    @Slot(int)
    def onSampleScaleAnalyzed(self, sample_id: int) -> None:
        """Slot appele apres analyse de gamme d'un sample."""
        self.cards.on_sample_scale_analyzed(sample_id)

    @Slot(str)
    def onOpenInFoldersRequested(self, folder: str) -> None:
        """Remonte la demande d'ouverture du dossier au ReservePane."""
        self.openInFoldersRequested.emit(folder)

    def set_current_reserve_sample(self, sample_id: int | None) -> None:
        sample_id = int(sample_id) if sample_id is not None else None
        if sample_id == self._current_sample_id:
            return
        self._current_sample_id = sample_id
        self.reserveEntrySelected.emit(self.current_reserve_entry())

    def _entry_from_sample(self, sample) -> ReserveEntry:
        path = getattr(sample, "path", "") or ""
        return reserve_entry_from_sample(
            sample,
            source_kind="history",
            root_path=self._resolve_library_root(path),
            folder_path=os.path.dirname(path),
        )

    def _resolve_library_root(self, path: str) -> str | None:
        normalized = os.path.normpath(os.path.abspath(path)) if path else ""
        for library in sorted(self.settings.libraries, key=lambda lib: lib.position):
            root = os.path.normpath(os.path.abspath(getattr(library, "path", "") or ""))
            if not root:
                continue
            try:
                if os.path.commonpath([normalized, root]) == root:
                    return root
            except ValueError:
                continue
        return None

    @Slot(int)
    def onSampleDeleted(self, sample_id: int):
        start = perf_counter()
        self.cards.on_sample_deleted(sample_id)
        logger.info(
            "[SampleList][Perf] onSampleDeleted sample=%s cards=%s total=%.1fms",
            sample_id,
            len(self._card_widgets),
            (perf_counter() - start) * 1000.0,
        )

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._pending_hidden_samples_refresh is None:
            return
        pending = list(self._pending_hidden_samples_refresh)
        self._pending_hidden_samples_refresh = None
        if self._compute_samples_signature(pending) == self._last_render_signature:
            logger.info(
                "[SampleList][Perf] showEvent skip-pending-unchanged samples=%s",
                len(pending),
            )
            return
        self.cards.on_samples_changed(pending)

    @staticmethod
    def _compute_samples_signature(samples: list) -> tuple:
        return tuple(
            (
                int(getattr(sample, "id", -1) or -1),
                str(getattr(sample, "path", "") or ""),
                str(getattr(sample, "name", "") or ""),
                float(getattr(sample, "duration", 0.0) or 0.0),
                bool(getattr(sample, "missing", False)),
                getattr(sample, "dominant_note", None),
                getattr(sample, "detected_scale_label", None),
                getattr(sample, "detected_scale_kind", None),
                getattr(sample, "compatible_scales", None),
            )
            for sample in samples
        )

    @Slot(int, str, str)
    def onSampleRenamed(self, sample_id: int, old_path: str, new_path: str):
        self.cards.on_sample_renamed(sample_id, old_path, new_path)

    @Slot(int, str)
    def onSampleMoved(self, sample_id: int, target_folder: str):
        self.cards.on_sample_moved(sample_id, target_folder)

    @Slot(int, float)
    def onSampleDurationChanged(self, sample_id: int, new_duration: float):
        self.cards.on_sample_duration_changed(sample_id, new_duration)

    @Slot(int, bool, object)
    def onSampleConcatCandidateChanged(self, sample_id: int, enabled: bool, prev_id):
        self.cards.on_sample_concat_candidate_changed(sample_id, enabled, prev_id)

    @Slot(int, bool)
    def onSampleNormalizationLockChanged(self, sample_id: int, locked: bool):
        self.cards.on_sample_normalization_lock_changed(sample_id, locked)

    @Slot(int)
    def concat_with_previous(self, sample_id: int):
        self.service_actions.concat_with_previous(sample_id)

    @Slot(int)
    def dismiss_concat(self, sample_id: int):
        self.service_actions.dismiss_concat(sample_id)

    @Slot(int, bool, object)
    def onConcatPreviewHoverChanged(self, sample_id: int, active: bool, prev_id):
        self.cards.on_concat_preview_hover_changed(sample_id, active, prev_id)

    def bulkDelete(self):
        self.selection.bulk_delete()

    def bulkMove(self):
        self.selection.bulk_move()

    def bulkNormalize(self):
        self.selection.bulk_normalize()

    def close_waveforms_for_path(self, path):
        self.cards.close_waveforms_for_path(path)

    def updateSelectActions(self):
        self.selection.update_select_actions()

    @Slot()
    def onSelectAll(self):
        self.selection.select_all()

    @Slot()
    def onDeselectAll(self):
        self.selection.deselect_all()

    # ---- Drag & drop
    def dragEnterEvent(self, event):
        self.dragdrop.drag_enter(event)

    def dragMoveEvent(self, event):
        self.dragdrop.drag_move(event)

    def dropEvent(self, event):
        self.dragdrop.drop(event)

    # ---- Pagination
    def updatePaginationLabel(self, start_idx: int, end_idx: int, total_samples: int):
        """Met a jour le label de pagination."""
        self.pagination.update_label(start_idx, end_idx, total_samples)

    @Slot(int)
    def onSamplesPerPageChanged(self, count: int):
        """Slot appele lorsque le parametre de pagination change."""
        self.pagination.on_samples_per_page_changed(count)

    def setCurrentPage(self, page: int):
        """Change la page actuelle et rafraichit la liste."""
        self.pagination.set_current_page(page)

    def change_page(self, page: int):
        """Gere le changement de page et arrete la lecture si necessaire."""
        self.pagination.change_page(page)

    def _prev_page(self):
        self.pagination.prev_page()

    def _next_page(self):
        self.pagination.next_page()
