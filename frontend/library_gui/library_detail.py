# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Panneau de detail affiché à droite du tableau de la Bibliothèque.
# - Quand l'utilisateur clique sur un sample dans le tableau, ce widget
#   affiche : nom, statut, chemin, metadonnees, et une SampleCard complete
#   (avec lecture, waveform, renommage).
#
# FONCTIONS (sommaire)
# - LibraryDetailWidget        : widget principal
# - set_sample()               : affiche les infos du sample selectionne
# - clear_sample()             : remet le panneau a vide
# - open_current_folder()      : ouvre le dossier du sample dans l'explorateur
# - toggle_waveform()          : ouvre la waveform dans le Labo
# - current_card()             : expose la SampleCard integree pour les raccourcis
# - clear_current_card()       : detruit proprement la SampleCard precedente
# - _format_scale_text()       : formate le texte de gamme detectee
#
# LIENS CLES
# - frontend/library_gui/library_widget.py  : appelant principal
# - frontend/reserve/reserve_entry.py       : type ReserveEntry
# - frontend/sample_gui/sample/sample_card.py : widget de carte integre
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    apply_status_badge,
    format_reserve_date,
    format_reserve_duration,
    format_reserve_rms,
)
from frontend.sample_gui.sample.sample_card import SampleCard


class _ElidedLabel(QLabel):
    """Label d'une seule ligne, elide a droite, texte complet en tooltip.

    Evite qu'un chemin long fasse grossir la bande de detail en hauteur.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(24, self.width()))
        )


class LibraryDetailWidget(QWidget):
    """Panneau de detail pour un sample indexe.

    Affiche : titre, badge de statut, chemin, metadonnees (racine, dossier,
    duree, RMS, gamme detectee), et une SampleCard interactive intégree.
    Se remet a vide quand aucun sample n'est selectionne (clear_sample()).
    """

    def __init__(self, app_context, reserve_actions: ReserveActions | None = None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.sample_store = self.app_context.sample_store
        self.reserve_actions = reserve_actions
        self._current_sample_id: int | None = None
        self._current_entry: ReserveEntry | None = None
        self._current_card: SampleCard | None = None
        self._build_ui()

    def _build_ui(self):
        """Bande compacte : une ligne d'identite, une ligne d'infos, la carte.

        Pas de boutons d'action : « ouvrir le dossier » et « ouvrir dans la
        waveform » sont deja dans le menu contextuel de la table (et le
        double-clic ouvre la waveform). Les metadonnees tiennent sur une seule
        ligne elidee — l'essentiel est deja dans les colonnes de la liste.
        """
        self.setObjectName("LibraryDetailPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        identity_row = QHBoxLayout()
        identity_row.setContentsMargins(0, 0, 0, 0)
        identity_row.setSpacing(8)

        self.title_label = QLabel("Aucun sample selectionne")
        self.title_label.setObjectName("LibrarySectionTitle")

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("LibraryDetailStatus")

        identity_row.addWidget(self.title_label)
        identity_row.addWidget(self.status_badge)
        identity_row.addStretch(1)

        # Chemin et metadonnees : une ligne chacun, elidees a la largeur du
        # panneau, avec le contenu complet en tooltip.
        self.path_label = _ElidedLabel("Selectionne un sample pour afficher son detail.")
        self.path_label.setObjectName("LibraryDetailPath")

        self.meta_label = _ElidedLabel("")
        self.meta_label.setObjectName("LibraryDetailMeta")

        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

        layout.addLayout(identity_row)
        layout.addWidget(self.path_label)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.card_container)
        layout.addStretch(1)

        self.clear_sample()

    def set_sample(self, sample, entry: ReserveEntry, library_service):
        """Affiche les informations du sample selectionne.

        Detruit la carte precedente, recrée une SampleCard pour le nouveau
        sample, masque les boutons non pertinents ici (archive, delete,
        normaliser, concat) et adapte l'interactivite selon si le fichier
        est manquant.
        """
        self.clear_current_card()
        self._current_sample_id = int(sample.id)
        self._current_entry = entry
        self.title_label.setText(entry.display_name)
        apply_status_badge(self.status_badge, entry.status)
        self.path_label.set_full_text(entry.path)
        scale_text = self._format_scale_text(entry)
        self.meta_label.set_full_text(
            " | ".join(
                part
                for part in [
                    f"Racine: {library_service.get_root_label(sample)}",
                    f"Dossier: {library_service.get_folder_label(sample)}",
                    (
                        f"Date: {format_reserve_date(sample.created_at)}"
                        if getattr(sample, "created_at", None) is not None
                        else ""
                    ),
                    f"Duree: {format_reserve_duration(sample.duration, compact=True)}",
                    f"RMS: {format_reserve_rms(sample.rms_level)}" if getattr(sample, "rms_level", None) is not None else "",
                    scale_text,
                    f"Source: {entry.source_label}",
                ]
                if part
            )
        )
        card = SampleCard(sample, self.app_context)
        self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
        self.sample_store.sampleMoved.connect(card.onMoveSuccess)
        card.renameSample.connect(lambda _sid, name: self.app_context.reserve_mutations.rename(entry, name))
        card.sampleMoved.connect(lambda _sid, folder: self.app_context.reserve_mutations.move(entry, folder))
        card.deleteSample.connect(lambda _sid: self.app_context.reserve_mutations.delete_file_and_record(entry))
        card.removeFromHistory.connect(lambda _sid: self.app_context.reserve_mutations.unindex(entry))

        card.checkbox.hide()
        card.archive_button.hide()
        card.delete_button.hide()
        card.normalize_button.hide()
        card.concat_button.hide()
        card.concat_cancel_button.hide()
        card.change_dir_combobox.hide()
        card.set_external_waveform_handler(
            lambda _sample=None, current_entry=entry: (
                self.reserve_actions.open_waveform(current_entry)
                if self.reserve_actions is not None
                else None
            )
        )
        card.waveform_button.hide()

        missing = bool(getattr(sample, "missing", False))
        card.play_button.setEnabled(not missing)
        card.playback_slider.setEnabled(not missing)
        card.waveform_button.setEnabled(not missing)
        if missing:
            card.name_label.setToolTip("Renommage indisponible: fichier manquant")
            card.name_label.mouseDoubleClickEvent = lambda _event: None  # type: ignore[assignment]
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            card.name_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_layout.addWidget(card)
        self._current_card = card

    def clear_sample(self):
        """Remet le panneau a son etat vide (aucun sample selectionne)."""
        self._current_sample_id = None
        self._current_entry = None
        self.title_label.setText("Aucun sample selectionne")
        self.status_badge.setText("")
        self.status_badge.setStyleSheet("")
        self.path_label.set_full_text("Selectionne un sample pour l'ecouter ici.")
        self.meta_label.set_full_text("")
        self.clear_current_card()

    def open_current_folder(self):
        """Ouvre le dossier du sample dans l'explorateur du systeme.

        Si des reserve_actions sont disponibles, délègue à reveal_in_folder().
        Sinon utilise QDesktopServices pour un accès direct sans dependance.
        """
        if self._current_entry is None:
            return
        if self.reserve_actions is not None:
            self.reserve_actions.reveal_in_folder(self._current_entry)
            return
        folder = os.path.dirname(self._current_entry.path)
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def toggle_waveform(self):
        """Ouvre la waveform du sample courant dans le Labo (via open_waveform)."""
        if self._current_entry is not None and self.reserve_actions is not None:
            self.reserve_actions.open_waveform(self._current_entry)

    def current_sample_id(self) -> int | None:
        return self._current_sample_id

    def current_entry(self) -> ReserveEntry | None:
        return self._current_entry

    def current_card(self) -> SampleCard | None:
        return self._current_card

    def clear_current_card(self):
        """Detruit proprement la SampleCard en cours (arrete l'audio, supprime le widget).

        Appele avant chaque changement de sample pour eviter les fuites memoire
        et les timers orphelins de l'ancien widget.
        """
        if self._current_card is None:
            return
        try:
            if self._current_card.wave_edition_widget:
                self._current_card.wave_edition_widget.stop_audio()
                self._current_card.wave_edition_widget.timer.stop()
        except Exception:
            pass
        self.card_layout.removeWidget(self._current_card)
        self._current_card.deleteLater()
        self._current_card = None

    @staticmethod
    def _format_scale_text(entry: ReserveEntry) -> str:
        """Retourne une chaine lisible pour la gamme detectee du sample.

        Exemples : "Gamme: D Minor (82%)", "Note dominante: A", ou "" si inconnu.
        """
        label = str(entry.detected_scale_label or "").strip()
        confidence = (
            f" ({float(entry.scale_confidence):.0%})"
            if entry.scale_confidence is not None
            else ""
        )
        if label:
            prefix = "Gamme" if entry.detected_scale_kind == "scale" else "Note dominante"
            return f"{prefix}: {label}{confidence}"
        if entry.dominant_note:
            return f"Note dominante: {entry.dominant_note}{confidence}"
        return ""
