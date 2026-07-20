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

from PySide6.QtCore import QEvent, QRect, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget

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

    def __init__(self, instance_id: str, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self._instance_id = instance_id
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

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.activated.emit(self._instance_id)
        super().changeEvent(event)
