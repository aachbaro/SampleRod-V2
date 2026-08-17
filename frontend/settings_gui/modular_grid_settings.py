# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres "Atelier modulaire" : taille du quadrillage affiche et
#   utilise pour remettre en ordre les geometries existantes.
#
# POURQUOI UN MULTIPLICATEUR ET PAS UNE TAILLE LIBRE
# - Le quadrillage doit rester un MULTIPLE du pas de magnetisme. Une taille
#   libre (20 px face a un snap de 8) tracerait des lignes la ou aucune fenetre
#   ne s'accroche : un reperage qui ment est pire que pas de reperage.
# - On propose donc x1, x2, x4, x8, en affichant la taille obtenue.
#
# LIENS CLES
# - frontend/modular/backdrop.py       : le rendu du quadrillage
# - frontend/modular/window_manager.py : applique la densite au fond
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from frontend.modular.backdrop import GRID_MULTIPLIERS, display_step_px

logger = logging.getLogger("modular_grid_settings")

MULTIPLIER_KEY = "modular_grid_multiplier_v1"
DEFAULT_MULTIPLIER = 4


def load_grid_multiplier() -> int:
    """Multiplicateur enregistre, ramene a une valeur proposee."""
    raw = QSettings("SampleRod", "Main").value(
        MULTIPLIER_KEY, DEFAULT_MULTIPLIER, type=int
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MULTIPLIER
    return value if value in GRID_MULTIPLIERS else DEFAULT_MULTIPLIER


def save_grid_multiplier(multiplier: int) -> None:
    QSettings("SampleRod", "Main").setValue(MULTIPLIER_KEY, int(multiplier))


class ModularGridSettingsWidget(QWidget):
    """Densite du quadrillage de l'atelier modulaire."""

    multiplierChanged = Signal(int)

    def __init__(self, window_manager=None, parent=None):
        super().__init__(parent)
        self._wm = window_manager
        self._build_ui()
        self._load()
        logger.info("[ModularGridSettings] Initialisation")

    def _snap_px(self) -> int:
        """Pas du magnetisme, source de verite pour les tailles proposees."""
        if self._wm is None:
            return 8
        try:
            return int(self._wm.layout_manager.settings.grid_px)
        except Exception:
            return 8

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form = QFormLayout()
        self.density_combo = QComboBox()
        snap = self._snap_px()
        for multiplier in GRID_MULTIPLIERS:
            step = display_step_px(snap, multiplier)
            label = f"{step} px" if multiplier > 1 else f"{step} px (chaque pas)"
            self.density_combo.addItem(label, multiplier)
        self.density_combo.currentIndexChanged.connect(self._on_changed)
        form.addRow(QLabel("Espacement du quadrillage :"), self.density_combo)
        layout.addLayout(form)

        hint = QLabel(
            f"Le quadrillage reste un multiple du pas de magnetisme ({snap} px) : "
            "changer sa taille recale la position et les quatre contours des "
            "fenetres sur les lignes.\n"
            "Il s'affiche sur le fond global, via le bouton grille de "
            "l'orchestrateur."
        )
        hint.setWordWrap(True)
        hint.setObjectName("SettingsDesc")
        layout.addWidget(hint)

    def _load(self) -> None:
        multiplier = load_grid_multiplier()
        index = self.density_combo.findData(multiplier)
        if index >= 0:
            self.density_combo.blockSignals(True)
            self.density_combo.setCurrentIndex(index)
            self.density_combo.blockSignals(False)

    def _on_changed(self, *_args) -> None:
        multiplier = int(self.density_combo.currentData() or DEFAULT_MULTIPLIER)
        save_grid_multiplier(multiplier)
        if self._wm is not None:
            # Effet immediat : inutile de rouvrir l'atelier pour voir le
            # resultat d'un reglage visuel.
            try:
                self._wm.set_grid_overlay_multiplier(multiplier)
            except Exception:
                logger.exception("Application de la densite de grille impossible")
        self.multiplierChanged.emit(multiplier)
