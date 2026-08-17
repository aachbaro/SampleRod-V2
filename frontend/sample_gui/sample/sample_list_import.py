# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'import manuel de fichiers audio via QFileDialog.
# - Detecte les doublons et propose le reimport (suppression + re-ajout).
# - Memorise le dernier dossier selectionne (QSettings "lastSampleDir").
#
# FONCTIONS (sommaire)
# - SampleListImport : controleur d'import manuel
# - add_files()      : ouvre QFileDialog, filtre .wav, gere doublons, ajoute via SampleStore
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py : SampleListWidget (widget parent)
# - backend/services/reserve_import_service.py : contrat métier d'import
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from backend.services.reserve_import_service import (
    ReserveImportRequest, ReserveReimportPolicy,
)
from PySide6.QtWidgets import QFileDialog, QMessageBox


class SampleListImport:
    """Controleur d'import manuel de fichiers audio dans SampleListWidget."""

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
            policy = ReserveReimportPolicy.SKIP
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
                policy = ReserveReimportPolicy.REINDEX
            try:
                result = self.widget.app_context.reserve_imports.import_request(
                    ReserveImportRequest(
                        paths=(path,),
                        status="source",
                        reimport_policy=policy,
                    )
                )
                if result.errors:
                    raise RuntimeError(result.errors[0][1])
            except Exception as e:
                QMessageBox.warning(
                    self.widget,
                    "Erreur d'ajout",
                    f"Impossible d'ajouter le fichier :\n{path}\n\n{e}",
                )
