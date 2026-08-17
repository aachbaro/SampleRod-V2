# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le cycle de vie des SampleCard (creation, suppression, refresh).
# - Centralise la reconstruction de la liste (pagination + layout).
# - Met a jour les cartes suite aux evenements du SampleStore (signaux).
#
# FONCTIONS (sommaire)
# - SampleListCards                     : controleur du cycle de vie
# - on_samples_changed(samples)         : recharge toute la liste (+ defer si anim)
# - on_sample_added(sample_id)          : insere en tete avec animation slide-in
# - on_sample_removed_from_history(id)  : anime la sortie + supprime la carte
# - on_sample_deleted(id)               : meme flow que removed_from_history
# - on_sample_renamed(id, old, new)     : met a jour label + chemin
# - on_sample_moved(id, folder)         : met a jour chemin + combobox
# - on_sample_duration_changed(id, s)   : met a jour la duree affichee
# - refresh_list()                      : reconstruit les cartes visibles selon la page
# - _build_card(sample)                 : cree et cable une SampleCard
# - _animate_card_in(card)              : slide-in (opacity + height, 250 ms)
# - _animate_remove_card(id)            : slide-out puis suppression physique
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py   : SampleCard creees ici
# - frontend/sample_gui/sample/sample_list.py   : SampleListWidget (widget parent)
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from time import perf_counter

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QLabel
from frontend.reserve import format_reserve_clock_duration

from frontend.sample_gui.sample.sample_card import SampleCard

logger = logging.getLogger("sample_list_cards")


class SampleListCards:
    """Controleur du cycle de vie des SampleCard dans une SampleListWidget."""

    def __init__(self, widget):
        self.widget = widget
        self._preview_pair_ids: set[int] = set()
        self._entry_animations: dict[int, QPropertyAnimation] = {}
        self._exit_animations: dict[int, QPropertyAnimation] = {}
        self._pending_refresh_after_exit = False
        self._incremental_refresh_running = False
        self._pending_refresh_after_incremental = False
        self._incremental_generation = 0

    # ---- Service slots
    def on_samples_changed(self, samples: list):
        """Slot du SampleStore: remplace toute la liste et reconstruit les cartes.

        Si une animation de sortie est en cours (_exit_animations non vide),
        on differe le refresh pour ne pas interrompre l'animation.
        """
        self.widget.samples = samples
        if self._incremental_refresh_running:
            # Analyses and normalisation may update the store while the first
            # page is being materialised.  Finish the current page, then apply
            # only the latest snapshot instead of restarting the build for
            # every signal.
            self._pending_refresh_after_incremental = True
            return
        # Si une animation de suppression est en cours, on differe le refresh
        # pour eviter de retirer la card instantanement.
        if self._exit_animations:
            self._pending_refresh_after_exit = True
            return
        self.refresh_list()
        self.widget.updateSelectActions()

    def on_sample_added(self, sample_id: int):
        """Slot: cree et insere une nouvelle carte en tete de liste avec animation."""
        new_sample = next(
            (s for s in self.widget.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if new_sample is None:
            return

        self.widget.samples.insert(0, new_sample)
        card = self._build_card(new_sample)
        self.widget._card_widgets[sample_id] = card
        self.widget.content_layout.insertWidget(0, card)
        self._animate_card_in(card)
        self.widget.updateSelectActions()

    def on_sample_removed_from_history(self, sample_id: int):
        """Slot: anime la sortie de la carte puis la supprime du layout."""
        self._clear_concat_preview()
        self._animate_remove_card(sample_id)

    def on_sample_deleted(self, sample_id: int):
        self._clear_concat_preview()
        self._animate_remove_card(sample_id)

    def on_sample_renamed(self, sample_id: int, old_path: str, new_path: str):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            self.close_waveforms_for_path(old_path)
            card.sample.name = os.path.splitext(os.path.basename(new_path))[0]
            card.sample.path = new_path
            card.refresh_display()

    def on_sample_moved(self, sample_id: int, target_folder: str):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            old_path = card.sample.path
            self.close_waveforms_for_path(old_path)
            new_path = os.path.join(target_folder, os.path.basename(old_path))
            card.sample.path = new_path
            card.updateLibraryCombo(self.widget.app_context.settings.libraries)
            card.refresh_display()

    def on_sample_duration_changed(self, sample_id: int, new_duration: float):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.sample.duration = new_duration
            card.length_label.setText(
                format_reserve_clock_duration(new_duration)
            )

    def on_sample_concat_candidate_changed(self, sample_id: int, enabled: bool, prev_id):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.setConcatCandidate(enabled, prev_id)
        if not enabled and sample_id in self._preview_pair_ids:
            self._clear_concat_preview()

    def on_sample_normalization_lock_changed(self, sample_id: int, locked: bool):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.setNormalizationLocked(locked)

    # ---- Refresh list
    def refresh_list(self):
        if self._should_build_first_page_incrementally():
            self._start_incremental_first_page()
            return

        start = perf_counter()
        self._clear_concat_preview()
        ordered_samples = self.widget.get_filtered_samples()
        self.widget.filtered_samples = list(ordered_samples)

        total_samples = len(ordered_samples)
        max_pages = max(1, ((total_samples - 1) // self.widget.samples_per_page) + 1) if total_samples else 1
        if self.widget.current_page > max_pages:
            self.widget.current_page = max_pages
        start_idx = (self.widget.current_page - 1) * self.widget.samples_per_page
        end_idx = start_idx + self.widget.samples_per_page
        page_samples = ordered_samples[start_idx:end_idx]

        # A page may instantiate dozens of fairly rich cards.  Keep the scroll
        # viewport quiet while the batch is assembled: otherwise Qt performs a
        # layout/paint pass for nearly every insertion, which makes the first
        # opening of Recents visibly stutter.
        content_widget = getattr(self.widget, "content_widget", None)
        if content_widget is not None:
            content_widget.setUpdatesEnabled(False)

        ids_courants = {s.id for s in page_samples}
        for ancien_id in list(self.widget._card_widgets):
            if ancien_id not in ids_courants:
                self._stop_card_animation(ancien_id)
                w = self.widget._card_widgets.pop(ancien_id)
                self.close_waveforms_for_path(w.sample.path)
                self.widget.content_layout.removeWidget(w)
                w.deleteLater()

        cartes_ordonnees = []
        for samp in page_samples:
            if samp.id in self.widget._card_widgets:
                card = self.widget._card_widgets[samp.id]
                card.sample = samp
                card.refresh_display()
                prev_id = self.widget.sample_store.get_concat_previous_id(samp.id)
                card.setConcatCandidate(prev_id is not None, prev_id)
                card.setNormalizationLocked(
                    self.widget.sample_store.is_normalization_locked(samp.id)
                )
            else:
                card = self._build_card(samp)
                self.widget._card_widgets[samp.id] = card
                if samp.id in self.widget.selected_ids:
                    card.checkbox.setChecked(True)
            cartes_ordonnees.append(card)

        while self.widget.content_layout.count():
            item = self.widget.content_layout.takeAt(0)
            w = item.widget()
            if w:
                self.widget.content_layout.removeWidget(w)

        for w in cartes_ordonnees:
            self.widget.content_layout.addWidget(w)
        self.widget.content_layout.addStretch()

        if content_widget is not None:
            content_widget.setUpdatesEnabled(True)
            content_widget.update()

        if total_samples == 0:
            self.widget.updatePaginationLabel(0, 0, 0)
        else:
            self.widget.updatePaginationLabel(
                start_idx + 1, min(end_idx, total_samples), total_samples
            )

        visible_ids = {int(sample.id) for sample in page_samples}
        pending_focus_id = self.widget._pending_focus_sample_id
        if pending_focus_id is not None:
            pending_card = self.widget._card_widgets.get(int(pending_focus_id))
            if pending_card is not None:
                self.widget._pending_focus_sample_id = None
                QTimer.singleShot(0, lambda c=pending_card: self.widget._focus_card(c))
            elif not visible_ids:
                self.widget._pending_focus_sample_id = None
                self.widget.set_current_reserve_sample(None)
        elif (
            self.widget._current_sample_id is not None
            and self.widget._current_sample_id not in visible_ids
        ):
            self.widget.set_current_reserve_sample(None)

        self.widget.updateSelectActions()
        self.widget._last_render_signature = self.widget._compute_samples_signature(self.widget.samples)
        logger.info(
            "[SampleListCards][Perf] refresh_list total=%s page=%s/%s visible_cards=%s layout_items=%s total=%.1fms",
            total_samples,
            self.widget.current_page,
            max_pages,
            len(page_samples),
            self.widget.content_layout.count(),
            (perf_counter() - start) * 1000.0,
        )

    def _should_build_first_page_incrementally(self) -> bool:
        """Use cooperative batches only for the costly first visible page."""
        if self._incremental_refresh_running or self.widget._card_widgets:
            return False
        is_visible = getattr(self.widget, "isVisible", None)
        if not callable(is_visible) or not is_visible():
            return False
        return len(self.widget.get_filtered_samples()) > 8

    def _start_incremental_first_page(self) -> None:
        """Materialise the first page without monopolising the Qt event loop."""
        start = perf_counter()
        self._clear_concat_preview()
        ordered_samples = self.widget.get_filtered_samples()
        self.widget.filtered_samples = list(ordered_samples)
        total_samples = len(ordered_samples)
        max_pages = max(
            1,
            ((total_samples - 1) // self.widget.samples_per_page) + 1,
        ) if total_samples else 1
        self.widget.current_page = min(self.widget.current_page, max_pages)
        start_idx = (self.widget.current_page - 1) * self.widget.samples_per_page
        page_samples = ordered_samples[
            start_idx:start_idx + self.widget.samples_per_page
        ]

        while self.widget.content_layout.count():
            item = self.widget.content_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                self.widget.content_layout.removeWidget(child)

        loading = QLabel("Chargement des récents…", self.widget.content_widget)
        loading.setObjectName("RecentLoadingLabel")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setStyleSheet("color: #858585; padding: 12px;")
        self.widget.content_layout.addWidget(loading)

        self._incremental_refresh_running = True
        self._pending_refresh_after_incremental = False
        self._incremental_generation += 1
        generation = self._incremental_generation
        queue = list(page_samples)
        built: list[SampleCard] = []
        loading_removed = False

        def build_batch() -> None:
            nonlocal loading_removed
            if generation != self._incremental_generation:
                return

            # Four cards keeps each UI slice short enough to preserve window
            # movement and repainting even on machines where card construction
            # is relatively expensive.
            for _ in range(min(4, len(queue))):
                sample = queue.pop(0)
                card = self._build_card(sample)
                self.widget._card_widgets[sample.id] = card
                if sample.id in self.widget.selected_ids:
                    card.checkbox.setChecked(True)
                built.append(card)

            if queue:
                QTimer.singleShot(0, build_batch)
                return

            # Publish the completed page in one layout pass.  Adding each batch
            # to a visible layout made the page resize and blink repeatedly.
            if not loading_removed:
                self.widget.content_layout.removeWidget(loading)
                loading.deleteLater()
                loading_removed = True
            self.widget.content_widget.setUpdatesEnabled(False)
            for card in built:
                self.widget.content_layout.addWidget(card)
            self.widget.content_layout.addStretch()
            self.widget.content_widget.setUpdatesEnabled(True)
            self.widget.content_widget.update()
            if total_samples:
                self.widget.updatePaginationLabel(
                    start_idx + 1,
                    min(start_idx + self.widget.samples_per_page, total_samples),
                    total_samples,
                )
            else:
                self.widget.updatePaginationLabel(0, 0, 0)
            self.widget._last_render_signature = self.widget._compute_samples_signature(
                self.widget.samples
            )
            self._incremental_refresh_running = False
            self.widget.updateSelectActions()
            pending_focus_id = self.widget._pending_focus_sample_id
            if pending_focus_id is not None:
                pending_card = self.widget._card_widgets.get(int(pending_focus_id))
                if pending_card is not None:
                    self.widget._pending_focus_sample_id = None
                    QTimer.singleShot(
                        0, lambda c=pending_card: self.widget._focus_card(c)
                    )
            logger.info(
                "[SampleListCards][Perf] first-page incremental cards=%s total=%.1fms",
                len(built),
                (perf_counter() - start) * 1000.0,
            )
            if self._pending_refresh_after_incremental:
                self._pending_refresh_after_incremental = False
                QTimer.singleShot(0, self.refresh_list)

        QTimer.singleShot(0, build_batch)

    # ---- Helpers
    def _build_card(self, samp):
        # Parent the card at construction time.  A parentless QWidget is a
        # top-level native window until the layout reparents it; during a large
        # first refresh this produced the succession of tiny flashing windows.
        card = SampleCard(
            samp,
            self.widget.app_context,
            parent=getattr(self.widget, "content_widget", None),
        )
        card.deleteSample.connect(self.widget.delete_sample)
        card.removeFromHistory.connect(
            lambda sample_id: self.widget.app_context.reserve_mutations.unindex(
                self.widget._entry_from_sample_id(sample_id)
            )
        )
        card.renameSample.connect(self.widget.rename_sample)
        card.sampleMoved.connect(self.widget.move_sample)
        card.normalizeClicked.connect(self.widget.onNormalizeClicked)
        card.selectionChanged.connect(self.widget.onSelectionChanged)
        card.concatWithPrevious.connect(self.widget.concat_with_previous)
        card.dismissConcat.connect(self.widget.dismiss_concat)
        card.concatPreviewHoverChanged.connect(self.widget.onConcatPreviewHoverChanged)
        card.activated.connect(self.widget.set_current_reserve_sample)
        if self.widget.reserve_actions is not None:
            card.set_external_waveform_handler(
                lambda sample, w=self.widget: w.reserve_actions.open_waveform(
                    w._entry_from_sample(sample)
                )
            )

        prev_id = self.widget.sample_store.get_concat_previous_id(samp.id)
        card.setConcatCandidate(prev_id is not None, prev_id)
        card.setNormalizationLocked(
            self.widget.sample_store.is_normalization_locked(samp.id)
        )
        card.setConcatPreviewActive(False)

        self.widget.sample_store.sampleRenamed.connect(card.onRenameSuccess)
        self.widget.sample_store.sampleMoved.connect(card.onMoveSuccess)
        card.findCompatiblesRequested.connect(self.widget.onFindCompatiblesRequested)
        card.openInFoldersRequested.connect(self.widget.onOpenInFoldersRequested)
        return card

    def on_sample_scale_analyzed(self, sample_id: int) -> None:
        """Met a jour le badge de gamme de la carte concernee."""
        card = self.widget._card_widgets.get(sample_id)
        if card is None:
            return
        # Synchronise l'objet sample depuis le cache du service
        updated = next(
            (s for s in self.widget.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if updated is not None:
            card.sample = updated
        card.update_scale_badge()

    def _animate_remove_card(self, sample_id: int):
        card = self.widget._card_widgets.get(sample_id)
        if not card:
            self.widget.updateSelectActions()
            return
        if sample_id in self._exit_animations:
            return

        self._stop_card_animation(sample_id)
        self.close_waveforms_for_path(card.sample.path)
        self.widget.selected_ids.discard(sample_id)
        self.widget._pending_focus_sample_id = self._next_focus_candidate_id(sample_id)

        def _finalize():
            self.widget.content_layout.removeWidget(card)
            card.deleteLater()
            self.widget._card_widgets.pop(sample_id, None)
            self.widget.updateSelectActions()

        self._animate_card_out(card, sample_id, _finalize)

    def _animate_card_in(self, card: SampleCard):
        sample_id = int(card.sample.id)
        self._stop_card_animation(sample_id)

        target_h = max(1, card.sizeHint().height())
        card.setMaximumHeight(0)

        grow = QPropertyAnimation(card, b"maximumHeight", card)
        grow.setDuration(220)
        grow.setStartValue(0)
        grow.setEndValue(target_h)
        grow.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _done():
            card.setMaximumHeight(16777215)
            self._entry_animations.pop(sample_id, None)

        grow.finished.connect(_done)
        self._entry_animations[sample_id] = grow
        grow.start()

    def _animate_card_out(self, card: SampleCard, sample_id: int, on_done):
        start_h = max(1, max(card.height(), card.sizeHint().height()))
        card.setMaximumHeight(start_h)

        collapse = QPropertyAnimation(card, b"maximumHeight", card)
        collapse.setDuration(190)
        collapse.setStartValue(start_h)
        collapse.setEndValue(0)
        collapse.setEasingCurve(QEasingCurve.Type.InCubic)

        def _done():
            self._exit_animations.pop(sample_id, None)
            on_done()
            if not self._exit_animations and self._pending_refresh_after_exit:
                self._pending_refresh_after_exit = False
                self.refresh_list()
                self.widget.updateSelectActions()

        collapse.finished.connect(_done)
        self._exit_animations[sample_id] = collapse
        collapse.start()

    def _stop_card_animation(self, sample_id: int):
        anim_in = self._entry_animations.pop(sample_id, None)
        if anim_in:
            anim_in.stop()
        anim_out = self._exit_animations.pop(sample_id, None)
        if anim_out:
            anim_out.stop()

    def _next_focus_candidate_id(self, sample_id: int) -> int | None:
        ordered_samples = self.widget.get_filtered_samples()
        ordered_ids = [int(sample.id) for sample in ordered_samples]
        if not ordered_ids:
            return None
        try:
            index = ordered_ids.index(int(sample_id))
        except ValueError:
            current_cards = self.widget._visible_cards_in_order()
            for card in current_cards:
                if int(card.sample.id) != int(sample_id):
                    return int(card.sample.id)
            return None
        if index + 1 < len(ordered_ids):
            return ordered_ids[index + 1]
        if index - 1 >= 0:
            return ordered_ids[index - 1]
        return None

    def on_concat_preview_hover_changed(self, sample_id: int, active: bool, prev_id):
        if not active:
            self._clear_concat_preview()
            return

        target_ids = {sample_id}
        if prev_id is not None:
            target_ids.add(int(prev_id))

        if target_ids != self._preview_pair_ids:
            self._clear_concat_preview()

        self._preview_pair_ids = set()
        for sid in target_ids:
            card = self.widget._card_widgets.get(sid)
            if not card:
                continue
            card.setConcatPreviewActive(True)
            self._preview_pair_ids.add(sid)

    def _clear_concat_preview(self):
        if not self._preview_pair_ids:
            return
        for sid in tuple(self._preview_pair_ids):
            card = self.widget._card_widgets.get(sid)
            if card:
                card.setConcatPreviewActive(False)
        self._preview_pair_ids.clear()

    def close_waveforms_for_path(self, path):
        for i in range(self.widget.content_layout.count()):
            w = self.widget.content_layout.itemAt(i).widget()
            if isinstance(w, SampleCard) and w.sample.path == path and w.wave_edition_widget:
                try:
                    w.wave_edition_widget.stop_audio()
                except Exception:
                    pass
                try:
                    w.wave_edition_widget.timer.stop()
                except Exception:
                    pass

                w.waveform_layout.removeWidget(w.wave_edition_widget)
                w.wave_edition_widget.deleteLater()
                w.wave_edition_widget = None
