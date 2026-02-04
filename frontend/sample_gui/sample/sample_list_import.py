# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'import manuel via QFileDialog (ajout de fichiers audio).
# - Centralise la logique d'evitement des doublons et de reimport.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox


class SampleListImport:
    def __init__(self, widget):
        self.widget = widget

    def add_files(self):
        """
        Ouvre un QFileDialog pour selectionner un ou plusieurs fichiers,
        puis les ajoute un par un via SampleService.add().
        """
        last_dir = self.widget._qs.value("lastSampleDir", os.path.expanduser("~"), type=str)
        fichiers, _ = QFileDialog.getOpenFileNames(
            self.widget,
            "Selectionner des fichiers audio",
            last_dir,
            "Fichiers WAV (*.wav);;Tous les fichiers (*)",
        )
        if not fichiers:
            return

        new_dir = os.path.dirname(fichiers[0])
        self.widget._qs.setValue("lastSampleDir", new_dir)

        for path in fichiers:
            existing = next(
                (s for s in self.widget.sample_store.get_cached() if s.path == path),
                None,
            )
            if existing:
                answer = QMessageBox.question(
                    self.widget,
                    "Sample deja importe",
                    "Ce sample existe deja.\nVoulez-vous le retirer de la bibliotheque puis le reimporter en tete ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.No:
                    continue
                self.widget.sample_store.delete_record_by_path(path)
            try:
                self.widget.sample_store.add(path)
            except Exception as e:
                QMessageBox.warning(
                    self.widget,
                    "Erreur d'ajout",
                    f"Impossible d'ajouter le fichier :\n{path}\n\n{e}",
                )
