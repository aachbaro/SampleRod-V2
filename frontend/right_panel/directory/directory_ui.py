"""
------------------------------------------------------------------------------
Directory UI (Builder + Style Tokens)
------------------------------------------------------------------------------
Role
----
Ce module est le "point unique" pour tout ce qui touche a l'UI du Directory tool:
- construction du layout du DirectoryWidget (header + liste)
- construction du widget de ligne (DirectoryListItemWidget)
- constantes UI (tailles, icones, couleurs)

Objectif
--------
Permettre de retoucher rapidement le look & feel (espacements, tailles, icones,
styles) sans aller modifier la logique/metier dans plusieurs fichiers.

Note
----
On garde volontairement ici un style minimal (proche du comportement existant),
le but du refactor est d'abord structurel. Une fois la separation "UI vs logique"
faite, le remake visuel devient beaucoup plus simple.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QLineEdit

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme

from .directory_list_widget import DirectoryListWidget

# ----------------------------------------------------------------------------- tokens (non-color)
BTN_SIZE = 24
BTN_ICON = 10

ICON_PLAY = "fa5s.play"
ICON_PAUSE = "fa5s.pause"
ICON_DELETE = "fa5s.trash-alt"

# Kept for backward-compat callsites that might reference these directly
# (remove once all callers use theme.manager.p.*)
ICON_NORMAL = "#cfcfcf"
ICON_HOVER = "#111111"


# ----------------------------------------------------------------------------- builders
def build_directory_widget_ui(widget) -> None:
    """
    Construit l'UI de base du DirectoryWidget.

    Convention:
    - On cree ici les sous-widgets (label de chemin + liste) pour garder toute la
      construction UI dans un seul fichier.
    - Le "choix du dossier" se fait dans MainWindow (Add directory -> QFileDialog),
      donc DirectoryWidget n'embarque pas de bouton "Choose folder".
    """
    # Container style / tokens
    widget.setObjectName("DirectoryWidget")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)

    widget.list_widget = DirectoryListWidget(widget)
    widget.list_widget.setObjectName("DirectoryList")
    widget.list_widget.setSpacing(6)

    layout.addWidget(widget.list_widget)

    apply_styles(widget)


def set_directory_path(widget, path: str) -> None:
    """
    Met a jour le label de chemin, si present.
    (Le label vit dans l'UI, mais la valeur vient de la logique du widget.)
    """
    lbl = getattr(widget, "path_label", None)
    if lbl is None:
        return
    # Affichage compact: basename, avec tooltip full path.
    lbl.setText(os.path.basename(path) or path)
    lbl.setToolTip(path)


def build_directory_item_ui(
    item_widget,
    file_path: str,
    *,
    on_start_rename,
    on_submit_rename,
    on_toggle_preview,
    on_delete,
) -> None:
    """
    Construit l'UI d'une ligne (DirectoryListItemWidget).

    On passe les callbacks pour garder le fichier "widget" concentre sur la logique.
    """
    item_widget.setObjectName("DirectoryRow")
    item_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    item_widget.name_label = QLabel(os.path.basename(file_path))
    item_widget.name_label.setObjectName("DirectoryItemName")
    # Hack PyQt: on remplace le handler pour activer le rename inline.
    item_widget.name_label.mouseDoubleClickEvent = on_start_rename  # type: ignore[assignment]

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    item_widget.rename_input = QLineEdit(base_name)
    item_widget.rename_input.setObjectName("DirectoryRenameInput")
    item_widget.rename_input.hide()
    item_widget.rename_input.editingFinished.connect(on_submit_rename)

    # Boutons: meme look & feel que le waveform editor (HoverIconButton 24px / icone 10px)
    p = theme.manager.p
    item_widget.play_button = HoverIconButton(
        icon_name=ICON_PLAY,
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=p.TEXT_MUTED,
        icon_color_hover="#111111",
        border_color=p.BORDER,
        parent=item_widget,
    )
    item_widget.play_button.clicked.connect(on_toggle_preview)
    item_widget.play_button.setToolTip("Pre-ecouter")
    item_widget.play_button.setCursor(Qt.CursorShape.PointingHandCursor)

    item_widget.delete_button = HoverIconButton(
        icon_name=ICON_DELETE,
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=p.ERROR,
        icon_color_hover="#111111",
        border_color=p.BORDER,
        parent=item_widget,
    )
    item_widget.delete_button.clicked.connect(on_delete)
    item_widget.delete_button.setToolTip("Supprimer")
    item_widget.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)

    layout = QHBoxLayout(item_widget)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(8)
    layout.addWidget(item_widget.name_label)
    layout.addWidget(item_widget.rename_input)
    layout.addStretch()
    layout.addWidget(item_widget.play_button)
    layout.addWidget(item_widget.delete_button)

    # Small UI niceties: align vertically with icon buttons.
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)


def set_item_playing(item_widget, playing: bool) -> None:
    """Met a jour l'icone play/pause sans dupliquer les tokens dans le widget."""
    p = theme.manager.p
    icon_name = ICON_PAUSE if playing else ICON_PLAY
    if hasattr(item_widget.play_button, "set_icon_pair"):
        item_widget.play_button.set_icon_pair(
            icon_name,
            icon_color_normal=p.TEXT_MUTED,
            icon_color_hover="#111111",
        )
    else:
        item_widget.play_button.setIcon(qta.icon(icon_name, color="lightgray"))


def restyle_item(item_widget) -> None:
    """Re-applique le style d'une ligne selon le theme courant."""
    p = theme.manager.p
    item_widget.play_button.update_colors(p.TEXT_MUTED, "#111111", p.BORDER)
    item_widget.delete_button.update_colors(p.ERROR, "#111111", p.BORDER)


# ----------------------------------------------------------------------------- style
def apply_styles(widget) -> None:
    """
    Applique les styles QSS du Directory tool.

    Important:
    - On limite le scope via objectName (#DirectoryWidget, #DirectoryList, etc.)
      pour ne pas impacter le reste de l'application.
    - Les widgets "rows" (DirectoryRow) heritent de ce stylesheet.
    """
    p = theme.manager.p
    widget.setStyleSheet(
        f"""
        QWidget#DirectoryWidget {{
            background: transparent;
            border: none;
        }}

        QListWidget#DirectoryList {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QListWidget#DirectoryList::item {{
            border: none;
            padding: 0px;
            margin: 0px;
            background: transparent;
        }}
        QListWidget#DirectoryList::item:selected {{
            background: transparent;
        }}

        QWidget#DirectoryRow {{
            background-color: {p.BG_MEDIUM};
            border: 1px solid {p.BORDER};
            border-radius: 10px;
        }}
        QWidget#DirectoryRow:hover {{
            background-color: {p.BG_HOVER};
            border-color: {p.BORDER_LIGHT};
        }}

        QLabel#DirectoryItemName {{
            color: {p.TEXT};
            font-size: 12px;
            font-weight: 600;
        }}
        QLineEdit#DirectoryRenameInput {{
            background-color: {p.BG_CARD};
            color: {p.TEXT};
            border: 1px solid {p.WARNING};
            border-radius: 6px;
            padding: 4px 6px;
        }}
        """
    )
