"""
------------------------------------------------------------------------------
Sample Composer - UI (Builder + style tokens)
------------------------------------------------------------------------------
Role
----
Point unique pour l'UI du Compositeur:
- construction du layout (actions + preview waveform + clip list)
- tokens de style (couleurs, tailles) alignee avec Waveform/SampleCard

Le but est de pouvoir modifier rapidement le look & feel sans toucher a la
logique (modele, concat, drag & drop).
------------------------------------------------------------------------------
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme

from .composer_clip_list import ComposerClipListWidget

BTN_SIZE = 24
BTN_ICON = 10


def build_composer_widget_ui(widget) -> None:
    """
    Construit l'UI du Compositeur.

    Convention:
    - on attache les references sur `widget` (clip_list, plot, boutons, etc.)
    - la logique reste dans composer_widget.py
    """
    # Note: le widget parent est la "tool card" (objectName=ComposerToolCard)
    # stylisee depuis RightToolsPanel. Ici, on ne touche pas a cet objectName.
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)

    # ---------------- header (infos + actions)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)

    widget.info_label = QLabel("Drop des slices (markers) pour composer un sample")
    widget.info_label.setObjectName("ComposerInfoLabel")

    header.addWidget(widget.info_label, 1)

    p = theme.manager.p
    widget.save_comp_btn = HoverIconButton(
        icon_name="fa5s.save",
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=p.TEXT_MUTED,
        icon_color_hover="#111111",
        border_color=p.BORDER,
        parent=widget,
    )
    widget.save_comp_btn.setToolTip("Sauvegarder la composition")
    widget.save_comp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    header.addWidget(widget.save_comp_btn, 0)

    widget.clear_btn = HoverIconButton(
        icon_name="fa5s.times",
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=p.TEXT_MUTED,
        icon_color_hover="#111111",
        border_color=p.BORDER,
        parent=widget,
    )
    widget.clear_btn.setToolTip("Vider la composition")
    widget.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    header.addWidget(widget.clear_btn, 0)

    layout.addLayout(header)

    # ---------------- preview stack (plot + list underneath)
    preview = QWidget()
    preview.setObjectName("ComposerPreviewStack")
    preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    preview_layout = QVBoxLayout(preview)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preview_layout.setSpacing(8)

    # Conteneur pour le WaveformWidget (reutilise le vrai editor).
    widget.waveform_container = QWidget()
    widget.waveform_container.setObjectName("ComposerWaveformContainer")
    widget.waveform_layout = QVBoxLayout(widget.waveform_container)
    widget.waveform_layout.setContentsMargins(0, 0, 0, 0)
    widget.waveform_layout.setSpacing(0)
    preview_layout.addWidget(widget.waveform_container, 0)

    widget.time_label = QLabel("Durée: 0.00s")
    widget.time_label.setObjectName("ComposerTimeLabel")
    widget.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
    preview_layout.addWidget(widget.time_label, 0)

    widget.clip_list = ComposerClipListWidget()
    widget.clip_list.setObjectName("ComposerClipList")
    widget.clip_list.setFrameShape(QFrame.Shape.NoFrame)
    widget.clip_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.clip_list.setFixedHeight(220)
    # Espace entre les rows gere en PyQt (pas en QSS).
    widget.clip_list.setSpacing(4)
    widget.clip_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.clip_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    preview_layout.addWidget(widget.clip_list, 0)

    layout.addWidget(preview, 1)

    apply_styles(widget)
    theme.manager.themeChanged.connect(lambda _: restyle(widget))


def apply_styles(widget) -> None:
    p = theme.manager.p
    widget.setStyleSheet(
        f"""
        QLabel#ComposerInfoLabel {{
            color: {p.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#ComposerTimeLabel {{
            color: {p.TEXT_MUTED};
            font-size: 10px;
        }}

        QWidget#ComposerToolCard[focused="true"] {{
            border: 1px solid {p.WARNING};
        }}
        QWidget#ComposerToolCard[dropActive="true"] {{
            border: 1px solid {p.WARNING};
            background-color: {p.BG_HOVER};
        }}

        QListWidget#ComposerClipList {{
            background: transparent;
            border: 1px solid {p.BORDER_LIGHT};
            border-radius: 10px;
            padding: 4px;
            outline: none;
        }}
        QListWidget#ComposerClipList::item {{
            border: none;
            padding: 0px;
            margin: 0px;
            background: transparent;
        }}
        QListWidget#ComposerClipList::item:selected {{
            background: transparent;
        }}
        QListWidget#ComposerClipList::item:hover {{
            background: transparent;
        }}
        QListWidget#ComposerClipList::item:focus {{
            outline: none;
        }}

        QWidget#ComposerClipRow {{
            background-color: transparent;
            border: none;
        }}
        QLabel#ComposerClipLabel {{
            color: {p.TEXT};
            font-size: 12px;
            font-weight: 600;
        }}
        """
    )


def restyle(widget) -> None:
    """Re-applique les styles selon le theme courant."""
    apply_styles(widget)
    p = theme.manager.p
    widget.save_comp_btn.update_colors(p.TEXT_MUTED, "#111111", p.BORDER)
    widget.clear_btn.update_colors(p.TEXT_MUTED, "#111111", p.BORDER)
