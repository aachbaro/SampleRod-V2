from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.styles import theme


def build_library_widget_ui(widget) -> None:
    widget.setObjectName("LibraryRoot")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    main_layout = QVBoxLayout(widget)
    main_layout.setContentsMargins(8, 8, 8, 8)
    main_layout.setSpacing(8)

    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)

    widget.title_label = QLabel("Bibliotheque")
    widget.title_label.setObjectName("LibraryTitle")

    widget.count_label = QLabel("0 sample")
    widget.count_label.setObjectName("LibraryCount")

    widget.search_input = QLineEdit()
    widget.search_input.setObjectName("LibrarySearch")
    widget.search_input.setPlaceholderText("Rechercher un nom, un dossier ou une racine...")

    widget.status_filter = QComboBox()
    widget.status_filter.setObjectName("LibraryStatusFilter")
    widget.status_filter.addItem("Tous les statuts", "all")
    widget.status_filter.addItem("Normaux", "normal")
    widget.status_filter.addItem("Non indexes", "non_indexed")
    widget.status_filter.addItem("A analyser", "needs_analysis")
    widget.status_filter.addItem("Fichiers manquants", "missing")

    header.addWidget(widget.title_label)
    header.addStretch(1)
    header.addWidget(widget.count_label)
    header.addWidget(widget.search_input, 1)
    header.addWidget(widget.status_filter)

    main_layout.addLayout(header)

    widget.splitter = QSplitter(Qt.Orientation.Horizontal)
    widget.splitter.setObjectName("LibrarySplitter")

    widget.nav_panel = QWidget()
    widget.nav_panel.setObjectName("LibraryNavPanel")
    nav_layout = QVBoxLayout(widget.nav_panel)
    nav_layout.setContentsMargins(8, 8, 8, 8)
    nav_layout.setSpacing(8)

    widget.nav_title = QLabel("Navigation")
    widget.nav_title.setObjectName("LibrarySectionTitle")
    widget.tree = QTreeWidget()
    widget.tree.setObjectName("LibraryTree")
    widget.tree.setHeaderHidden(True)
    widget.tree.setIndentation(14)
    nav_layout.addWidget(widget.nav_title)
    nav_layout.addWidget(widget.tree, 1)

    widget.table_panel = QWidget()
    widget.table_panel.setObjectName("LibraryTablePanel")
    table_layout = QVBoxLayout(widget.table_panel)
    table_layout.setContentsMargins(8, 8, 8, 8)
    table_layout.setSpacing(8)

    widget.table_title = QLabel("Samples indexes")
    widget.table_title.setObjectName("LibrarySectionTitle")
    widget.table = QTableWidget(0, 6)
    widget.table.setObjectName("LibraryTable")
    widget.table.setHorizontalHeaderLabels(["Nom", "Dossier", "Racine", "Duree", "RMS", "Statut"])
    widget.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.table.setAlternatingRowColors(False)
    widget.table.setSortingEnabled(True)
    widget.table.verticalHeader().setVisible(False)
    widget.table.setShowGrid(False)
    widget.table.setWordWrap(False)
    table_layout.addWidget(widget.table_title)
    table_layout.addWidget(widget.table, 1)

    widget.splitter.addWidget(widget.nav_panel)
    widget.splitter.addWidget(widget.table_panel)
    widget.splitter.addWidget(widget.detail_widget)
    widget.splitter.setSizes([220, 520, 460])

    main_layout.addWidget(widget.splitter, 1)

    apply_styles(widget)


def apply_styles(widget) -> None:
    palette = theme.manager.p
    widget.setStyleSheet(
        f"""
        QWidget#LibraryRoot {{
            background: {palette.BG_DARK};
        }}

        QLabel#LibraryTitle {{
            color: {palette.TEXT};
            font-size: 16px;
            font-weight: 700;
        }}
        QLabel#LibraryCount {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#LibrarySectionTitle {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
            font-weight: 600;
        }}
        QLineEdit#LibrarySearch,
        QComboBox#LibraryStatusFilter {{
            background: {palette.BG_MEDIUM};
            color: {palette.TEXT};
            border: 1px solid {palette.BORDER};
            border-radius: 8px;
            padding: 6px 8px;
        }}
        QWidget#LibraryNavPanel,
        QWidget#LibraryTablePanel,
        QWidget#LibraryDetailPanel {{
            background: {palette.BG_MEDIUM};
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 10px;
        }}
        QTreeWidget#LibraryTree,
        QTableWidget#LibraryTable {{
            background: transparent;
            color: {palette.TEXT};
            border: none;
            outline: none;
        }}
        QTreeWidget#LibraryTree::item,
        QTableWidget#LibraryTable::item {{
            padding: 6px 4px;
            border: none;
        }}
        QTreeWidget#LibraryTree::item:selected,
        QTableWidget#LibraryTable::item:selected {{
            background: {palette.BG_HOVER};
            color: {palette.TEXT};
        }}
        QTreeWidget#LibraryTree::item:hover,
        QTableWidget#LibraryTable::item:hover {{
            background: {palette.BG_HOVER};
        }}
        QHeaderView::section {{
            background: {palette.BG_CARD};
            color: {palette.TEXT_MUTED};
            border: none;
            border-bottom: 1px solid {palette.BORDER};
            padding: 6px 8px;
            font-weight: 600;
        }}
        """
    )
