# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Objet QObject partage entre les trois onglets de la Reserve (Dossiers,
#   Historique, Indexe) qui centralise les actions communes sur un ReserveEntry.
# - Evite de dupliquer la logique de preview, de renommage ou d'envoi au Labo
#   dans chaque widget.
#
# FONCTIONS (sommaire)
# - ReserveActions           : classe principale (partage par reference)
# - can_preview()            : True si le fichier est present et lisible
# - preview()                : lecture/arret via AudioPlayer (toggle)
# - seek_preview()           : saut a une position donnee (ms)
# - rename()                 : renomme via sample_store
# - reveal_in_folder()       : ouvre le dossier dans l'explorateur
# - open_waveform()          : emet waveformRequested -> Labo
# - send_to_lab()            : emet sendToLabRequested -> Labo
#
# Signaux emis :
#   sendToLabRequested(list[str])  : liste de chemins a ouvrir dans le Labo
#   waveformRequested(ReserveEntry): demande d'ouverture de la waveform
#   previewChanged(ReserveEntry | None): change d'etat de la lecture
#
# LIENS CLES
# - frontend/reserve/reserve_entry.py    : type ReserveEntry
# - backend/models/AppContext.py         : audio_player, sample_store
# - frontend/reserve/reserve_pane.py     : connecte les signaux
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QDesktopServices

from backend.services.audio_metadata import get_audio_duration, normalize_audio_path
from backend.services.reserve_mutation_service import ReserveMutationService
from .reserve_entry import ReserveEntry
from .reserve_preview import ensure_reserve_preview


class ReserveActions(QObject):
    """Actions communes partagees par les trois onglets de la Reserve.

    Une instance est creee dans ReservePane et passee en parametre a chaque
    widget enfant (DirectoryWidget, SampleListWidget, LibraryWidget). Cela
    evite de reimplementer la logique de lecture, de renommage et d'envoi au
    Labo dans chaque onglet.
    """

    sendToLabRequested = Signal(list)
    waveformRequested = Signal(object)
    previewChanged = Signal(object)

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context
        self.sample_store = app_context.sample_store
        self.audio_player = app_context.audio_player
        self.preview_controller = ensure_reserve_preview(app_context)
        self.preview_controller.activeEntryChanged.connect(self.previewChanged)
        self.mutations = getattr(app_context, "reserve_mutations", None)
        if self.mutations is None:
            self.mutations = ReserveMutationService(app_context)

    def can_preview(self, entry: ReserveEntry | None) -> bool:
        """Retourne True si le fichier existe sur disque et n'est pas marque manquant."""
        return bool(entry and entry.path and os.path.isfile(entry.path) and not entry.missing)

    def can_rename(self, entry: ReserveEntry | None) -> bool:
        return bool(entry and entry.path and os.path.isfile(entry.path) and not entry.missing)

    def can_open_waveform(self, entry: ReserveEntry | None) -> bool:
        return self.can_preview(entry)

    def can_reveal_in_folder(self, entry: ReserveEntry | None) -> bool:
        return bool(entry and entry.path)

    def can_send_to_lab(self, entry: ReserveEntry | None) -> bool:
        return self.can_preview(entry)

    def is_previewing(self, entry: ReserveEntry | None) -> bool:
        """Retourne True si c'est ce sample qui est actuellement en lecture."""
        return self.preview_controller.is_active(entry)

    def seek_preview(self, entry: ReserveEntry | None, position_ms: int) -> bool:
        """Saute a la position donnee (en ms) dans la lecture du sample.

        Retourne True si le sample est en lecture apres le saut.
        """
        if not self.can_preview(entry):
            return False
        assert entry is not None

        duration = self._duration_for_entry(entry)
        if duration <= 0:
            return False
        position_ms = max(0, min(int(position_ms), int(duration * 1000)))
        return self.preview_controller.seek(entry, position_ms)

    def preview(self, entry: ReserveEntry | None) -> bool:
        """Lance ou arrete la lecture du sample (toggle).

        Si le sample est deja en lecture, l'arrete et emet previewChanged(None).
        Sinon, demarre la lecture et emet previewChanged(entry).
        Retourne True si la lecture a demarree, False si elle a ete arretee.
        """
        if not self.can_preview(entry):
            return False
        assert entry is not None
        return self.preview_controller.play_pause(entry)

    def rename(self, entry: ReserveEntry | None, new_name: str) -> tuple[bool, str | None]:
        """Renomme le sample via le sample_store.

        Retourne (True, None) en cas de succes, (False, message_erreur) sinon.
        Prefere rename(id, name) si le sample est indexe, sinon rename_by_path().
        """
        if not self.can_rename(entry):
            return False, "Renommage indisponible"
        assert entry is not None
        result = self.mutations.rename(entry, new_name)
        return result.success, (None if result.success else result.message or "Renommage impossible")

    def reveal_in_folder(self, entry: ReserveEntry | None) -> bool:
        if not self.can_reveal_in_folder(entry):
            return False
        assert entry is not None
        folder = os.path.dirname(entry.path)
        if not folder:
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        return True

    def open_waveform(self, entry: ReserveEntry | None) -> bool:
        if not self.can_open_waveform(entry):
            return False
        self.waveformRequested.emit(entry)
        return True

    def send_to_lab(self, entry: ReserveEntry | None) -> bool:
        if not self.can_send_to_lab(entry):
            return False
        assert entry is not None
        self.sendToLabRequested.emit([entry.path])
        return True

    @staticmethod
    def _duration_for_entry(entry: ReserveEntry) -> float:
        """Retourne la duree du sample : depuis l'entree si connue, sinon depuis les metadonnees audio."""
        duration = float(entry.duration or 0.0)
        if duration > 0:
            return duration
        try:
            return float(get_audio_duration(entry.path))
        except Exception:
            return 0.0
