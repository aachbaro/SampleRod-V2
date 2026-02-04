# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'UI de SampleListWidget (toolbar, scroll area, pagination).
# - Regroupe styles, widgets et layouts pour alleger sample_list.py.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
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


class SampleListUIBuilder:
    def __init__(self, widget):
        self.widget = widget

    def build(self):
        w = self.widget
        w.setObjectName("SampleListRoot")
        w.setStyleSheet(
            """
            QWidget#SampleListRoot {
                background-color: #121212;
            }
            QToolBar#SampleToolbar {
                background-color: #181818;
                border: 1px solid #262626;
                border-radius: 8px;
                spacing: 6px;
                padding: 6px;
            }
            QToolBar#SampleToolbar QToolButton {
                color: #eaeaea;
                background: #202020;
                border: 1px solid #2f2f2f;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QToolBar#SampleToolbar QToolButton:hover {
                background: #2a2a2a;
            }
            QToolBar#SampleToolbar QToolButton:disabled {
                color: #777777;
                background: #1a1a1a;
                border-color: #262626;
            }
            QToolBar#SampleToolbar::separator {
                background: #2a2a2a;
                width: 1px;
                margin: 0 6px;
            }
            QScrollArea#SampleScroll {
                background: #141414;
                border: 1px solid #222222;
                border-radius: 10px;
            }
            QWidget#SampleListContent {
                background: #141414;
            }
            QLabel#PaginationLabel {
                color: #cfcfcf;
            }
            QPushButton[role="pagination"] {
                background: #202020;
                color: #eaeaea;
                border: 1px solid #2f2f2f;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton[role="pagination"]:hover {
                background: #2a2a2a;
            }
            QPushButton[role="pagination"]:disabled {
                color: #777777;
                background: #1a1a1a;
                border-color: #262626;
            }
            QMenu {
                background: #1b1b1b;
                color: #eaeaea;
                border: 1px solid #2a2a2a;
            }
            QMenu::item:selected {
                background: #2a2a2a;
            }
            QScrollBar:vertical {
                background: #141414;
                width: 10px;
                margin: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2b2b2b;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3a3a3a;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            """
        )

        main_layout = QVBoxLayout(w)

        # ---- Toolbar
        w.toolbar = QToolBar("Bulk Actions")
        w.toolbar.setObjectName("SampleToolbar")
        w.toolbar.setIconSize(QSize(24, 24))
        w.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        main_layout.addWidget(w.toolbar)

        w.add_files_act = QAction(qta.icon("fa5s.folder-open"), "Ajouter fichiers...", w)
        w.add_files_act.setToolTip("Ajouter un ou plusieurs fichiers audio")
        w.add_files_act.triggered.connect(w.onAddFiles)
        w.toolbar.addAction(w.add_files_act)

        w.select_all_act = QAction(qta.icon("fa5s.check-double"), "Tout cocher", w)
        w.deselect_all_act = QAction(qta.icon("fa5s.times-circle"), "Tout decocher", w)
        w.select_all_act.triggered.connect(w.onSelectAll)
        w.deselect_all_act.triggered.connect(w.onDeselectAll)
        w.toolbar.addAction(w.select_all_act)
        w.toolbar.addAction(w.deselect_all_act)

        w.toolbar.addSeparator()

        w.bulk_archive_act = QAction(
            qta.icon("fa5s.times-circle", color="lightgray"),
            "Retirer de l'historique",
            w,
        )
        w.bulk_archive_act.setEnabled(False)
        w.bulk_archive_act.triggered.connect(w.bulkRemoveFromHistory)

        w.bulk_delete_act = QAction(qta.icon("fa5s.trash-alt", color="red"), "Supprimer", w)
        w.bulk_delete_act.setEnabled(False)
        w.bulk_delete_act.triggered.connect(w.bulkDelete)

        w.bulk_move_act = QAction(qta.icon("fa5s.folder", color="lightgray"), "Deplacer...", w)
        w.bulk_move_act.setEnabled(False)
        w.bulk_move_act.triggered.connect(w.bulkMove)

        w.bulk_normalize_act = QAction(qta.icon("fa5s.bolt", color="orange"), "Normaliser", w)
        w.bulk_normalize_act.setEnabled(False)
        w.bulk_normalize_act.triggered.connect(w.bulkNormalize)

        w.actions_menu = QMenu(w)
        w.actions_menu.addAction(w.bulk_archive_act)
        w.actions_menu.addAction(w.bulk_delete_act)
        w.actions_menu.addAction(w.bulk_move_act)
        w.actions_menu.addAction(w.bulk_normalize_act)

        w.actions_btn = QToolButton(w)
        w.actions_btn.setText("Actions selection")
        w.actions_btn.setIcon(qta.icon("fa5s.list"))
        w.actions_btn.setMenu(w.actions_menu)
        w.actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        w.actions_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
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
        main_layout.addWidget(w.scroll_area)

        # ---- Pagination
        w.pagination_layout = QHBoxLayout()
        w.pagination_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        w.pagination_label = QLabel("0 - 0 / 0")
        w.pagination_label.setObjectName("PaginationLabel")
        w.pagination_layout.addWidget(w.pagination_label)

        w.prev_button = QPushButton("Precedent")
        w.prev_button.setProperty("role", "pagination")
        w.next_button = QPushButton("Suivant")
        w.next_button.setProperty("role", "pagination")
        w.prev_button.clicked.connect(w._prev_page)
        w.next_button.clicked.connect(w._next_page)

        w.pagination_layout.addWidget(w.prev_button)
        w.pagination_layout.addWidget(w.next_button)
        main_layout.addLayout(w.pagination_layout)
