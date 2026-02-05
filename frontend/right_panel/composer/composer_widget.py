"""
------------------------------------------------------------------------------
Sample Composer (Placeholder)
------------------------------------------------------------------------------
Objectif
--------
Futur outil du panneau droit: construire un "sample compose" en concaténant des
slices (markers) et/ou des samples entiers via drag & drop.

Ce fichier est volontairement minimal pour l'instant: on pose seulement le
"squelette" UI pour pouvoir integrer l'onglet des maintenant, sans bloquer
le refactor du Right Panel.
------------------------------------------------------------------------------
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class SampleComposerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Tool card: le style (background/border/radius) est applique via QSS
        # depuis RightToolsPanel (tools_panel.py).
        self.setObjectName("ComposerToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Compositeur (TODO)")
        title.setStyleSheet("color: #f5f5f5; font-weight: 600;")

        hint = QLabel(
            "Cet outil permettra de drop des slices pour construire un nouveau sample.\n"
            "Pour l'instant on pose juste l'onglet."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b9b9b9;")

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addStretch(1)
