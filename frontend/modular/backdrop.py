# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fond global optionnel de l'atelier modulaire : une fenetre plein-ecran
#   posee DERRIERE les fenetres de module, pour masquer le bureau et les
#   autres applications (eviter l'effet "bordelique").
# - N'est pas un vrai flou (peu fiable sous Windows) mais un aplat sobre au
#   ton du theme. Fait partie du "groupe" remonte par le WindowManager : il
#   suit l'atelier au premier plan et repasse derriere quand on quitte l'app.
#
# LIENS CLES
# - frontend/modular/window_manager.py : cree/affiche/masque + ordre de z.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from frontend.styles import theme


class BackdropWindow(QWidget):
    """Aplat plein-ecran derriere les fenetres de l'atelier."""

    def __init__(self, window_manager=None, parent=None):
        super().__init__(parent)
        self._wm = window_manager
        self.setObjectName("ModularBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setWindowTitle("SampleRod")
        self._apply_style()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_style())

    def cover_screens(self) -> None:
        """Couvre tout le bureau virtuel (tous les ecrans)."""
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.virtualGeometry())

    def changeEvent(self, event):  # noqa: N802
        # Cliquer le fond ramene tout l'atelier au premier plan.
        if (
            event.type() == QEvent.Type.ActivationChange
            and self.isActiveWindow()
            and self._wm is not None
        ):
            self._wm.raise_group()
        super().changeEvent(event)

    def _apply_style(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(f"QWidget#ModularBackdrop {{ background: {p.BG_DARK}; }}")
