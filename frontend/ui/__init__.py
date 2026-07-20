# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Design-core de l'UI modulaire : composants visuels reutilisables et
#   coherents (icones Tabler recolorees, boutons icone-seule, tooltips rapides).
# - Toute la nouvelle interface (WindowManager, Workspace, modules) s'appuie
#   dessus pour un rendu uniforme en niveaux de gris, dark/light.
#
# MODULES
# - icons.py        : registre d'icones + themed_icon()
# - icon_button.py  : IconButton (rond, hover fill, theme-aware)
# - fast_tooltip.py : install_fast_tooltips() (delai reduit)
# -----------------------------------------------------------------------------

from .icon_button import IconButton
from .icons import available_names, clear_cache, render_pixmap, themed_icon
from .fast_tooltip import FastTooltipStyle, install_fast_tooltips

__all__ = [
    "IconButton",
    "themed_icon",
    "render_pixmap",
    "available_names",
    "clear_cache",
    "FastTooltipStyle",
    "install_fast_tooltips",
]
