# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le drag & drop audio depuis l'explorateur et les modules SampleRod.
# - Accepte fichiers, stems, artefacts et selections editees en memoire.
# - Cree les samples via SampleStore et coche les cartes correspondantes.
#
# FONCTIONS (sommaire)
# - SampleListDragDrop   : controleur DnD de la liste
# - drag_enter / drag_move : accepte si URLs presentes
# - drop()               : filtre les .wav, ajoute les samples, coche les cartes
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py : SampleListWidget (widget parent)
# - backend/services/reserve_import_service.py : contrat métier d'import
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from dataclasses import replace

from backend.services.audio_metadata import audio_path_key
from backend.services.reserve_import_service import ReserveReimportPolicy
from frontend.labo.audio_drop import can_accept_audio_drop
from frontend.reserve.reserve_import_adapters import import_request_from_mime


class SampleListDragDrop:
    """Controleur de drag & drop pour l'import audio dans la Reserve."""

    def __init__(self, widget):
        self.widget = widget

    def _sample_path(self, sample_id: int) -> str | None:
        sample = next(
            (item for item in self.widget.sample_store.get_cached()
             if int(getattr(item, "id", -1)) == int(sample_id)),
            None,
        )
        return str(getattr(sample, "path", "") or "") or None

    def _artifact_path(self, artifact_id: str) -> str | None:
        store = getattr(self.widget.app_context, "lab_artifact_store", None)
        resolver = getattr(store, "resolve_path", None)
        return resolver(artifact_id) if callable(resolver) else None

    def _accepts(self, mime) -> bool:
        return can_accept_audio_drop(
            mime,
            sample_path_lookup=self._sample_path,
            artifact_path_lookup=self._artifact_path,
        )

    def drag_enter(self, event):
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def drag_move(self, event):
        if self._accepts(event.mimeData()):
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
        request = import_request_from_mime(
            event.mimeData(),
            sample_path_lookup=self._sample_path,
            artifact_path_lookup=self._artifact_path,
        )
        if not request.paths:
            return

        imported = []
        for path in request.paths:
            item_request = replace(request, paths=(path,))
            existing = next(
                (sample for sample in self.widget.sample_store.get_cached()
                 if audio_path_key(sample.path) == audio_path_key(path)),
                None,
            )
            if existing:
                answer = QMessageBox.question(
                    self.widget,
                    "Sample deja importe",
                    "Ce sample existe deja.\nVoulez-vous le retirer de la bibliotheque puis le reimporter en tete ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if answer == QMessageBox.StandardButton.No:
                    continue
                item_request = replace(
                    item_request, reimport_policy=ReserveReimportPolicy.REINDEX
                )
            result = self.widget.app_context.reserve_imports.import_request(item_request)
            imported.extend(result.imported_samples)

        for sample in imported:
            sid = int(sample.id)
            card = self.widget._card_widgets.get(sid)
            if card:
                card.checkbox.setChecked(True)

        self.widget.scroll_area.verticalScrollBar().setValue(0)
        if imported:
            event.acceptProposedAction()
        else:
            event.ignore()
