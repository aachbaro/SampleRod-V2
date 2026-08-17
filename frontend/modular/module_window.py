# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre top-level (cadre natif de l'OS : barre de titre, croix, reduction)
#   qui heberge le widget d'une instance de module.
# - Comportements cles :
#   * hide-on-close : la croix MASQUE la fenetre (contenu conserve), elle
#     reapparait depuis la fenetre Workspace ;
#   * focus groupe : signale son activation pour que le WindowManager remonte
#     tout le groupe de fenetres visibles ;
#   * geometrie : sauvegarde/restauration {x,y,w,h} avec securite multi-ecran.
#
# LIENS CLES
# - frontend/modular/window_manager.py : cree et pilote ces fenetres
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QRect, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget

logger = logging.getLogger("module_window")

_MIN_VISIBLE_W = 96
_MIN_VISIBLE_H = 48


def clamp_rect_to_screens(rect: QRect) -> QRect:
    """Ramene un rectangle sur un ecran existant (securite 2e moniteur debranche)."""
    screens = QGuiApplication.screens()
    if not screens:
        return rect
    for screen in screens:
        inter = screen.availableGeometry().intersected(rect)
        if inter.width() >= _MIN_VISIBLE_W and inter.height() >= _MIN_VISIBLE_H:
            return rect
    primary = QGuiApplication.primaryScreen().availableGeometry()
    width = min(rect.width(), primary.width())
    height = min(rect.height(), primary.height())
    x = primary.x() + (primary.width() - width) // 2
    y = primary.y() + (primary.height() - height) // 2
    return QRect(x, y, width, height)


class ModuleWindow(QMainWindow):
    """Fenetre a cadre natif d'une instance de module (hide-on-close)."""

    windowHidden = Signal(str)  # instance_id : la croix a masque la fenetre
    activated = Signal(str)     # instance_id : la fenetre est devenue active
    # La geometrie a change, pour une raison QUELCONQUE (drag en cours,
    # setGeometry programmatique, restauration). Sert a la memoire et a la
    # persistance. Ce n'est PAS une fin de geste : le magnetisme ne doit pas
    # s'y brancher — il ecoutera le cycle d'interaction natif.
    geometryChanged = Signal(str)
    # Cycle du geste utilisateur : saisie puis relachement de la fenetre.
    # SEULE source du magnetisme.
    interactionStarted = Signal(str)
    interactionFinished = Signal(str)

    def __init__(self, instance_id: str, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self._instance_id = instance_id
        # Observateur du geste utilisateur (debut/fin). C'est lui, et lui seul,
        # qui declenchera le magnetisme — jamais geometryChanged.
        # Cree AVANT tout appel qui pourrait declencher move/resizeEvent.
        from .layout.move_lifecycle import create_interaction_watcher

        self._interaction_watcher = create_interaction_watcher(instance_id, self)
        self._interaction_watcher.interactionStarted.connect(self.interactionStarted)
        self._interaction_watcher.interactionFinished.connect(self.interactionFinished)

        self.setObjectName("ModuleWindow")
        self.setWindowTitle(title)
        self.setCentralWidget(content)
        self.resize(900, 560)

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def module_widget(self) -> QWidget:
        return self.centralWidget()

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)

    # -- Geometrie ----------------------------------------------------------
    def current_geometry(self) -> dict:
        geo = self.geometry()
        return {"x": geo.x(), "y": geo.y(), "width": geo.width(), "height": geo.height()}

    def apply_geometry(self, geometry: dict | None) -> None:
        if not geometry:
            return
        try:
            rect = QRect(
                int(geometry["x"]),
                int(geometry["y"]),
                int(geometry["width"]),
                int(geometry["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return
        self.setGeometry(clamp_rect_to_screens(rect))

    # -- Evenements ---------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        # Hide-on-close : on ne detruit pas, on masque (contenu conserve).
        event.ignore()
        self.hide()
        self.windowHidden.emit(self._instance_id)

    def _notify_watcher(self) -> None:
        """Signale un mouvement a l'observateur, s'il existe deja.

        Qt peut emettre un resizeEvent pendant la construction, avant meme que
        l'observateur soit en place : on ne veut pas d'AttributeError pour ca.
        """
        watcher = getattr(self, "_interaction_watcher", None)
        if watcher is not None:
            watcher.on_geometry_event()

    def nativeEvent(self, event_type, message):  # noqa: N802
        """Observation PASSIVE du cycle natif.

        Ne renvoie jamais True de son propre fait, ne modifie jamais le RECT,
        et delegue toujours a super(). Toute exception de l'observateur est
        capturee : nativeEvent est sur un chemin chaud, une erreur qui
        remonterait ici perturberait la fenetre.
        """
        try:
            watcher = getattr(self, "_interaction_watcher", None)
            if watcher is not None:
                watcher.handle_native(event_type, message)
        except Exception:
            logger.exception("Observation du cycle natif impossible")
        return super().nativeEvent(event_type, message)

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self._notify_watcher()
        self.geometryChanged.emit(self._instance_id)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._notify_watcher()
        self.geometryChanged.emit(self._instance_id)

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.activated.emit(self._instance_id)
        super().changeEvent(event)
