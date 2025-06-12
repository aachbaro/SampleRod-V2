# /backend/settings_gui/retro_recording_settings.py

from PyQt6.QtWidgets import (
    QWidget, QLabel, QSpinBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QCheckBox
)
from PyQt6.QtCore import pyqtSignal
from backend.services.settings_service import SettingsService

import logging
logger = logging.getLogger("retro_recording")

class RetroRecordingWidget(QWidget):
    retroRecordingUpdated = pyqtSignal()

    def __init__(self, settingsService: SettingsService, parent=None):
        super().__init__(parent)
        self.settingsService = settingsService

        # 1) Construire l'UI
        self.init_ui()

        # 2) Initialiser l'état des contrôles à partir du service
        self.toggle_checkbox.setChecked(
            self.settingsService.isRetroEnabled()
        )
        self.duration_input.setValue(
            self.settingsService.getPreSeconds()
        )

        # 3) Connecter les signaux pour les mises à jour ultérieures
        self.settingsService.retroToggled.connect(
            self.toggle_checkbox.setChecked
        )
        self.settingsService.preSecondsChanged.connect(
            self.duration_input.setValue
        )

        self.settingsService.retroToggled.connect(self.toggle_checkbox.setChecked)
        self.settingsService.preSecondsChanged.connect(self.duration_input.setValue)
        self.toggle_checkbox.setChecked(self.settingsService.isRetroEnabled())
        self.duration_input.setValue(self.settingsService.getPreSeconds())
        logger.info("[RetroRecording] Initialisation")

    def init_ui(self):
        layout = QVBoxLayout()

        # → Titre
        top_layout = QHBoxLayout()
        self.title_label = QLabel("Enregistrement Rétroactif")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()

        # → Configuration de la durée
        settings_layout = QHBoxLayout()
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 60)
        self.duration_input.setSuffix(" sec")
        self.duration_input.valueChanged.connect(self.on_duration_change)

        self.confirm_button = QPushButton("OK")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.save_duration)

        settings_layout.addWidget(QLabel("Durée max :"))
        settings_layout.addWidget(self.duration_input)
        settings_layout.addWidget(self.confirm_button)

        # → Activation
        self.toggle_checkbox = QCheckBox("Activer")
        self.toggle_checkbox.clicked.connect(self.toggle_recording)

        # → Assemblage
        layout.addLayout(top_layout)
        layout.addLayout(settings_layout)
        layout.addWidget(self.toggle_checkbox)
        layout.addStretch()
        self.setLayout(layout)

    def on_duration_change(self, value):
        self.confirm_button.setEnabled(True)

    def save_duration(self):
        # Informe le service (persistance + signal)
        self.settingsService.setPreSeconds(self.duration_input.value())
        logger.info(f"[RetroRecording] Durée enregistrée : {self.duration_input.value()}s")
        self.confirm_button.setEnabled(False)

    def toggle_recording(self):
        # Informe le service (persistance + signal)
        self.settingsService.toggleRetro()
        state = 'activé' if self.toggle_checkbox.isChecked() else 'désactivé'
        logger.info(f"[RetroRecording] Rétro-enregistrement {state}")
        # On peut aussi émettre un signal local si besoin
        self.retroRecordingUpdated.emit()