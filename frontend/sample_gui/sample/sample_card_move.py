# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le deplacement d'un sample vers une autre librairie.
# - La combobox propose les librairies configurees + "Autre..." (QFileDialog).
# - Met a jour le sample.path et la combobox apres un deplacement reussi.
#
# FONCTIONS (sommaire)
# - SampleCardMove      : controleur de deplacement
# - move_sample(index)  : index 0 = inaction, 1..N = librairies, dernier = "Autre..."
# - on_move_success()   : met a jour sample.path + combobox
# - update_library_combo() : reconstruit les items sans declencher de signal
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py : carte parente
# - backend/services/settings_service.py      : settings.libraries
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QFileDialog

logger = logging.getLogger("sample_card")


class SampleCardMove:
    """Controleur de deplacement de sample vers une librairie ou un dossier "Autre..."."""

    def __init__(self, card):
        self.card = card

    def move_sample(self, index: int):
        """
        - index==0 : dossier courant -> rien a faire
        - 1 <= index <= len(libs) : deplacer vers settings.libraries[index-1]
        - index == dernier item : ouvrir un QFileDialog pour dossier "Autre..."
        """
        c = self.card
        count = c.change_dir_combobox.count()
        if index == 0:
            return

        if index == count - 1:
            folder = QFileDialog.getExistingDirectory(
                c,
                "Choisir un dossier de destination",
                os.path.dirname(c.sample.path),
            )
            if not folder:
                c.change_dir_combobox.setCurrentIndex(0)
                return
            new_dir = folder
        else:
            try:
                target_library = c.settings.libraries[index - 1]
                new_dir = target_library.path
            except IndexError:
                return

        if c.app_context.audio_player.current_sample_id == c.sample.id:
            try:
                c.app_context.audio_player.clear_audio()
                c.playback.set_paused_icon()
            except Exception:
                pass

        logger.info(f"[SampleCard] Deplacer l'echantillon {c.sample.id} -> {new_dir}")
        c.sampleMoved.emit(c.sample.id, new_dir)
        c.change_dir_combobox.setCurrentIndex(0)

    def on_move_success(self, sample_id, new_dir: str):
        """Slot: met a jour le chemin du sample et reconstruit la combobox."""
        c = self.card
        if c.sample.id == sample_id:
            c.sample.path = os.path.join(new_dir, os.path.basename(c.sample.path))
            self.update_library_combo(c.settings.libraries)
            c.refresh_display()

    def update_library_combo(self, libs: list):
        """
        Met a jour le contenu de la combobox sans declencher de signal.
        """
        c = self.card
        current_folder = c.get_folder_name(c.sample.path) + "/"
        c.change_dir_combobox.blockSignals(True)
        c.change_dir_combobox.clear()
        c.change_dir_combobox.addItem(current_folder)
        for library in sorted(libs, key=lambda lib: lib.position):
            nom = os.path.basename(library.path) + "/"
            c.change_dir_combobox.addItem(nom)
        c.change_dir_combobox.addItem("Autre...")
        c.change_dir_combobox.blockSignals(False)
