# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'UI de SampleListWidget (toolbar, scroll area, pagination).
# - Regroupe styles, widgets et layouts pour alleger sample_list.py.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QToolBar,
    QToolButton,
    QPushButton,
    QMenu,
    QLabel,
)
import qtawesome as qta

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme

class SampleListUIBuilder:
    def __init__(self, widget):
        self.widget = widget

    def build(self):
        w = self.widget
        # Global container for the list area + header.
        w.setObjectName("SampleListRoot")
        SampleListUIBuilder._apply_stylesheet(w)

        main_layout = QVBoxLayout(w)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Panel = one block (header + list) to avoid the "two separate blocks" feel.
        w.panel = QWidget()
        w.panel.setObjectName("SampleListPanel")
        panel_layout = QVBoxLayout(w.panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(6)
        main_layout.addWidget(w.panel)

        # ---- Toolbar
        w.toolbar = QToolBar("Bulk Actions")
        w.toolbar.setObjectName("SampleToolbar")
        w.toolbar.setIconSize(QSize(10, 10))
        w.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        panel_layout.addWidget(w.toolbar)

        w.add_files_btn = self._make_round_btn(
            "fa5s.folder-open",
            "Ajouter un ou plusieurs fichiers audio",
        )
        w.add_files_btn.clicked.connect(w.onAddFiles)
        w.toolbar.addWidget(w.add_files_btn)

        w.select_all_btn = self._make_round_btn("fa5s.check-double", "Tout cocher")
        w.deselect_all_btn = self._make_round_btn("fa5s.times-circle", "Tout decocher")
        w.select_all_btn.clicked.connect(w.onSelectAll)
        w.deselect_all_btn.clicked.connect(w.onDeselectAll)
        w.toolbar.addWidget(w.select_all_btn)
        w.toolbar.addWidget(w.deselect_all_btn)

        w.toolbar.addSeparator()

        w.bulk_archive_act = QAction(
            qta.icon("fa5s.times-circle", color="#bdbdbd"),
            "Retirer de l'historique",
            w,
        )
        w.bulk_archive_act.setEnabled(False)
        w.bulk_archive_act.triggered.connect(w.bulkRemoveFromHistory)

        w.bulk_delete_act = QAction(qta.icon("fa5s.trash-alt", color="#c06a6a"), "Supprimer", w)
        w.bulk_delete_act.setEnabled(False)
        w.bulk_delete_act.triggered.connect(w.bulkDelete)

        w.bulk_move_act = QAction(qta.icon("fa5s.folder", color="#bdbdbd"), "Deplacer...", w)
        w.bulk_move_act.setEnabled(False)
        w.bulk_move_act.triggered.connect(w.bulkMove)

        w.bulk_normalize_act = QAction(qta.icon("fa5s.bolt", color="#c9a75a"), "Normaliser", w)
        w.bulk_normalize_act.setEnabled(False)
        w.bulk_normalize_act.triggered.connect(w.bulkNormalize)

        w.actions_menu = QMenu(w)
        w.actions_menu.addAction(w.bulk_archive_act)
        w.actions_menu.addAction(w.bulk_delete_act)
        w.actions_menu.addAction(w.bulk_move_act)
        w.actions_menu.addAction(w.bulk_normalize_act)

        w.actions_btn = self._make_round_btn("fa5s.list", "Actions selection")
        w.actions_btn.setMenu(w.actions_menu)
        w.actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        w.toolbar.addWidget(w.actions_btn)

        # ---- Drag & drop enabled
        w.setAcceptDrops(True)

        # ---- Scroll area
        w.scroll_area = QScrollArea()
        w.scroll_area.setObjectName("SampleScroll")
        w.scroll_area.setWidgetResizable(True)
        w.content_widget = QWidget()
        w.content_widget.setObjectName("SampleListContent")
        w.content_layout = QVBoxLayout(w.content_widget)
        w.content_layout.setSpacing(10)
        w.content_layout.setContentsMargins(10, 10, 10, 10)
        w.scroll_area.setWidget(w.content_widget)
        panel_layout.addWidget(w.scroll_area)

        # ---- Pagination
        w.pagination_layout = QHBoxLayout()
        w.pagination_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        w.pagination_label = QLabel("0 - 0 / 0")
        w.pagination_label.setObjectName("PaginationLabel")

        w.prev_button = self._make_round_btn("fa5s.chevron-left", "Page precedente")
        w.next_button = self._make_round_btn("fa5s.chevron-right", "Page suivante")
        w.prev_button.clicked.connect(w._prev_page)
        w.next_button.clicked.connect(w._next_page)

        w.pagination_layout.addWidget(w.prev_button)
        w.pagination_layout.addWidget(w.pagination_label)
        w.pagination_layout.addWidget(w.next_button)
        panel_layout.addLayout(w.pagination_layout)

    def _make_round_btn(self, icon_name: str, tooltip: str) -> HoverIconButton:
        p = theme.manager.p
        btn = HoverIconButton(
            icon_name=icon_name,
            size=24,
            icon_size=10,
            icon_color_normal=p.TEXT_MUTED,
            icon_color_hover="#111111",
            border_color=p.BG_CARD,
            parent=self.widget.toolbar,
        )
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    @staticmethod
    def _apply_stylesheet(widget):
        p = theme.manager.p
        widget.setStyleSheet(
            f"""
            QWidget#SampleListRoot {{
                background-color: {p.BG_DARK};
            }}
            QWidget#SampleListPanel {{
                background-color: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
            }}
            QToolBar#SampleToolbar {{
                background: transparent;
                border: none;
                spacing: 6px;
                padding: 6px 8px 4px 8px;
            }}
            QToolBar#SampleToolbar::separator {{
                background: {p.BORDER};
                width: 1px;
                margin: 0 6px;
            }}
            QScrollArea#SampleScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#SampleListContent {{
                background: transparent;
            }}
            QLabel#PaginationLabel {{
                color: {p.TEXT_MUTED};
            }}
            QMenu {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
            }}
            QMenu::item:selected {{
                background: {p.BG_CARD};
            }}
            QScrollBar:vertical {{
                background: {p.BG_DARK};
                width: 10px;
                margin: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {p.BORDER};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {p.BORDER_LIGHT};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
            }}
            """
        )

    @staticmethod
    def restyle(widget):
        """Re-applique le style selon le theme courant. Appeler sur themeChanged."""
        SampleListUIBuilder._apply_stylesheet(widget)
        p = theme.manager.p
        border = p.BG_CARD
        neutral = p.TEXT_MUTED
        icon_hover = "#111111"
        for btn in [
            widget.add_files_btn,
            widget.select_all_btn,
            widget.deselect_all_btn,
            widget.actions_btn,
            widget.prev_button,
            widget.next_button,
        ]:
            btn.update_colors(neutral, icon_hover, border)
