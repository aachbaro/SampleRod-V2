# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Sous-package des styles globaux de l'application.
# - Exporte le ThemeManager singleton (theme.manager) pour toute l'app.
#
# MODULES
# - theme.py : palettes DARK/LIGHT, ThemeManager, build_global_qss()
#
# USAGE
#   from frontend.styles import theme
#   color = theme.manager.p.BG          # lecture couleur courante
#   theme.manager.themeChanged.connect(slot)  # reaction au changement
# -----------------------------------------------------------------------------
