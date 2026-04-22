from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from frontend.reserve import ReserveActions, ReserveEntry, apply_status_badge
from frontend.sample_gui.sample.sample_card import SampleCard


class LibraryDetailWidget(QWidget):
    """Panneau de detail pour un sample indexe."""

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
        self.setObjectName("LibraryDetailPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.title_label = QLabel("Aucun sample selectionne")
        self.title_label.setObjectName("LibrarySectionTitle")

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("LibraryDetailStatus")

        self.path_label = QLabel("Selectionne un sample pour afficher son detail.")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)

        self.open_folder_button = QPushButton("Ouvrir le dossier source")
        self.open_folder_button.clicked.connect(self.open_current_folder)
        self.open_folder_button.setEnabled(False)

        self.send_to_lab_button = QPushButton("Envoyer au labo")
        self.send_to_lab_button.clicked.connect(self.send_current_to_lab)
        self.send_to_lab_button.setEnabled(False)

        self.toggle_waveform_button = QPushButton("Ouvrir dans le labo")
        self.toggle_waveform_button.clicked.connect(self.toggle_waveform)
        self.toggle_waveform_button.setEnabled(False)

        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

        layout.addWidget(self.title_label)
        layout.addWidget(self.status_badge)
        layout.addWidget(self.path_label)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.open_folder_button)
        layout.addWidget(self.send_to_lab_button)
        layout.addWidget(self.toggle_waveform_button)
        layout.addWidget(self.card_container, 1)

        self.clear_sample()

    def set_sample(self, sample, entry: ReserveEntry, library_service):
        self.clear_current_card()
        self._current_sample_id = int(sample.id)
        self._current_entry = entry
        self.title_label.setText(entry.display_name)
        apply_status_badge(self.status_badge, entry.status)
        self.path_label.setText(entry.path)
        self.meta_label.setText(
            " | ".join(
                part
                for part in [
                    f"Racine: {library_service.get_root_label(sample)}",
                    f"Dossier: {library_service.get_folder_label(sample)}",
                    f"Duree: {library_service.format_duration(sample)}",
                    f"RMS: {library_service.format_rms(sample)}" if getattr(sample, "rms_level", None) is not None else "",
                    f"Source: {entry.source_label}",
                ]
                if part
            )
        )
        self.open_folder_button.setEnabled(True)
        self.send_to_lab_button.setEnabled(not entry.missing and os.path.isfile(entry.path))

        card = SampleCard(sample, self.app_context)
        self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
        self.sample_store.sampleMoved.connect(card.onMoveSuccess)
        card.renameSample.connect(self.sample_store.rename)
        card.sampleMoved.connect(self.sample_store.move)
        card.deleteSample.connect(self.sample_store.delete)
        card.removeFromHistory.connect(self.sample_store.removeFromHistory)

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
        self.toggle_waveform_button.setEnabled(not missing)
        if missing:
            card.name_label.setToolTip("Renommage indisponible: fichier manquant")
            card.name_label.mouseDoubleClickEvent = lambda _event: None  # type: ignore[assignment]
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            card.name_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_layout.addWidget(card)
        self._current_card = card

    def clear_sample(self):
        self._current_sample_id = None
        self._current_entry = None
        self.title_label.setText("Aucun sample selectionne")
        self.status_badge.setText("")
        self.status_badge.setStyleSheet("")
        self.path_label.setText("Selectionne un sample pour afficher son detail.")
        self.meta_label.setText("")
        self.open_folder_button.setEnabled(False)
        self.send_to_lab_button.setEnabled(False)
        self.toggle_waveform_button.setEnabled(False)
        self.clear_current_card()

    def open_current_folder(self):
        if self._current_entry is None:
            return
        if self.reserve_actions is not None:
            self.reserve_actions.reveal_in_folder(self._current_entry)
            return
        folder = os.path.dirname(self._current_entry.path)
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def send_current_to_lab(self):
        if self._current_entry is None:
            return
        if self.reserve_actions is not None:
            self.reserve_actions.send_to_lab(self._current_entry)

    def toggle_waveform(self):
        if self._current_entry is not None and self.reserve_actions is not None:
            self.reserve_actions.open_waveform(self._current_entry)

    def current_sample_id(self) -> int | None:
        return self._current_sample_id

    def current_entry(self) -> ReserveEntry | None:
        return self._current_entry

    def clear_current_card(self):
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
