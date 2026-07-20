# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Bouton icone-seule reutilisable pour toute l'UI modulaire.
# - Rond, remplissage au survol, icone Tabler recoloree par le theme, tooltip.
# - Objectif : decharger l'interface (plus de boutons texte), coherence totale.
#
# API
#   IconButton("plus", tooltip="Nouvelle instance", size="m")
#   - size : "s" (28/16), "m" (32/20), "l" (40/24)  -> (bouton px / icone px)
#   - variant : "ghost" (defaut, transparent) | "primary" (rempli accent)
#   - checkable via setCheckable(True) ; etat actif = fond BG_CARD
#   .set_icon_name("eye-off") pour changer l'icone a chaud
#
# LIENS CLES
# - frontend/ui/icons.py     : rendu des icones
# - frontend/styles/theme.py : couleurs + signal themeChanged
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QToolButton

from frontend.styles import theme

from .icons import themed_icon

# size -> (cote du bouton, cote de l'icone)
_SIZES: dict[str, tuple[int, int]] = {
    "s": (28, 16),
    "m": (32, 20),
    "l": (40, 24),
}


class IconButton(QToolButton):
    """Bouton rond icone-seule, theme-aware, remplissage au hover."""

    def __init__(
        self,
        icon_name: str,
        *,
        tooltip: str = "",
        size: str = "m",
        variant: str = "ghost",
        parent=None,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._variant = variant
        btn_px, icon_px = _SIZES.get(size, _SIZES["m"])
        self._icon_px = icon_px

        self.setFixedSize(btn_px, btn_px)
        self.setIconSize(QSize(icon_px, icon_px))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)

        self._refresh_icon()
        self._apply_style()
        theme.manager.themeChanged.connect(self._on_theme_changed)

    # -- API publique -------------------------------------------------------
    def set_icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self._refresh_icon()

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self._apply_style()
        self._refresh_icon()

    # -- Interne ------------------------------------------------------------
    def _icon_color(self) -> str:
        p = theme.manager.p
        if self._variant == "primary":
            # Sur fond accent : couleur contrastee (fond sombre du theme).
            return p.BG_DARK
        return p.TEXT

    def _refresh_icon(self) -> None:
        self.setIcon(themed_icon(self._icon_name, self._icon_px, self._icon_color()))

    def _on_theme_changed(self, *_args) -> None:
        self._refresh_icon()
        self._apply_style()

    def _apply_style(self) -> None:
        p = theme.manager.p
        radius = self.width() // 2
        if self._variant == "primary":
            self.setStyleSheet(
                f"""
                QToolButton {{
                    border: none;
                    border-radius: {radius}px;
                    background: {p.ACCENT};
                }}
                QToolButton:hover {{ background: {p.RETRO}; }}
                QToolButton:pressed {{ background: {p.INFO}; }}
                QToolButton:disabled {{ background: {p.BG_CARD}; }}
                """
            )
        else:
            self.setStyleSheet(
                f"""
                QToolButton {{
                    border: none;
                    border-radius: {radius}px;
                    background: transparent;
                }}
                QToolButton:hover {{ background: {p.BG_HOVER}; }}
                QToolButton:pressed {{ background: {p.BG_CARD}; }}
                QToolButton:checked {{ background: {p.BG_CARD}; }}
                QToolButton:disabled {{ background: transparent; }}
                """
            )
