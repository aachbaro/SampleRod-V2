# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'UI de SampleListWidget (toolbar, scroll area, pagination).
# - Regroupe styles, widgets et layouts pour alleger sample_list.py.
#
# FONCTIONS (sommaire)
# - SampleListUIBuilder   : constructeur d'UI
# - build()               : cree toolbar, scroll area + content_layout, pagination
# - _apply_stylesheet(w)  : QSS du fond, scroll bar et toolbar
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py    : SampleListWidget (widget parent)
# - frontend/sample_gui/waveform/waveform_ui.py  : HoverIconButton pour la toolbar
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
    QSizePolicy,
)

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme
from frontend.ui import themed_icon

class SampleListUIBuilder:
    """Constructeur d'UI pour SampleListWidget (toolbar + scroll + pagination)."""

    def __init__(self, widget):
        self.widget = widget

    def build(self):
        """Construit toolbar, scroll area, content_layout et pagination.

        Attache sur le widget: content_layout, scroll_area, pagination_label,
        prev_page_btn, next_page_btn, et les boutons d'action bulk.
        """
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

        w.recent_title = QLabel("")
        w.recent_title.setObjectName("RecentSectionTitle")
        w.toolbar.addWidget(w.recent_title)
        spacer = QWidget()
        spacer.setObjectName("SampleToolbarSpacer")
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.toolbar.addWidget(spacer)

        w.add_files_btn = None

        w.select_all_btn = self._make_round_btn("check", "Sélectionner cette page")
        w.deselect_all_btn = self._make_round_btn("x", "Tout decocher")
        w.select_all_btn.clicked.connect(w.onSelectAll)
        w.deselect_all_btn.clicked.connect(w.onDeselectAll)
        w.toolbar.addWidget(w.select_all_btn)
        w.deselect_all_btn.setToolTip("Désélectionner cette page")
        w.toolbar.addWidget(w.deselect_all_btn)

        w.toolbar.addSeparator()

        w.bulk_archive_act = QAction(
            themed_icon("x", size=16, color="#bdbdbd"),
            "Désindexer",
            w,
        )
        w.bulk_archive_act.setEnabled(False)
        w.bulk_archive_act.triggered.connect(w.bulkRemoveFromHistory)

        w.bulk_delete_act = QAction(
            themed_icon("trash", size=16, color="#c06a6a"),
            "Supprimer",
            w,
        )
        w.bulk_delete_act.setEnabled(False)
        w.bulk_delete_act.triggered.connect(w.bulkDelete)

        w.bulk_move_act = QAction(
            themed_icon("folder", size=16, color="#bdbdbd"),
            "Deplacer...",
            w,
        )
        w.bulk_move_act.setEnabled(False)
        w.bulk_move_act.triggered.connect(w.bulkMove)

        w.bulk_normalize_act = QAction(
            themed_icon("bolt", size=16, color="#c9a75a"),
            "Normaliser",
            w,
        )
        w.bulk_normalize_act.setEnabled(False)
        w.bulk_normalize_act.triggered.connect(w.bulkNormalize)

        w.bulk_analyze_act = QAction(
            themed_icon("music", size=16, color="#58c7d4"),
            "Analyser la gamme de la sélection",
            w,
        )
        w.bulk_analyze_act.setEnabled(False)
        w.bulk_analyze_act.triggered.connect(
            lambda: getattr(w, "bulkAnalyzeScale", lambda: None)()
        )

        w.actions_menu = QMenu(w)
        w.actions_menu.addAction(w.bulk_archive_act)
        w.actions_menu.addAction(w.bulk_delete_act)
        w.actions_menu.addAction(w.bulk_move_act)
        w.actions_menu.addAction(w.bulk_normalize_act)
        w.actions_menu.addAction(w.bulk_analyze_act)

        w.actions_btn = self._make_round_btn("dots-vertical", "Actions selection")
        w.actions_btn.setObjectName("RecentActionsMenuButton")
        # Ouverture manuelle : pas de menu attache au QToolButton, donc Qt ne
        # dessine aucun petit chevron redondant sous les trois points.
        w.actions_btn.clicked.connect(
            lambda: w.actions_menu.exec(
                w.actions_btn.mapToGlobal(w.actions_btn.rect().bottomLeft())
            )
        )
        w.toolbar.addWidget(w.actions_btn)
        w.toolbar.setVisible(True)

        w.bulk_bar = QWidget()
        w.bulk_bar.setObjectName("RecentBulkBar")
        bulk_layout = QHBoxLayout(w.bulk_bar)
        bulk_layout.setContentsMargins(8, 4, 8, 4)
        bulk_layout.setSpacing(6)
        w.bulk_count_label = QLabel("0 sélectionné")
        w.bulk_count_label.setObjectName("RecentBulkCount")
        bulk_layout.addWidget(w.bulk_count_label)
        bulk_layout.addStretch(1)
        w.bulk_buttons = []
        for text, action in (
            ("Analyser", w.bulk_analyze_act),
            ("Normaliser", w.bulk_normalize_act),
            ("Déplacer", w.bulk_move_act),
            ("Désindexer", w.bulk_archive_act),
            ("Supprimer", w.bulk_delete_act),
        ):
            button = QPushButton(text)
            button.setObjectName("RecentBulkButton")
            button.clicked.connect(action.trigger)
            bulk_layout.addWidget(button)
            w.bulk_buttons.append(button)
        w.bulk_bar.hide()
        panel_layout.addWidget(w.bulk_bar)

        # ---- Drag & drop enabled
        w.setAcceptDrops(True)

        # ---- Scroll area
        w.scroll_area = QScrollArea()
        w.scroll_area.setObjectName("SampleScroll")
        w.scroll_area.setWidgetResizable(True)
        w.content_widget = QWidget()
        w.content_widget.setObjectName("SampleListContent")
        w.content_layout = QVBoxLayout(w.content_widget)
        w.content_layout.setSpacing(2)
        w.content_layout.setContentsMargins(4, 4, 4, 4)
        w.scroll_area.setWidget(w.content_widget)
        panel_layout.addWidget(w.scroll_area)

        # ---- Pagination
        w.pagination_layout = QHBoxLayout()
        w.pagination_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        w.pagination_label = QLabel("0 - 0 / 0")
        w.pagination_label.setObjectName("PaginationLabel")

        w.prev_button = self._make_round_btn("chevron-left", "Page precedente")
        w.next_button = self._make_round_btn("chevron-right", "Page suivante")
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
                background-color: transparent;
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QToolBar#SampleToolbar {{
                background: transparent;
                border: none;
                spacing: 6px;
                padding: 6px 8px 4px 8px;
            }}
            QToolBar#SampleToolbar QWidget {{
                background: transparent;
                border: none;
            }}
            QToolBar#SampleToolbar::separator {{
                background: {p.BORDER};
                width: 1px;
                margin: 0 6px;
            }}
            QToolButton#RecentActionsMenuButton::menu-indicator {{
                image: none;
                width: 0px;
                height: 0px;
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
            QLabel#RecentSectionTitle {{ background:transparent; color:{p.TEXT_MUTED}; font-size:10px; font-weight:700; }}
            QWidget#SampleToolbarSpacer {{ background:transparent; border:none; }}
            QWidget#RecentBulkBar {{ background:{p.BG_CARD}; border:1px solid {p.BORDER}; border-radius:8px; }}
            QLabel#RecentBulkCount {{ color:{p.TEXT}; font-weight:600; }}
            QPushButton#RecentBulkButton {{ background:transparent; color:{p.TEXT}; border:1px solid {p.BORDER}; border-radius:6px; padding:3px 7px; }}
            QPushButton#RecentBulkButton:hover {{ background:{p.BG_HOVER}; }}
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
        for btn in filter(
            None,
            [
                widget.add_files_btn,
                widget.select_all_btn,
                widget.deselect_all_btn,
                widget.actions_btn,
                widget.prev_button,
                widget.next_button,
            ],
        ):
            btn.update_colors(neutral, icon_hover, border)
