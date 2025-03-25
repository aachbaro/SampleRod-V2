from PyQt6.QtWidgets import QWidget, QLabel, QSpinBox, QPushButton, QVBoxLayout, QHBoxLayout, QCheckBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, pyqtSignal
from backend.models.User import User

class RetroRecordingWidget(QWidget):
    retroRecordingUpdated = pyqtSignal()

    def __init__(self, user: User, parent=None):
        super().__init__(parent)
        # self.store = store  # Simulation d'un store externe (ex: dict)
        self.user = user

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout()

        # Ligne principale avec icône et titre
        top_layout = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(QIcon("icon.svg").pixmap(24, 24))
        self.title_label = QLabel("Enregistrement Rétroactif")

        top_layout.addWidget(self.icon_label)
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        
        # Zone de configuration
        settings_layout = QHBoxLayout()
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 60)
        self.duration_input.setSuffix(" sec")
        self.duration_input.valueChanged.connect(self.on_duration_change)
        
        self.confirm_button = QPushButton("OK")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.save_duration)
        
        settings_layout.addWidget(QLabel("Durée max:"))
        settings_layout.addWidget(self.duration_input)
        settings_layout.addWidget(self.confirm_button)
        
        # Activation/Désactivation
        self.toggle_checkbox = QCheckBox("Activer")
        self.toggle_checkbox.stateChanged.connect(self.toggle_recording)
        
        # Ajout des layouts
        layout.addLayout(top_layout)
        layout.addLayout(settings_layout)
        layout.addWidget(self.toggle_checkbox)
        layout.addStretch()
        
        self.setLayout(layout)

    def load_settings(self):
        # Charger les valeurs du store
        # self.duration_input.setValue(self.store.get("maxRecordingTime", 10))
        # self.toggle_checkbox.setChecked(self.store.get("retroactiveRecording", False))
        self.duration_input.setValue(0)
        self.toggle_checkbox.setChecked(False)

    
    def on_duration_change(self, value):
        self.confirm_button.setEnabled(True)

    def save_duration(self):
        self.user.settings.set_pre_recording_seconds(self.duration_input.value())
        self.confirm_button.setEnabled(False)

    def toggle_recording(self, state):
        # Désactiver le bouton pendant l'opération
        self.toggle_checkbox.setEnabled(False)

        print("Settings retro recording: Toggle retro recording")
        self.user.settings.set_retro_recording_state(bool(state))
        self.user.settings.retro_recording_enabled = bool(state)

        if self.user.settings.retro_recording_enabled:
            self.user.recorder.bac_rec_activated()
        else:
            self.user.recorder.bac_rec_deactivated()

        # Réactiver le bouton après l'opération
        self.toggle_checkbox.setEnabled(True)

        self.retroRecordingUpdated.emit()