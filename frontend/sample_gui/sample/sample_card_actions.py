# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe les actions "header" d'une SampleCard (rename / delete / archive /
#   normalize) pour separer l'UI de la logique.
# - Centralise les etats visuels associes (champs de renommage, statut).
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import qtawesome as qta

from PyQt6.QtWidgets import QMessageBox


class SampleCardHeaderActions:
    def __init__(self, card):
        self.card = card

    # ---- Rename
    def start_rename(self):
        c = self.card
        c.isRenaming = True
        c.rename_input.setText(c.get_sample_name())

        c.rename_input.setVisible(True)
        c.check_button.setVisible(True)
        c.cancel_button.setVisible(True)

        c.name_label.setVisible(False)

        c.rename_input.setFocus()

    def cancel_rename(self):
        c = self.card
        c.isRenaming = False

        c.rename_input.setVisible(False)
        c.check_button.setVisible(False)
        c.cancel_button.setVisible(False)

        c.name_label.setVisible(True)

    def submit_rename(self):
        c = self.card
        new_name = c.rename_input.text().strip()
        if new_name and new_name != c.get_sample_name():
            c.renameSample.emit(c.sample.id, new_name)
        c.isRenaming = False

        c.rename_input.setVisible(False)
        c.check_button.setVisible(False)
        c.cancel_button.setVisible(False)

        c.name_label.setVisible(True)

    def on_rename_success(self, sample_id, old_path, new_path):
        c = self.card
        if c.sample.id == sample_id:
            new_name = os.path.splitext(os.path.basename(new_path))[0]
            c.sample.name = new_name
            c.sample.path = new_path
            c.name_label.setText(new_name)
            self.cancel_rename()

    def on_rename_error(self, sample_id, error_msg):
        if self.card.sample.id == sample_id:
            QMessageBox.critical(
                self.card,
                "Erreur de renommage",
                f"Impossible de renommer: {error_msg}",
            )

    # ---- Delete / archive
    def confirm_delete(self):
        """
        Stoppe la lecture si ce sample est en cours,
        puis emet le signal pour supprimer fichier + DB.
        """
        c = self.card
        if c.app_context.audio_player.current_sample_id == c.sample.id:
            try:
                c.app_context.audio_player.clear_audio()
                if hasattr(c.play_button, "set_icon_pair"):
                    c.play_button.set_icon_pair(
                        "fa5s.play",
                        icon_color_normal="#cfcfcf",
                        icon_color_hover="#121212",
                    )
                else:
                    c.play_button.setIcon(qta.icon("fa5s.play", color="lightgray"))
            except Exception:
                pass
        c.deleteSample.emit(c.sample.id)

    def archive(self):
        """
        Stoppe la lecture si ce sample est en cours,
        puis emet le signal pour retirer de l'historique.
        """
        c = self.card
        if c.app_context.audio_player.current_sample_id == c.sample.id:
            try:
                c.app_context.audio_player.clear_audio()
                if hasattr(c.play_button, "set_icon_pair"):
                    c.play_button.set_icon_pair(
                        "fa5s.play",
                        icon_color_normal="#cfcfcf",
                        icon_color_hover="#121212",
                    )
                else:
                    c.play_button.setIcon(qta.icon("fa5s.play", color="lightgray"))
            except Exception:
                pass
        c.removeFromHistory.emit(c.sample.id)

    # ---- Normalize
    def normalize_clicked(self):
        c = self.card
        current_id = c.app_context.audio_player.current_sample_id
        if current_id == c.sample.id:
            try:
                c.app_context.audio_player.clear_audio()
            except Exception:
                pass

        c.status_label.setText("⏳ Normalisation...")
        c.status_label.setVisible(True)
        c.normalize_button.setEnabled(False)
        c.normalizeClicked.emit(c.sample.id)

    def indicate_normalization_started(self):
        c = self.card
        c.status_label.setText("⏳ Normalisation...")
        c.status_label.setVisible(True)
        c.normalize_button.setEnabled(False)

    def indicate_normalization_finished(self):
        c = self.card
        c.status_label.setText("✔️ Normalisé")
        c.status_label.setVisible(True)
        c.normalize_button.setEnabled(True)

    def indicate_normalization_error(self, message: str):
        c = self.card
        c.status_label.setText(f"❌ Erreur: {message}")
        c.status_label.setVisible(True)
        c.normalize_button.setEnabled(True)
