# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere la selection (checkbox) et les actions bulk de SampleListWidget.
# - Centralise l'activation des boutons selon la selection.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from backend.models.normalize_worker import NormalizeWorker

logger = logging.getLogger("sample_list")


class SampleListSelection:
    def __init__(self, widget):
        self.widget = widget

    # ---- Selection
    def on_selection_changed(self, sample_id: int, checked: bool):
        logger.info("onSelectionChanged: sample_id=%s, checked=%s", sample_id, checked)
        if checked:
            self.widget.selected_ids.add(sample_id)
        else:
            self.widget.selected_ids.discard(sample_id)

        any_selected = len(self.widget.selected_ids) > 0
        self.widget.bulk_delete_act.setEnabled(any_selected)
        self.widget.bulk_move_act.setEnabled(any_selected)
        self.widget.bulk_normalize_act.setEnabled(any_selected)
        self.widget.bulk_archive_act.setEnabled(any_selected)

        self.update_select_actions()

    def update_select_actions(self):
        any_samples = bool(self.widget._card_widgets)
        all_selected = len(self.widget.selected_ids) == len(self.widget._card_widgets)
        none_selected = len(self.widget.selected_ids) == 0

        # Support legacy QAction buttons or the new round HoverIconButton widgets.
        if hasattr(self.widget, "select_all_btn"):
            self.widget.select_all_btn.setEnabled(any_samples and not all_selected)
        if hasattr(self.widget, "deselect_all_btn"):
            self.widget.deselect_all_btn.setEnabled(any_samples and not none_selected)
        if hasattr(self.widget, "select_all_act"):
            self.widget.select_all_act.setEnabled(any_samples and not all_selected)
        if hasattr(self.widget, "deselect_all_act"):
            self.widget.deselect_all_act.setEnabled(any_samples and not none_selected)

    def select_all(self):
        for card in self.widget._card_widgets.values():
            card.checkbox.setChecked(True)

    def deselect_all(self):
        for card in self.widget._card_widgets.values():
            card.checkbox.setChecked(False)

    # ---- Bulk actions
    def bulk_remove_from_history(self):
        if not self.widget.selected_ids:
            return

        reply = QMessageBox.question(
            self.widget,
            "Confirmer la suppression de l'historique",
            f"Voulez-vous vraiment retirer les {len(self.widget.selected_ids)} echantillons de l'historique ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for sample_id in list(self.widget.selected_ids):
            self.widget.sample_store.removeFromHistory(sample_id)

        self.widget.selected_ids.clear()
        self.widget.bulk_delete_act.setEnabled(False)
        self.widget.bulk_move_act.setEnabled(False)
        self.widget.bulk_normalize_act.setEnabled(False)
        self.widget.bulk_archive_act.setEnabled(False)
        self.update_select_actions()

    def bulk_delete(self):
        if not self.widget.selected_ids:
            return
        reply = QMessageBox.question(
            self.widget,
            "Confirmer la suppression",
            f"Voulez-vous vraiment supprimer les {len(self.widget.selected_ids)} echantillons selectionnes ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            to_delete = list(self.widget.selected_ids)
            current = self.widget.app_context.audio_player.current_sample_id
            if current in to_delete:
                self.widget.app_context.audio_player.clear_audio()

            self.widget.sample_store.bulkDelete(to_delete)
            self.widget.selected_ids.clear()
            self.widget.bulk_delete_act.setEnabled(False)
            self.widget.bulk_move_act.setEnabled(False)
            self.widget.bulk_normalize_act.setEnabled(False)
            self.update_select_actions()

    def bulk_move(self):
        if not self.widget.selected_ids:
            return

        dossier = QFileDialog.getExistingDirectory(
            self.widget, "Choisir le dossier de destination"
        )
        if not dossier:
            return

        for sample_id in list(self.widget.selected_ids):
            self.widget.sample_store.move(sample_id, dossier)

        self.widget.selected_ids.clear()
        self.widget.bulk_delete_act.setEnabled(False)
        self.widget.bulk_move_act.setEnabled(False)
        self.widget.bulk_normalize_act.setEnabled(False)
        self.update_select_actions()

    def bulk_normalize(self):
        if not self.widget.selected_ids:
            return
        for sample_id in list(self.widget.selected_ids):
            samp = next(
                (s for s in self.widget.sample_store.get_cached() if s.id == sample_id),
                None,
            )
            if samp is None:
                continue
            worker = NormalizeWorker(
                sample_id=sample_id,
                file_path=samp.path,
                mode="lufs",
                target_db=self.widget.app_context.settings.getNormalizationLevel(),
            )
            worker.startedNormalization.connect(self.widget.onStartedNormalization)
            worker.finishedNormalization.connect(self.widget.onFinishedNormalization)
            worker.normalizationFailed.connect(self.widget.onNormalizationFailed)
            worker.start()
            self.widget.app_context.sample_store._normalize_threads[sample_id] = worker
