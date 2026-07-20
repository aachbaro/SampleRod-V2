# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres Affichage (pagination, densite de liste).
# - Expose les reglages de presentation de la liste de samples.
#
# FONCTIONS (sommaire)
# - DisplaySettingsWidget     : widget de configuration de l'affichage
# - _build_ui()               : formulaire avec combo "Samples par page"
# - _load_settings()          : charge la valeur depuis le service
# - _on_combo_changed()       : persiste et emet samplesPerPageChanged
# - _on_service_changed()     : resynchronise la combo si le service change
#
# LIENS CLES
# - backend/services/settings_service.py
# - frontend/sample_gui/sample/sample_list.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/display_settings.py

from PySide6.QtWidgets import (
    QWidget, QLabel, QComboBox, QFormLayout, QVBoxLayout
)
from PySide6.QtCore import Signal
from backend.services.settings_service import SettingsService

import logging
logger = logging.getLogger("display_settings")

class DisplaySettingsWidget(QWidget):
    """Widget pour configurer l'affichage des samples."""
    samplesPerPageChanged = Signal(int)

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
        """Construit le formulaire: combo Samples par page."""
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
        """Charge la valeur courante depuis le service et met a jour la combo."""
        count = self.settings.getSamplesPerPage()
        idx = self.samples_combo.findData(count)
        if idx >= 0:
            self.samples_combo.setCurrentIndex(idx)

    def _on_combo_changed(self, index):
        """Persiste la nouvelle valeur et emet samplesPerPageChanged."""
        value = self.samples_combo.itemData(index)
        if value is not None:
            self.settings.setSamplesPerPage(value)
            self.samplesPerPageChanged.emit(value)

    def _on_service_changed(self, value: int):
        """Resynchronise la combo si la valeur change via le service (signal externe)."""
        idx = self.samples_combo.findData(value)
        if idx >= 0:
            self.samples_combo.setCurrentIndex(idx)

