"""Reglages compacts du buffer de retro-enregistrement."""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from backend.services.settings_service import SettingsService

logger = logging.getLogger("retro_recording")


class RetroRecordingWidget(QWidget):
    retroRecordingUpdated = Signal()

    def __init__(self, settingsService: SettingsService, parent=None):
        super().__init__(parent)
        self.settingsService = settingsService
        self._build_ui()
        self._load_state()
        self.settingsService.retroToggled.connect(self.toggle_checkbox.setChecked)
        self.settingsService.preSecondsChanged.connect(self._on_service_duration)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.toggle_checkbox = QCheckBox("Activer le buffer rétro")
        self.toggle_checkbox.clicked.connect(self.toggle_recording)
        layout.addWidget(self.toggle_checkbox)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        duration_row = QHBoxLayout()
        duration_row.setContentsMargins(0, 0, 0, 0)
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 60)
        self.duration_input.setSuffix(" s")
        self.duration_input.valueChanged.connect(self.on_duration_change)
        duration_row.addWidget(self.duration_input, 1)
        self.confirm_button = QPushButton("Appliquer")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.save_duration)
        duration_row.addWidget(self.confirm_button)
        form.addRow("Buffer maximal", duration_row)
        layout.addLayout(form)

        hint = QLabel("Dans REC : utilise la molette pour choisir la durée de la prochaine prise.")
        hint.setObjectName("SettingsDesc")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _load_state(self) -> None:
        self.toggle_checkbox.setChecked(self.settingsService.isRetroEnabled())
        self.duration_input.blockSignals(True)
        self.duration_input.setValue(self.settingsService.getPreSeconds())
        self.duration_input.blockSignals(False)

    def _on_service_duration(self, value: int) -> None:
        self.duration_input.blockSignals(True)
        self.duration_input.setValue(int(value))
        self.duration_input.blockSignals(False)
        self.confirm_button.setEnabled(False)

    def on_duration_change(self, _value: int) -> None:
        self.confirm_button.setEnabled(True)

    def save_duration(self) -> None:
        value = self.duration_input.value()
        self.settingsService.setPreSeconds(value)
        self.confirm_button.setEnabled(False)
        logger.info("[RetroRecording] Duree enregistree : %ss", value)

    def toggle_recording(self) -> None:
        self.settingsService.toggleRetro()
        self.retroRecordingUpdated.emit()
