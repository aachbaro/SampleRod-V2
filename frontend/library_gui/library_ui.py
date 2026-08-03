# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Module de construction de l'interface graphique de la Bibliotheque.
# - Separe la logique UI pure (placement des widgets) du comportement
#   (gestion des evenements et des donnees dans LibraryWidget).
#
# FONCTIONS (sommaire)
# - build_library_widget_ui()  : cree et assemble tous les widgets de la vue
# - apply_styles()             : applique le QSS dynamique via le theme courant
#
# LIENS CLES
# - frontend/library_gui/library_widget.py  : appelant ; reçoit les attributs crees ici
# - frontend/styles/theme.py               : source des couleurs
# -----------------------------------------------------------------------------

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
from frontend.ui import IconButton


def build_library_widget_ui(widget) -> None:
    """Construit toute l'interface de la Bibliotheque et attache les attributs au widget.

    Structure :
    - Header : titre, compteur, barre de recherche, filtre de statut.
    - Splitter horizontal :
        - Panneau de navigation (QTreeWidget) a gauche.
        - Tableau de samples (QTableWidget, 8 colonnes) au centre.
        - Detail du sample (LibraryDetailWidget) a droite.

    Les attributs crees (tree, table, search_input, etc.) sont directement
    attaches a `widget` pour que LibraryWidget puisse y acceder.
    """
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

    widget.nav_toggle_button = IconButton("chevron-left", tooltip="Masquer la navigation", size="s")

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

    widget.scale_filter = QComboBox()
    widget.scale_filter.setObjectName("LibraryScaleFilter")
    widget.scale_filter.setMinimumWidth(190)
    widget.scale_filter.addItem("Toutes les gammes", "__all__")

    header.addWidget(widget.title_label)
    header.addWidget(widget.nav_toggle_button)
    header.addStretch(1)
    header.addWidget(widget.count_label)
    header.addWidget(widget.search_input, 1)
    header.addWidget(widget.status_filter)
    header.addWidget(widget.scale_filter)

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
    widget.table = QTableWidget(0, 8)
    widget.table.setObjectName("LibraryTable")
    widget.table.setHorizontalHeaderLabels(["Nom", "Gamme", "Dossier", "Racine", "Date", "Duree", "Poids", "Statut"])
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

    # Le detail passe SOUS la table plutot qu'a sa droite : en colonne il
    # mangeait la moitie de la largeur alors qu'il ne sert qu'a lire le sample
    # selectionne. La table recupere toute la place, le detail se reduit a une
    # bande compacte (quelques infos + la carte de lecture).
    widget.content_splitter = QSplitter(Qt.Orientation.Vertical)
    widget.content_splitter.setObjectName("LibraryContentSplitter")
    widget.content_splitter.setChildrenCollapsible(False)
    widget.content_splitter.addWidget(widget.table_panel)
    widget.content_splitter.addWidget(widget.detail_widget)
    widget.content_splitter.setStretchFactor(0, 1)
    widget.content_splitter.setStretchFactor(1, 0)
    widget.content_splitter.setSizes([700, 170])

    widget.splitter.addWidget(widget.nav_panel)
    widget.splitter.addWidget(widget.content_splitter)
    widget.splitter.setSizes([220, 900])

    main_layout.addWidget(widget.splitter, 1)

    apply_styles(widget)


def apply_styles(widget) -> None:
    """Applique la feuille de style QSS a partir des couleurs du theme courant."""
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
        QComboBox#LibraryStatusFilter,
        QComboBox#LibraryScaleFilter {{
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
            padding: 4px 6px;
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
        QLabel#LibraryDetailPath {{
            color: {palette.TEXT};
            font-size: 11px;
        }}
        QLabel#LibraryDetailMeta {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
        }}
        """
    )
