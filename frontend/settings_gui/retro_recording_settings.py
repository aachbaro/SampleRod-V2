# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres du retro-enregistrement.
# - Permet de regler duree du buffer et activation globale.
#
# LIENS CLES
# - backend/services/settings_service.py
# - backend/services/recorder_service.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/retro_recording_settings.py

# /backend/settings_gui/retro_recording_settings.py

from PySide6.QtWidgets import (
    QWidget, QLabel, QSpinBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QCheckBox
)
from PySide6.QtCore import Signal
from backend.services.settings_service import SettingsService

import logging
logger = logging.getLogger("retro_recording")

class RetroRecordingWidget(QWidget):
    retroRecordingUpdated = Signal()

    def __init__(self, settingsService: SettingsService, parent=None):
        super().__init__(parent)
        self.settingsService = settingsService

        # 1) Construire l'UI
        self.init_ui()

        # 2) Initialiser l'ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©tat des contrÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â´les ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â  partir du service
        self.toggle_checkbox.setChecked(
            self.settingsService.isRetroEnabled()
        )
        self.duration_input.setValue(
            self.settingsService.getPreSeconds()
        )

        # 3) Connecter les signaux pour les mises ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â  jour ultÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©rieures
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

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ Titre
        top_layout = QHBoxLayout()
        self.title_label = QLabel("Enregistrement RÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©troactif")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ Configuration de la durÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©e
        settings_layout = QHBoxLayout()
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 60)
        self.duration_input.setSuffix(" sec")
        self.duration_input.valueChanged.connect(self.on_duration_change)

        self.confirm_button = QPushButton("OK")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.save_duration)

        settings_layout.addWidget(QLabel("DurÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©e max :"))
        settings_layout.addWidget(self.duration_input)
        settings_layout.addWidget(self.confirm_button)

        # Activation
        self.toggle_checkbox = QCheckBox("Activer")
        self.toggle_checkbox.clicked.connect(self.toggle_recording)

        self.help_label = QLabel(
            "Astuce widget REC : clic droit pour activer/desactiver le retro, "
            "puis molette sur REC pour choisir le retro time applique a la prochaine prise "
            "(entre 0 et la duree max ci-dessus)."
        )
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet("color: #8d95a3; font-size: 11px;")

        layout.addLayout(top_layout)
        layout.addLayout(settings_layout)
        layout.addWidget(self.toggle_checkbox)
        layout.addWidget(self.help_label)
        layout.addStretch()
        self.setLayout(layout)

    def on_duration_change(self, value):
        self.confirm_button.setEnabled(True)

    def save_duration(self):
        # Informe le service (persistance + signal)
        self.settingsService.setPreSeconds(self.duration_input.value())
        logger.info(f"[RetroRecording] DurÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©e enregistrÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©e : {self.duration_input.value()}s")
        self.confirm_button.setEnabled(False)

    def toggle_recording(self):
        # Informe le service (persistance + signal)
        self.settingsService.toggleRetro()
        state = 'activÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©' if self.toggle_checkbox.isChecked() else 'dÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©sactivÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©'
        logger.info(f"[RetroRecording] RÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©tro-enregistrement {state}")
        # On peut aussi ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©mettre un signal local si besoin
        self.retroRecordingUpdated.emit()