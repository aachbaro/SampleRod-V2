"""
------------------------------------------------------------------------------
Directory List Item Widget
------------------------------------------------------------------------------
Role
----
Ce module contient le widget "ligne" utilise par le DirectoryWidget.

Chaque ligne represente un fichier audio present dans le dossier courant et
expose des actions rapides:
- Renommer inline (double-clic sur le nom).
- Pre-ecouter (play/pause) via l'audio_player partage.
- Supprimer le fichier (via sample_store).

Pourquoi l'extraire ?
---------------------
Le DirectoryWidget reste un "orchestrateur" (liste + DnD + synchro store),
alors que la ligne elle-meme est un composant UI autonome.
Cela rend le refactor plus simple et prepare l'arrivee d'autres outils dans le
Right Panel (ex: Sample Composer) sans gonfler un seul fichier monolithique.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import logging
from typing import Any

from PyQt6.QtWidgets import (
    QWidget,
    QMessageBox,
)

from . import directory_ui

logger = logging.getLogger("directory_item_widget")


class DirectoryListItemWidget(QWidget):
    """
    UI "row" pour la liste du DirectoryWidget.

    Note: on garde volontairement la dependance au parent_widget (DirectoryWidget)
    via des callbacks/methodes (toggle_preview, _remove_widget, app_context...).
    Dans une etape suivante, on pourra remplacer ca par une petite interface
    (controller) pour decoupler davantage.
    """

    def __init__(self, file_path: str, parent_widget: Any, sample_id: int | None = None):
        super().__init__()
        self.file_path = file_path
        self.parent_widget = parent_widget
        self.sample_id = sample_id

        # UI construction: centralisee dans directory_ui.py
        directory_ui.build_directory_item_ui(
            self,
            file_path,
            on_start_rename=self._start_rename,
            on_submit_rename=self._submit_rename,
            on_toggle_preview=self._on_clicked,
            on_delete=self._on_delete,
        )

    # ------------------------------------------------------------------ actions
    def _on_clicked(self):
        """Delegue au DirectoryWidget (un seul preview a la fois)."""
        self.parent_widget.toggle_preview(self)

    # ------------------------------------------------------------------ rename
    def _start_rename(self, event):
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        self.rename_input.setText(base_name)
        self.name_label.hide()
        self.rename_input.show()
        self.rename_input.setFocus()
        self.rename_input.selectAll()

    def _submit_rename(self):
        new_name = self.rename_input.text().strip()
        old_base = os.path.splitext(os.path.basename(self.file_path))[0]
        if new_name and new_name != old_base:
            success, err = self.parent_widget.app_context.sample_store.rename_by_path(
                self.file_path,
                new_name,
            )
            if success:
                ext = os.path.splitext(self.file_path)[1]
                folder = os.path.dirname(self.file_path)
                new_path = os.path.join(folder, new_name + ext)
                self.file_path = new_path
                self.name_label.setText(os.path.basename(new_path))
            elif err:
                QMessageBox.warning(self, "Erreur", err)

        self.rename_input.hide()
        self.name_label.show()

    # ------------------------------------------------------------------ delete
    def _on_delete(self):
        reply = QMessageBox.question(
            self,
            "Supprimer",
            f"Supprimer le fichier '{os.path.basename(self.file_path)}' ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Arret de la lecture si ce fichier est en cours.
        ap = self.parent_widget.app_context.audio_player
        if ap.current_sample_path == self.file_path:
            try:
                ap.clear_audio()
            except Exception:
                pass

        success, err = self.parent_widget.app_context.sample_store.delete_by_path(self.file_path)
        if not success and err:
            QMessageBox.warning(self, "Erreur", err)

        # Si l'entree n'est pas trackee en DB, on retire immediatement la ligne.
        # Sinon, le sample_store emettra sampleDeleted -> le DirectoryWidget se mettra a jour.
        if self.sample_id is None:
            self.parent_widget._remove_widget(self)

    # ------------------------------------------------------------------ ui state
    def set_playing(self, playing: bool):
        """Met a jour l'icone play/pause de la ligne."""
        directory_ui.set_item_playing(self, playing)
