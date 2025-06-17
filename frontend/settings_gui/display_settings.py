from PyQt6.QtWidgets import (
    QWidget, QLabel, QComboBox, QFormLayout, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal
from backend.services.settings_service import SettingsService

import logging
logger = logging.getLogger("display_settings")

class DisplaySettingsWidget(QWidget):
    """Widget pour configurer l'affichage des samples."""
    samplesPerPageChanged = pyqtSignal(int)

    def __init__(self, settings: SettingsService, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self.settings.samplesPerPageChanged.connect(
            self._on_service_changed
        )
        self._load_settings()
        logger.info("[DisplaySettings] Initialisation")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.samples_combo = QComboBox()
        for n in [10, 20, 50, 100]:
            self.samples_combo.addItem(str(n), n)
        self.samples_combo.currentIndexChanged.connect(self._on_combo_changed)
        form.addRow(QLabel("Samples par page :"), self.samples_combo)
        layout.addLayout(form)
        layout.addStretch()

    def _load_settings(self):
        count = self.settings.getSamplesPerPage()
        idx = self.samples_combo.findData(count)
        if idx >= 0:
            self.samples_combo.setCurrentIndex(idx)

    def _on_combo_changed(self, index):
        value = self.samples_combo.itemData(index)
        if value is not None:
            self.settings.setSamplesPerPage(value)
            self.samplesPerPageChanged.emit(value)

    def _on_service_changed(self, value: int):
        idx = self.samples_combo.findData(value)
        if idx >= 0:
            self.samples_combo.setCurrentIndex(idx)

