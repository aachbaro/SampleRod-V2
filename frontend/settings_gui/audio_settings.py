# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres Audio (sample rate, loopback, normalisation).
# - Synchronise les choix UI avec SettingsService/RecorderService.
#
# FONCTIONS (sommaire)
# - AudioSettingsWidget       : widget de configuration audio
# - _build_ui()               : formulaire + timer de diagnostic
# - _load_settings()          : charge sample rate + loopback devices
# - _populate_loopback_devices(): remplit la combo des mics loopback
# - _on_sample_rate_changed() : emet sampleRateChanged
# - _save_settings()          : persiste sample rate + loopback
# - _update_worker_status()   : rafraichit le label de diagnostic du worker
#
# LIENS CLES
# - backend/services/settings_service.py
# - backend/services/recorder_service.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/audio_settings.py

from PySide6.QtWidgets import (
    QWidget, QLabel, QComboBox, QPushButton, QFormLayout, QVBoxLayout, QHBoxLayout, QMessageBox, QCheckBox, QSpinBox
)
from PySide6.QtCore import Signal, QTimer
import sounddevice as sd

from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext
import soundcard as sc


import logging
logger = logging.getLogger("audio_settings")

class NoWheelSpinBox(QSpinBox):
    """SpinBox qui ignore la molette pour eviter les changements involontaires."""
    def wheelEvent(self, event):
        event.ignore()

class AudioSettingsWidget(QWidget):
    """
    Un widget de paramètres audio : sample rate, micro en loopback, etc.
    """
    sampleRateChanged     = Signal(int)
    loopbackDeviceChanged = Signal(object)

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = app_context.settings



        self._build_ui()
        self.loopbackDeviceChanged.connect(self.settings.setLoopbackDevice)
        self.settings.autoNormalizeToggled.connect(self.auto_norm_checkbox.setChecked)
        self.settings.normalizationLevelChanged.connect(self.lufs_spin.setValue)
        self._load_settings()
        logger.info("[AudioSettings] Initialisation")

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
        self.lufs_spin = NoWheelSpinBox()
        self.lufs_spin.setRange(-30, 0)
        self.lufs_spin.setSuffix(" LUFS")
        self.lufs_spin.setValue(self.settings.getNormalizationLevel())
        self.lufs_spin.valueChanged.connect(self.settings.setNormalizationLevel)

        # Etat du recorder worker (diagnostic)
        self.worker_status = QLabel("—")
        self.worker_status.setObjectName("RecorderStatusLabel")
        self.worker_detail = QLabel("")
        self.worker_detail.setObjectName("RecorderStatusDetail")
        self.worker_detail.setWordWrap(True)

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

        # Ligne Etat worker
        status_box = QVBoxLayout()
        status_box.setSpacing(2)
        status_box.addWidget(self.worker_status)
        status_box.addWidget(self.worker_detail)
        form.addRow(QLabel("Recorder worker :"), status_box)

        # Ajout du formulaire au layout principal
        main_layout.addLayout(form)

        # Bouton Appliquer / Sauvegarder en-dessous du formulaire
        main_layout.addWidget(self.apply_btn)

        # Connexion pour recharger les devices lorsque le loopback change
        self.settings.loopbackDeviceChanged.connect(lambda dev: self._load_settings())

        # Timer de diagnostic (mise a jour de l'etat worker)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_worker_status)
        self._status_timer.start(1000)
        self._update_worker_status()

    def _load_settings(self):
        """Charge le sample rate courant et rafraichit la liste des mics loopback."""
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
        logger.info("[AudioSettings] Paramètres chargés")

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
        """Emet sampleRateChanged quand l'utilisateur change le sample rate."""
        rate = self.sample_rate_combo.itemData(index)
        if rate:
            self.sampleRateChanged.emit(rate)
            logger.info(f"[AudioSettings] Sample rate sélectionné : {rate}")

    def _save_settings(self):
        """Persiste le sample rate et le device loopback via SettingsService."""
        # Sample rate
        rate = self.sample_rate_combo.currentData()
        if rate:
            # persiste et émet sampleRateChanged
            self.settings.setSampleRate(rate)
            logger.info(f"[AudioSettings] Sample rate enregistré : {rate}")

        # Loopback
        dev = self.loopback_combo.currentData()
        if dev is not None:
            # persiste et émet loopbackDeviceChanged
            self.settings.setLoopbackDevice(dev)
            logger.info(f"[AudioSettings] Loopback sélectionné : {dev.name if dev else 'None'}")

    def _update_worker_status(self):
        """Affiche l'etat du worker d'enregistrement pour debug."""
        rec = getattr(self.app_context, "recorder", None)
        if rec is None or getattr(rec, "worker", None) is None:
            self.worker_status.setText("KO")
            self.worker_status.setStyleSheet("color:#d77a7a;")
            self.worker_detail.setText("Worker non initialisé.")
            return

        alive = rec.worker.is_alive()
        exitcode = rec.worker.exitcode
        if alive:
            self.worker_status.setText("OK")
            self.worker_status.setStyleSheet("color:#9bd18f;")
            self.worker_detail.setText("Worker actif.")
        else:
            self.worker_status.setText("KO")
            self.worker_status.setStyleSheet("color:#d77a7a;")
            detail = "Worker arrêté."
            if exitcode is not None:
                detail += f" (exitcode={exitcode})"
            self.worker_detail.setText(detail)
