from PyQt6.QtWidgets import (
    QWidget, QLabel, QComboBox, QPushButton, QFormLayout, QVBoxLayout, QHBoxLayout, QMessageBox, QCheckBox, QSpinBox
)
from PyQt6.QtCore import pyqtSignal
import sounddevice as sd

from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext
import soundcard as sc


class AudioSettingsWidget(QWidget):
    """
    Un widget de paramètres audio : sample rate, micro en loopback, etc.
    """
    sampleRateChanged     = pyqtSignal(int)
    loopbackDeviceChanged = pyqtSignal(object)

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = app_context.settings



        self._build_ui()
        self.loopbackDeviceChanged.connect(self.settings.setLoopbackDevice)
        self.settings.autoNormalizeToggled.connect(self.auto_norm_checkbox.setChecked)
        self.settings.normalizationLevelChanged.connect(self.lufs_spin.setValue)
        self._load_settings()

    def _build_ui(self):
        """
        Initialise l’interface des paramètres audio.
        Création des widgets en premier, puis assemblage des layouts à la fin.
        """

        # ─── Création des widgets (sans encore les ajouter aux layouts) ───

        # Sample Rate
        self.sample_rate_combo = QComboBox()
        for rate in [44100, 48000, 96000, 192000]:
            self.sample_rate_combo.addItem(f"{rate} Hz", rate)
        self.sample_rate_combo.currentIndexChanged.connect(self._on_sample_rate_changed)

        # Loopback device
        self.loopback_combo = QComboBox()
        self.refresh_button = QPushButton("Rafraîchir")
        self.refresh_button.clicked.connect(self._load_settings)

        # Bouton Appliquer / Sauvegarder
        self.apply_btn = QPushButton("Sauvegarder")
        self.apply_btn.clicked.connect(self._save_settings)

        # Normalisation automatique
        self.auto_norm_checkbox = QCheckBox("Normalisation automatique")
        self.auto_norm_checkbox.setChecked(self.settings.isAutoNormalizeEnabled())
        self.auto_norm_checkbox.clicked.connect(self.settings.toggleAutoNormalize)

        # Cible LUFS
        self.lufs_spin = QSpinBox()
        self.lufs_spin.setRange(-30, 0)
        self.lufs_spin.setSuffix(" LUFS")
        self.lufs_spin.setValue(self.settings.getNormalizationLevel())
        self.lufs_spin.valueChanged.connect(self.settings.setNormalizationLevel)

        # ─── Assemblage des layouts (addWidget / addLayout) ───
        main_layout = QVBoxLayout(self)

        # Formulaire principal
        form = QFormLayout()

        # Ligne Sample Rate
        form.addRow(QLabel("Sample Rate :"), self.sample_rate_combo)

        # Ligne Loopback device (HBox contenant combobox + bouton)
        hb = QHBoxLayout()
        hb.addWidget(self.loopback_combo)
        hb.addWidget(self.refresh_button)
        form.addRow(QLabel("Micro Loopback :"), hb)

        # Ligne Normalisation automatique
        form.addRow(QLabel("Normalisation :"), self.auto_norm_checkbox)

        # Ligne Cible LUFS
        form.addRow(QLabel("Cible LUFS :"), self.lufs_spin)

        # Ajout du formulaire au layout principal
        main_layout.addLayout(form)

        # Bouton Appliquer / Sauvegarder en-dessous du formulaire
        main_layout.addWidget(self.apply_btn)

        # Connexion pour recharger les devices lorsque le loopback change
        self.settings.loopbackDeviceChanged.connect(lambda dev: self._load_settings())

    def _load_settings(self):
        # Charger sample rate
        cur_rate = getattr(self.settings, 'sample_rate', None)
        if cur_rate:
            idx = self.sample_rate_combo.findData(cur_rate)
            if idx >= 0:
                self.sample_rate_combo.setCurrentIndex(idx)

        # Charger loopback devices
        mics = self._populate_loopback_devices()
        cur_dev = getattr(self.settings, 'loopback_device', None)
        if cur_dev:
            for i, mic in enumerate(mics):
                if mic.name == cur_dev.name:
                    self.loopback_combo.setCurrentIndex(i)
                    break

    def _populate_loopback_devices(self):
        """Remplit la combo et retourne la liste des devices."""
        try:
            mics = sc.all_microphones(include_loopback=True)
            self.loopback_combo.clear()
            for mic in mics:
                self.loopback_combo.addItem(mic.name, mic)
            return mics
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de lister les devices loopback :\n{e}")
            self.loopback_combo.clear()
            self.loopback_combo.addItem("Aucun device trouvé", None)
            return []

    def _on_sample_rate_changed(self, index):
        rate = self.sample_rate_combo.itemData(index)
        if rate:
            self.sampleRateChanged.emit(rate)

    def _save_settings(self):
        # Sample rate
        rate = self.sample_rate_combo.currentData()
        if rate:
            # persiste et émet sampleRateChanged
            self.settings.setSampleRate(rate)

        # Loopback
        dev = self.loopback_combo.currentData()
        if dev is not None:
            # persiste et émet loopbackDeviceChanged
            self.settings.setLoopbackDevice(dev)