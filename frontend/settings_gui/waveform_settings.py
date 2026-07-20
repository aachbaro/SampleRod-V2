# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres Waveform / Decoupage.
# - Regroupe les preferences liees a l'editeur waveform et au Break tab.
#
# OPTIONS ACTUELLES
# - fill_markers_replace: comportement du bouton "propager l'intervalle"
#   (remplacer les marqueurs existants dans la zone vs les conserver).
#
# FONCTIONS (sommaire)
# - WaveformSettingsWidget  : widget de configuration de l'editeur waveform
# - _build_ui()             : checkbox + hint
# - _load()                 : charge la valeur courante sans emettre de signal
# - _on_check_toggled()     : persiste la valeur via le service
# - _on_service_changed()   : resynchronise la checkbox si le service change
#
# LIENS CLES
# - backend/services/settings_service.py
# - frontend/labo/break_widget.py
# -----------------------------------------------------------------------------

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Signal

from backend.services.settings_service import SettingsService

import logging
logger = logging.getLogger("waveform_settings")


class WaveformSettingsWidget(QWidget):
    """Preferences liees a l'editeur waveform et au Break tab."""

    def __init__(self, settings: SettingsService, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self._load()
        self.settings.fillMarkersReplaceChanged.connect(self._on_service_changed)
        logger.info("[WaveformSettings] Initialisation")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.fill_replace_check = QCheckBox(
            "Remplacer les marqueurs existants lors du remplissage"
        )
        self.fill_replace_check.setToolTip(
            "Coche : le bouton Propager efface d'abord tous les marqueurs\n"
            "dans la zone ciblee avant d'en poser de nouveaux.\n\n"
            "Decoches : les marqueurs deja presents sont conserves\n"
            "(seules les positions vides sont remplies)."
        )
        self.fill_replace_check.toggled.connect(self._on_check_toggled)

        hint = QLabel(
            "Concerne le bouton ↦ (Propager l'intervalle) dans l'onglet Decoupage."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8d95a3; font-size: 11px;")

        layout.addWidget(self.fill_replace_check)
        layout.addWidget(hint)
        layout.addStretch()

    def _load(self) -> None:
        """Charge la valeur depuis le service sans declencher _on_check_toggled."""
        self.fill_replace_check.blockSignals(True)
        self.fill_replace_check.setChecked(self.settings.isFillMarkersReplace())
        self.fill_replace_check.blockSignals(False)

    def _on_check_toggled(self, checked: bool) -> None:
        self.settings.setFillMarkersReplace(checked)

    def _on_service_changed(self, value: bool) -> None:
        self.fill_replace_check.blockSignals(True)
        self.fill_replace_check.setChecked(value)
        self.fill_replace_check.blockSignals(False)
