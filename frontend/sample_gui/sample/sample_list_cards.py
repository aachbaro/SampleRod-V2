# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le cycle de vie des SampleCard (creation, suppression, refresh).
# - Centralise la reconstruction de la liste (pagination + layout).
# - Met a jour les cartes suite aux evenements du service.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from frontend.sample_gui.sample.sample_card import SampleCard


class SampleListCards:
    def __init__(self, widget):
        self.widget = widget

    # ---- Service slots
    def on_samples_changed(self, samples: list):
        self.widget.samples = samples
        self.refresh_list()
        self.widget.updateSelectActions()

    def on_sample_added(self, sample_id: int):
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

    def on_sample_removed_from_history(self, sample_id: int):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            self.close_waveforms_for_path(card.sample.path)
            self.widget.content_layout.removeWidget(card)
            card.deleteLater()
            del self.widget._card_widgets[sample_id]
            self.widget.selected_ids.discard(sample_id)
        self.widget.updateSelectActions()

    def on_sample_deleted(self, sample_id: int):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            self.close_waveforms_for_path(card.sample.path)
            self.widget.content_layout.removeWidget(card)
            card.deleteLater()
            del self.widget._card_widgets[sample_id]
            self.widget.selected_ids.discard(sample_id)
        self.widget.updateSelectActions()

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
            card.length_label.setText(f"{new_duration:.1f}s")

    def on_sample_concat_candidate_changed(self, sample_id: int, enabled: bool, prev_id):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.setConcatCandidate(enabled, prev_id)

    def on_sample_normalization_lock_changed(self, sample_id: int, locked: bool):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.setNormalizationLocked(locked)

    # ---- Refresh list
    def refresh_list(self):
        ordered_samples = sorted(self.widget.samples, key=lambda s: s.id, reverse=True)

        total_samples = len(ordered_samples)
        start_idx = (self.widget.current_page - 1) * self.widget.samples_per_page
        end_idx = start_idx + self.widget.samples_per_page
        page_samples = ordered_samples[start_idx:end_idx]

        ids_courants = {s.id for s in page_samples}
        for ancien_id in list(self.widget._card_widgets):
            if ancien_id not in ids_courants:
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

        if total_samples == 0:
            self.widget.updatePaginationLabel(0, 0, 0)
        else:
            self.widget.updatePaginationLabel(
                start_idx + 1, min(end_idx, total_samples), total_samples
            )

        self.widget.updateSelectActions()

    # ---- Helpers
    def _build_card(self, samp):
        card = SampleCard(samp, self.widget.app_context)
        card.deleteSample.connect(self.widget.delete_sample)
        card.removeFromHistory.connect(self.widget.sample_store.removeFromHistory)
        card.renameSample.connect(self.widget.rename_sample)
        card.sampleMoved.connect(self.widget.move_sample)
        card.normalizeClicked.connect(self.widget.onNormalizeClicked)
        card.selectionChanged.connect(self.widget.onSelectionChanged)
        card.concatWithPrevious.connect(self.widget.concat_with_previous)
        card.dismissConcat.connect(self.widget.dismiss_concat)

        prev_id = self.widget.sample_store.get_concat_previous_id(samp.id)
        card.setConcatCandidate(prev_id is not None, prev_id)
        card.setNormalizationLocked(
            self.widget.sample_store.is_normalization_locked(samp.id)
        )

        self.widget.sample_store.sampleRenamed.connect(card.onRenameSuccess)
        self.widget.sample_store.sampleMoved.connect(card.onMoveSuccess)
        return card

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
