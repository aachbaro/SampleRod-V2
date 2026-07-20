# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Helper partage pour donner une croix de fermeture d'onglet PROPRE et
#   uniforme (IconButton "x" de la librairie) au lieu du bouton de fermeture
#   par defaut de Qt (souvent moche / rouge).
#
# USAGE
#   tabs.setTabsClosable(False)   # on gere nous-memes la croix
#   index = tabs.addTab(widget, "titre")
#   add_tab_close_button(tabs, index, lambda: close_this(widget))
#
# LIENS CLES
# - frontend/ui/icon_button.py : la croix (IconButton "x").
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QTabBar, QTabWidget

from .icon_button import IconButton


def add_tab_close_button(
    tab_widget: QTabWidget,
    index: int,
    on_close: Callable[[], None],
    *,
    tooltip: str = "Fermer l'onglet",
) -> IconButton:
    """Pose une croix IconButton propre sur l'onglet `index`.

    `on_close` est appele sans argument quand on clique la croix ; il doit
    fermer l'onglet concerne (par widget, pas par index, car les index bougent).
    """
    button = IconButton("x", tooltip=tooltip, size="s")
    button.clicked.connect(lambda _=False: on_close())
    tab_widget.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
    return button
