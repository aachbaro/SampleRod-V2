# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre top-level qui heberge le widget d'une instance de module.
# - Comportements cles :
#   * hide-on-close : cliquer la croix MASQUE la fenetre (contenu conserve),
#     elle reapparait depuis la fenetre Workspace ;
#   * geometrie : sauvegarde/restauration {x,y,w,h} avec securite multi-ecran
#     (si l'ecran d'origine a disparu, on recentre sur l'ecran primaire).
#
# NOTE V1
# - On garde le cadre natif de l'OS (deplacement/redimensionnement gratuits).
#   La barre de titre custom frameless coherente est un polish ulterieur.
#
# LIENS CLES
# - frontend/modular/window_manager.py : cree et pilote ces fenetres
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QRect, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget

# Surface minimale visible pour considerer une fenetre "sur un ecran".
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
    """Fenetre d'une instance de module (hide-on-close + geometrie persistee)."""

    windowHidden = Signal(str)  # instance_id : la croix a masque la fenetre

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

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)

    def current_geometry(self) -> dict:
        geo = self.geometry()
        return {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
        }

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

    def closeEvent(self, event):  # noqa: N802
        # Hide-on-close : on ne detruit pas, on masque (contenu conserve).
        event.ignore()
        self.hide()
        self.windowHidden.emit(self._instance_id)
