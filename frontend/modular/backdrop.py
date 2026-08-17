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

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from frontend.styles import theme

# Pas minimal affichable : en dessous, le quadrillage vire au aplat uniforme et
# ne renseigne plus sur rien.
MIN_VISIBLE_GRID_PX = 4

# Opacite des lignes. Basse a dessein : c'est un reperage, pas un element de
# decor — il doit s'effacer des qu'on ne le cherche pas. Plus basse que pour
# des points, car des lignes couvrent bien plus de surface a opacite egale.
GRID_LINE_ALPHA = 26

# Multiplicateurs proposes pour l'affichage. Le quadrillage montre une ligne
# tous les `snap_px * multiplicateur` pixels.
GRID_MULTIPLIERS: tuple[int, ...] = (1, 2, 4, 8)

# Par defaut on n'affiche pas chaque pas de snap : a 8 px, une ligne tous les
# 8 pixels serait un aplat. Un quart des lignes suffit a se reperer.
DEFAULT_GRID_MULTIPLIER = 4


def display_step_px(snap_px: int, multiplier: int) -> int:
    """Pas d'AFFICHAGE du quadrillage, deduit du pas de snap.

    Le quadrillage est toujours un MULTIPLE du pas de magnetisme. C'est ce qui
    garantit que chaque ligne affichee correspond a une position ou une fenetre
    s'accroche vraiment : une taille d'affichage libre montrerait des lignes
    trompeuses, la ou rien n'accroche.
    """
    step = max(1, int(snap_px or 1))
    factor = max(1, int(multiplier or 1))
    return step * factor


def grid_brush_origin(widget_global_x: int, widget_global_y: int, step: int) -> QPoint:
    """Decalage du pavage pour que les points tombent sur la grille GLOBALE.

    Le magnetisme raisonne en coordonnees globales ; le fond, lui, part de son
    propre coin. Sans ce decalage, la grille affichee serait decalee de
    l'endroit ou les fenetres s'alignent reellement — un indicateur qui ment.
    Cela se voit des qu'un ecran secondaire place l'origine du bureau virtuel
    en negatif.
    """
    if step <= 0:
        return QPoint(0, 0)
    return QPoint((-int(widget_global_x)) % step, (-int(widget_global_y)) % step)


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
        self._grid_visible = False
        self._snap_step = 8                              # pas du magnetisme
        self._grid_multiplier = DEFAULT_GRID_MULTIPLIER  # densite d'affichage
        self._grid_tile: QPixmap | None = None
        self._apply_style()
        theme.manager.themeChanged.connect(lambda *_a: self._on_theme_changed())

    # -- Grille --------------------------------------------------------------
    def set_grid_visible(self, visible: bool, step: int | None = None) -> None:
        """Affiche ou masque le quadrillage de reperage."""
        if step is not None:
            self.set_grid_metrics(snap_px=step)
        self._grid_visible = bool(visible)
        self.update()

    def set_grid_metrics(self, *, snap_px: int | None = None, multiplier: int | None = None) -> None:
        """Regle le pas de snap et/ou la densite d'affichage."""
        changed = False
        if snap_px is not None:
            snap = max(1, int(snap_px))
            changed = changed or snap != self._snap_step
            self._snap_step = snap
        if multiplier is not None:
            factor = max(1, int(multiplier))
            changed = changed or factor != self._grid_multiplier
            self._grid_multiplier = factor
        if changed:
            self._grid_tile = None       # le pas a change : pavage a refaire
            self.update()

    def is_grid_visible(self) -> bool:
        return self._grid_visible

    @property
    def grid_step(self) -> int:
        """Pas reellement AFFICHE (snap x multiplicateur)."""
        return display_step_px(self._snap_step, self._grid_multiplier)

    @property
    def snap_step(self) -> int:
        return self._snap_step

    @property
    def grid_multiplier(self) -> int:
        return self._grid_multiplier

    def _tile(self) -> QPixmap | None:
        """Pavage d'un pas : une ligne verticale et une horizontale.

        Repete par Qt, ce carreau produit le quadrillage complet. Tracer les
        centaines de lignes a la main couterait cher a chaque repeint ; le
        pavage laisse Qt faire la repetition nativement.
        """
        step = self.grid_step
        if step < MIN_VISIBLE_GRID_PX:
            return None
        if self._grid_tile is not None:
            return self._grid_tile
        color = QColor(theme.manager.p.TEXT)
        color.setAlpha(GRID_LINE_ALPHA)
        tile = QPixmap(step, step)
        tile.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tile)
        try:
            painter.fillRect(0, 0, 1, step, color)   # verticale, bord gauche
            painter.fillRect(0, 0, step, 1, color)   # horizontale, bord haut
        finally:
            painter.end()
        self._grid_tile = tile
        return tile

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)          # l'aplat du theme (WA_StyledBackground)
        if not self._grid_visible:
            return
        tile = self._tile()
        if tile is None:
            return
        painter = QPainter(self)
        try:
            origin = self.geometry().topLeft()
            painter.setBrushOrigin(
                grid_brush_origin(origin.x(), origin.y(), self.grid_step)
            )
            painter.fillRect(self.rect(), QBrush(tile))
        finally:
            painter.end()

    def _on_theme_changed(self) -> None:
        self._grid_tile = None             # la couleur du point suit le theme
        self._apply_style()
        self.update()

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
