# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le drag & drop de fichiers audio depuis l'explorateur systeme.
# - Accepte uniquement les URLs locales de fichiers .wav.
# - Cree les samples via SampleStore et coche les cartes correspondantes.
#
# FONCTIONS (sommaire)
# - SampleListDragDrop   : controleur DnD de la liste
# - drag_enter / drag_move : accepte si URLs presentes
# - drop()               : filtre les .wav, ajoute les samples, coche les cartes
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py : SampleListWidget (widget parent)
# - backend/models/SampleLibrary.py           : sample_store.add()
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from PySide6.QtWidgets import QMessageBox


class SampleListDragDrop:
    """Controleur de drag & drop pour l'import de fichiers .wav dans SampleListWidget."""

    def __init__(self, widget):
        self.widget = widget

    def drag_enter(self, event):
        # N'accepte que si on a des URLs (fichiers)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def drag_move(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def drop(self, event):
        """
        Lorsqu'on lache des fichiers :
        - recupere les chemins locaux
        - cree les samples
        - coche automatiquement les cases correspondantes
        """
        urls = event.mimeData().urls()
        if not urls:
            return

        paths = []
        for u in urls:
            local = u.toLocalFile()
            if os.path.isfile(local) and local.lower().endswith(".wav"):
                paths.append(local)

        if not paths:
            return

        new_ids = []

        def _on_added(sid):
            new_ids.append(sid)

        self.widget.sample_store.sampleAdded.connect(_on_added)

        for p in paths:
            existing = next((s for s in self.widget.sample_store.get_cached() if s.path == p), None)
            if existing:
                answer = QMessageBox.question(
                    self.widget,
                    "Sample deja importe",
                    "Ce sample existe deja.\nVoulez-vous le retirer de la bibliotheque puis le reimporter en tete ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if answer == QMessageBox.StandardButton.No:
                    continue
                self.widget.sample_store.delete_record_by_path(p)
            self.widget.sample_store.add(p)

        self.widget.sample_store.sampleAdded.disconnect(_on_added)

        for sid in new_ids:
            card = self.widget._card_widgets.get(sid)
            if card:
                card.checkbox.setChecked(True)

        self.widget.scroll_area.verticalScrollBar().setValue(0)
