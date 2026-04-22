from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from frontend.reserve import ReserveActions, ReserveEntry, apply_status_badge
from frontend.sample_gui.wave_form import WaveformWidget


class DirectoryDetailWidget(QWidget):
    """Detail/preview pane for the currently selected filesystem audio file."""

    previewRequested = Signal(str)
    renameRequested = Signal(str)
    addToComposerRequested = Signal(str)

    def __init__(self, app_context, reserve_actions: ReserveActions | None = None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.reserve_actions = reserve_actions
        self._entry: ReserveEntry | None = None
        self._waveform_widget: WaveformWidget | None = None
        self._waveform_visible = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("DirectoryDetailPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.section_label = QLabel("Detail")
        self.section_label.setObjectName("DirectorySectionTitle")

        self.title_label = QLabel("Aucun fichier selectionne")
        self.title_label.setObjectName("DirectoryDetailTitle")
        self.title_label.setWordWrap(True)

        self.status_label = QLabel("")
        self.status_label.setObjectName("DirectoryDetailStatus")

        self.path_label = QLabel("Selectionne un fichier audio pour afficher son detail.")
        self.path_label.setObjectName("DirectoryDetailPath")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("DirectoryDetailMeta")
        self.meta_label.setWordWrap(True)

        self.preview_button = QPushButton("Pre-ecouter")
        self.preview_button.clicked.connect(self._request_preview)

        self.rename_button = QPushButton("Renommer")
        self.rename_button.clicked.connect(self._request_rename)

        self.waveform_button = QPushButton("Ouvrir dans le labo")
        self.waveform_button.clicked.connect(self._request_waveform)

        self.add_to_composer_button = QPushButton("Envoyer au labo")
        self.add_to_composer_button.clicked.connect(self._request_add_to_composer)

        self.open_folder_button = QPushButton("Ouvrir le dossier")
        self.open_folder_button.clicked.connect(self._open_current_folder)

        self.waveform_container = QWidget()
        self.waveform_layout = QVBoxLayout(self.waveform_container)
        self.waveform_layout.setContentsMargins(0, 0, 0, 0)
        self.waveform_layout.setSpacing(0)
        self.waveform_container.setVisible(False)

        layout.addWidget(self.section_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.rename_button)
        layout.addWidget(self.waveform_button)
        layout.addWidget(self.add_to_composer_button)
        layout.addWidget(self.open_folder_button)
        layout.addWidget(self.waveform_container, 1)

        self.clear_entry()

    def set_entry(self, entry: ReserveEntry) -> None:
        same_path = self._entry is not None and self._entry.path == entry.path
        self._entry = entry
        self.title_label.setText(entry.display_name or os.path.basename(entry.path))
        apply_status_badge(self.status_label, entry.status)
        self.path_label.setText(entry.path)
        self.meta_label.setText(self._format_metadata(entry))

        actions = self.reserve_actions
        enabled = os.path.isfile(entry.path) and not entry.missing
        self.preview_button.setEnabled(actions.can_preview(entry) if actions else enabled)
        self.rename_button.setEnabled(actions.can_rename(entry) if actions else enabled)
        self.waveform_button.setEnabled(actions.can_open_waveform(entry) if actions else enabled)
        self.add_to_composer_button.setEnabled(actions.can_send_to_lab(entry) if actions else enabled)
        self.open_folder_button.setEnabled(actions.can_reveal_in_folder(entry) if actions else bool(entry.path))

        if not same_path:
            self._destroy_waveform()
            self._waveform_visible = False
            self.waveform_button.setText("Ouvrir dans le labo")
            self.waveform_container.setVisible(False)

    def clear_entry(self) -> None:
        self._entry = None
        self.title_label.setText("Aucun fichier selectionne")
        self.status_label.setText("")
        self.status_label.setStyleSheet("")
        self.path_label.setText("Selectionne un fichier audio pour afficher son detail.")
        self.meta_label.setText("")
        self.preview_button.setEnabled(False)
        self.rename_button.setEnabled(False)
        self.waveform_button.setEnabled(False)
        self.add_to_composer_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.preview_button.setText("Pre-ecouter")
        self.waveform_button.setText("Ouvrir dans le labo")
        self._destroy_waveform()
        self._waveform_visible = False
        self.waveform_container.setVisible(False)

    def is_waveform_visible(self) -> bool:
        return bool(self._waveform_visible)

    def set_preview_active(self, active: bool) -> None:
        self.preview_button.setText("Stopper" if active else "Pre-ecouter")

    def toggle_waveform(self, *, force: bool = False) -> None:
        if self._entry is None or not os.path.isfile(self._entry.path):
            return

        self._waveform_visible = True if force else not self._waveform_visible
        if self._waveform_visible:
            if self._waveform_widget is None:
                self._waveform_widget = WaveformWidget(self._entry.path, self.app_context)
                self.waveform_layout.addWidget(self._waveform_widget)
            self.waveform_container.setVisible(True)
            self.waveform_button.setText("Masquer la waveform")
            return

        self.waveform_container.setVisible(False)
        self.waveform_button.setText("Ouvrir dans le labo")

    def _request_preview(self) -> None:
        if self._entry is not None:
            if self.reserve_actions is not None:
                self.reserve_actions.preview(self._entry)
            else:
                self.previewRequested.emit(self._entry.path)

    def _request_rename(self) -> None:
        if self._entry is not None:
            self.renameRequested.emit(self._entry.path)

    def _request_waveform(self) -> None:
        if self._entry is None:
            return
        if self._waveform_visible:
            self.toggle_waveform()
            return
        if self.reserve_actions is not None:
            self.reserve_actions.open_waveform(self._entry)
            return
        self.toggle_waveform()

    def _request_add_to_composer(self) -> None:
        if self._entry is not None:
            if self.reserve_actions is not None:
                self.reserve_actions.send_to_lab(self._entry)
            else:
                self.addToComposerRequested.emit(self._entry.path)

    def _open_current_folder(self) -> None:
        if self._entry is None:
            return
        if self.reserve_actions is not None:
            self.reserve_actions.reveal_in_folder(self._entry)
            return
        folder = os.path.dirname(self._entry.path)
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _destroy_waveform(self) -> None:
        if self._waveform_widget is None:
            return
        try:
            self._waveform_widget.stop_audio()
        except Exception:
            pass
        try:
            self._waveform_widget.timer.stop()
        except Exception:
            pass
        self.waveform_layout.removeWidget(self._waveform_widget)
        self._waveform_widget.deleteLater()
        self._waveform_widget = None

    @staticmethod
    def _format_metadata(entry: ReserveEntry) -> str:
        parts: list[str] = []
        if entry.duration is not None:
            parts.append(f"Duree: {float(entry.duration):.2f}s")
        if entry.rms_level is not None:
            parts.append(f"RMS: {float(entry.rms_level):.3f}")
        created_at = entry.metadata.get("directory_entry")
        created_at = getattr(created_at, "created_at", None)
        if created_at is not None and hasattr(created_at, "strftime"):
            parts.append(f"Cree: {created_at.strftime('%d/%m/%Y %H:%M')}")
        parts.append("Source: filesystem")
        return " | ".join(parts)
