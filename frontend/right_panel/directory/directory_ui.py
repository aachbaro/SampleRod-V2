"""
Directory UI (Builder + Style Tokens)
"""

from __future__ import annotations

import os

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme

from .directory_list_widget import DirectoryListWidget

BTN_SIZE = 24
BTN_ICON = 10

ICON_PLAY = "fa5s.play"
ICON_PAUSE = "fa5s.pause"
ICON_DELETE = "fa5s.trash-alt"

ICON_NORMAL = "#cfcfcf"
ICON_HOVER = "#111111"


def build_directory_widget_ui(widget) -> None:
    widget.setObjectName("DirectoryWidget")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)

    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)

    widget.choose_root_button = QPushButton("Choisir un dossier")
    widget.choose_root_button.setObjectName("DirectoryChooseButton")
    widget.choose_root_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.choose_root_button.clicked.connect(widget.choose_root_directory)

    widget.up_button = QPushButton("Monter")
    widget.up_button.setObjectName("DirectoryUpButton")
    widget.up_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.up_button.clicked.connect(widget.go_to_parent_directory)

    widget.path_label = QLabel("Aucun dossier")
    widget.path_label.setObjectName("DirectoryPathLabel")
    widget.path_label.setWordWrap(True)

    widget.status_label = QLabel("Non indexe")
    widget.status_label.setObjectName("DirectoryStatusLabel")

    widget.index_button = QPushButton("Indexer ce dossier")
    widget.index_button.setObjectName("DirectoryIndexButton")
    widget.index_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.index_button.clicked.connect(widget.index_current_directory)

    header.addWidget(widget.choose_root_button, 0, alignment=Qt.AlignmentFlag.AlignLeft)
    header.addWidget(widget.up_button, 0, alignment=Qt.AlignmentFlag.AlignLeft)
    header.addWidget(widget.path_label, 1)
    header.addWidget(widget.status_label, 0, alignment=Qt.AlignmentFlag.AlignRight)
    header.addWidget(widget.index_button, 0, alignment=Qt.AlignmentFlag.AlignRight)

    widget.progress_label = QLabel("")
    widget.progress_label.setObjectName("DirectoryProgressLabel")
    widget.progress_label.setVisible(False)

    widget.index_progress = QProgressBar()
    widget.index_progress.setObjectName("DirectoryProgressBar")
    widget.index_progress.setTextVisible(True)
    widget.index_progress.setVisible(False)

    widget.browser_splitter = QSplitter(Qt.Orientation.Horizontal)
    widget.browser_splitter.setObjectName("DirectoryBrowserSplitter")

    widget.tree_panel = QWidget()
    widget.tree_panel.setObjectName("DirectoryTreePanel")
    tree_layout = QVBoxLayout(widget.tree_panel)
    tree_layout.setContentsMargins(8, 8, 8, 8)
    tree_layout.setSpacing(8)

    tree_header_layout = QHBoxLayout()
    tree_header_layout.setContentsMargins(0, 0, 0, 0)
    tree_header_layout.setSpacing(4)
    widget.tree_title = QLabel("Arborescence")
    widget.tree_title.setObjectName("DirectorySectionTitle")
    widget.add_folder_button = QPushButton("+")
    widget.add_folder_button.setObjectName("DirectoryAddFolderBtn")
    widget.add_folder_button.setFixedSize(22, 22)
    widget.add_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.add_folder_button.setToolTip("Choisir un dossier racine")
    widget.add_folder_button.clicked.connect(widget.choose_root_directory)
    tree_header_layout.addWidget(widget.tree_title)
    tree_header_layout.addStretch(1)
    tree_header_layout.addWidget(widget.add_folder_button)

    widget.tree_view = QTreeView()
    widget.tree_view.setObjectName("DirectoryTree")
    widget.tree_view.setHeaderHidden(True)
    tree_layout.addLayout(tree_header_layout)
    tree_layout.addWidget(widget.tree_view, 1)

    widget.files_panel = QWidget()
    widget.files_panel.setObjectName("DirectoryFilesPanel")
    files_layout = QVBoxLayout(widget.files_panel)
    files_layout.setContentsMargins(8, 8, 8, 8)
    files_layout.setSpacing(8)

    files_header = QHBoxLayout()
    files_header.setContentsMargins(0, 0, 0, 0)
    files_header.setSpacing(8)
    widget.current_folder_label = QLabel("Fichiers audio")
    widget.current_folder_label.setObjectName("DirectorySectionTitle")
    widget.files_count_label = QLabel("0 fichier")
    widget.files_count_label.setObjectName("DirectoryFilesCount")
    files_header.addWidget(widget.current_folder_label)
    files_header.addStretch(1)
    files_header.addWidget(widget.files_count_label)

    widget.list_widget = DirectoryListWidget(widget)
    widget.list_widget.setObjectName("DirectoryList")
    widget.list_widget.setSpacing(8)
    # Marge droite : évite que la scrollbar recouvre la bordure arrondie du panel
    widget.list_widget.setViewportMargins(0, 0, 4, 0)

    files_layout.addLayout(files_header)
    files_layout.addWidget(widget.list_widget, 1)

    widget.browser_splitter.addWidget(widget.tree_panel)
    widget.browser_splitter.addWidget(widget.files_panel)
    widget.browser_splitter.setSizes([220, 760])

    layout.addLayout(header)
    layout.addWidget(widget.progress_label)
    layout.addWidget(widget.index_progress)
    layout.addWidget(widget.browser_splitter, 1)

    apply_styles(widget)


def set_directory_path(widget, path: str) -> None:
    lbl = getattr(widget, "path_label", None)
    if lbl is None:
        return
    lbl.setText(path)
    lbl.setToolTip(path)
    current_folder_label = getattr(widget, "current_folder_label", None)
    if current_folder_label is not None:
        current_folder_label.setText(f"Dossier courant: {os.path.basename(path) or path}")


def build_directory_item_ui(
    item_widget,
    file_path: str,
    *,
    status_text: str,
    meta_text: str,
    on_start_rename,
    on_submit_rename,
    on_toggle_preview,
    on_delete,
) -> None:
    item_widget.setObjectName("DirectoryRow")
    item_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    item_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    item_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    item_widget.name_label = QLabel(os.path.basename(file_path))
    item_widget.name_label.setObjectName("DirectoryItemName")
    item_widget.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    item_widget.name_label.setMinimumWidth(0)
    item_widget.name_label.mouseDoubleClickEvent = on_start_rename  # type: ignore[assignment]

    item_widget.meta_label = QLabel(meta_text)
    item_widget.meta_label.setObjectName("DirectoryItemMeta")
    item_widget.meta_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    item_widget.meta_label.setMinimumWidth(0)
    item_widget.meta_label.setVisible(bool(meta_text))

    item_widget.status_badge = QLabel(status_text)
    item_widget.status_badge.setObjectName("DirectoryStatusBadge")
    item_widget.status_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    item_widget.rename_input = QLineEdit(base_name)
    item_widget.rename_input.setObjectName("DirectoryRenameInput")
    item_widget.rename_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    item_widget.rename_input.setMinimumWidth(120)
    item_widget.rename_input.hide()
    item_widget.rename_input.editingFinished.connect(on_submit_rename)

    palette = theme.manager.p
    bg_hover = (
        QColor(255, 255, 255, 210) if theme.manager.is_dark()
        else QColor(30, 30, 30, 55)
    )
    item_widget.play_button = HoverIconButton(
        icon_name=ICON_PLAY,
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=palette.TEXT_MUTED,
        icon_color_hover="#111111",
        border_color=palette.BG_CARD,
        bg_hover=bg_hover,
        parent=item_widget,
    )
    item_widget.play_button.clicked.connect(on_toggle_preview)
    item_widget.play_button.setToolTip("Pre-ecouter")
    item_widget.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.play_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    item_widget.playback_slider = QSlider(Qt.Orientation.Horizontal, item_widget)
    item_widget.playback_slider.setObjectName("DirectoryPlaybackSlider")
    item_widget.playback_slider.setRange(0, 1000)
    item_widget.playback_slider.setValue(0)
    item_widget.playback_slider.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.playback_slider.setFixedHeight(24)
    item_widget.playback_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    item_widget.time_label = QLabel("00:00 / 00:00")
    item_widget.time_label.setObjectName("DirectoryTimeLabel")
    max_time_str = "00:00 / 00:00"
    time_w = item_widget.time_label.fontMetrics().horizontalAdvance(max_time_str) + 4
    item_widget.time_label.setFixedSize(time_w, 24)
    item_widget.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item_widget.time_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    text_container = QWidget(item_widget)
    text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    text_layout = QVBoxLayout(text_container)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(5)

    top_row = QHBoxLayout()
    top_row.setContentsMargins(0, 0, 0, 0)
    top_row.setSpacing(6)

    title_stack = QVBoxLayout()
    title_stack.setContentsMargins(0, 0, 0, 0)
    title_stack.setSpacing(2)
    title_stack.addWidget(item_widget.name_label)
    title_stack.addWidget(item_widget.rename_input)

    top_row.addLayout(title_stack, 1)
    top_row.addWidget(item_widget.status_badge, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

    meta_row = QHBoxLayout()
    meta_row.setContentsMargins(0, 0, 0, 0)
    meta_row.setSpacing(6)
    meta_row.addWidget(item_widget.meta_label, 1, alignment=Qt.AlignmentFlag.AlignLeft)

    playback_row = QHBoxLayout()
    playback_row.setContentsMargins(0, 0, 0, 0)
    playback_row.setSpacing(8)
    playback_row.addWidget(item_widget.play_button, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
    playback_row.addWidget(item_widget.playback_slider, 1)
    playback_row.addWidget(item_widget.time_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

    text_layout.addLayout(top_row)
    text_layout.addLayout(meta_row)
    text_layout.addLayout(playback_row)

    # Bouton supprimer (coin droit de la carte)
    palette = theme.manager.p
    bg_hover_del = QColor(180, 40, 40, 220)
    item_widget.delete_button = HoverIconButton(
        icon_name=ICON_DELETE,
        size=BTN_SIZE,
        icon_size=BTN_ICON,
        icon_color_normal=palette.TEXT_MUTED,
        icon_color_hover="#ffffff",
        border_color="transparent",
        border_color_hover="transparent",
        bg_hover=bg_hover_del,
        parent=item_widget,
    )
    item_widget.delete_button.clicked.connect(on_delete)
    item_widget.delete_button.setToolTip("Supprimer ce fichier")
    item_widget.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)

    layout = QHBoxLayout(item_widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)
    layout.addWidget(text_container, 1)
    layout.addWidget(item_widget.delete_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def set_item_playing(item_widget, playing: bool) -> None:
    palette = theme.manager.p
    icon_name = ICON_PAUSE if playing else ICON_PLAY
    if hasattr(item_widget.play_button, "set_icon_pair"):
        item_widget.play_button.set_icon_pair(
            icon_name,
            icon_color_normal=palette.TEXT_MUTED,
            icon_color_hover="#111111",
        )
    else:
        item_widget.play_button.setIcon(qta.icon(icon_name, color="lightgray"))


def restyle_item(item_widget) -> None:
    palette = theme.manager.p
    bg_hover = (
        QColor(255, 255, 255, 210) if theme.manager.is_dark()
        else QColor(30, 30, 30, 55)
    )
    item_widget.play_button.set_bg_hover(bg_hover)
    item_widget.play_button.update_colors(palette.TEXT_MUTED, "#111111", palette.BG_CARD)


def apply_styles(widget) -> None:
    palette = theme.manager.p
    widget.setStyleSheet(
        f"""
        QWidget#DirectoryWidget {{
            background: transparent;
            border: none;
        }}

        QLabel#DirectoryPathLabel {{
            color: {palette.TEXT};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel#DirectorySectionTitle,
        QLabel#DirectoryFilesCount,
        QLabel#DirectoryDetailMeta,
        QLabel#DirectoryDetailPath {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#DirectoryDetailTitle {{
            color: {palette.TEXT};
            font-size: 14px;
            font-weight: 700;
        }}
        QLabel#DirectoryDetailStatus,
        QLabel#DirectoryStatusLabel {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
            padding: 3px 10px;
            background: {palette.BG_CARD};
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 10px;
        }}
        QLabel#DirectoryStatusBadge {{
            color: {palette.TEXT};
            font-size: 10px;
            font-weight: 600;
            padding: 3px 8px;
            background: {palette.BG_CARD};
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 10px;
        }}
        QLabel#DirectoryProgressLabel {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
        }}
        QPushButton#DirectoryAddFolderBtn {{
            background: {palette.BG_CARD};
            color: {palette.TEXT};
            border: 1px solid {palette.BORDER};
            border-radius: 6px;
            font-size: 14px;
            font-weight: 700;
            padding: 0;
        }}
        QPushButton#DirectoryAddFolderBtn:hover {{
            background: {palette.BG_HOVER};
            border-color: {palette.WARNING};
            color: {palette.WARNING};
        }}
        QPushButton#DirectoryChooseButton,
        QPushButton#DirectoryUpButton,
        QPushButton#DirectoryIndexButton {{
            background: {palette.BG_CARD};
            color: {palette.TEXT};
            border: 1px solid {palette.BORDER};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QPushButton#DirectoryChooseButton:hover,
        QPushButton#DirectoryUpButton:hover,
        QPushButton#DirectoryIndexButton:hover {{
            background: {palette.BG_HOVER};
            border-color: {palette.WARNING};
        }}
        QPushButton#DirectoryChooseButton:disabled,
        QPushButton#DirectoryUpButton:disabled,
        QPushButton#DirectoryIndexButton:disabled {{
            color: {palette.TEXT_MUTED};
            border-color: {palette.BORDER_LIGHT};
        }}
        QProgressBar#DirectoryProgressBar {{
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 6px;
            background: {palette.BG_CARD};
            color: {palette.TEXT};
            text-align: center;
            min-height: 16px;
        }}
        QProgressBar#DirectoryProgressBar::chunk {{
            background: {palette.WARNING};
            border-radius: 5px;
        }}

        QWidget#DirectoryTreePanel,
        QWidget#DirectoryFilesPanel,
        QWidget#DirectoryDetailPanel {{
            background-color: {palette.BG_MEDIUM};
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 10px;
        }}
        QTreeView#DirectoryTree {{
            background: transparent;
            color: {palette.TEXT};
            border: none;
            outline: none;
        }}
        QTreeView#DirectoryTree::item {{
            padding: 5px 4px;
        }}
        QTreeView#DirectoryTree::item:selected {{
            background: {palette.BG_HOVER};
            color: {palette.TEXT};
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
            background-color: {palette.BG_MEDIUM};
            border: 1px solid {palette.BORDER_LIGHT};
            border-radius: 10px;
        }}
        QWidget#DirectoryRow[focused="true"] {{
            background-color: {palette.BG_HOVER};
            border-color: {palette.WARNING};
        }}
        QWidget#DirectoryRow:hover {{
            background-color: {palette.BG_HOVER};
            border-color: {palette.BORDER};
        }}

        QLabel#DirectoryItemName {{
            color: {palette.TEXT};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel#DirectoryItemMeta {{
            color: {palette.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#DirectoryTimeLabel {{
            color: {palette.TEXT_MUTED};
            font-size: 10px;
        }}
        QLineEdit#DirectoryRenameInput {{
            background-color: {palette.BG_CARD};
            color: {palette.TEXT};
            border: 1px solid {palette.WARNING};
            border-radius: 6px;
            padding: 4px 6px;
        }}
        QSlider#DirectoryPlaybackSlider::groove:horizontal {{
            border: none;
            height: 6px;
            background: {palette.BORDER};
            margin: 0px;
            border-radius: 3px;
        }}
        QSlider#DirectoryPlaybackSlider::sub-page:horizontal {{
            background: {palette.TEXT_MUTED};
            border-radius: 3px;
        }}
        QSlider#DirectoryPlaybackSlider::add-page:horizontal {{
            background: {palette.BORDER};
            border-radius: 3px;
        }}
        QSlider#DirectoryPlaybackSlider::handle:horizontal {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {palette.TEXT_MUTED}, stop:1 {palette.BORDER_LIGHT});
            border: 1px solid {palette.BORDER_LIGHT};
            width: 12px;
            margin: -3px 0;
            border-radius: 6px;
        }}
        QWidget#DirectoryDetailPanel QPushButton {{
            background: {palette.BG_CARD};
            color: {palette.TEXT};
            border: 1px solid {palette.BORDER};
            border-radius: 8px;
            padding: 6px 8px;
        }}
        QWidget#DirectoryDetailPanel QPushButton:hover {{
            background: {palette.BG_HOVER};
            border-color: {palette.BORDER_LIGHT};
        }}
        QWidget#DirectoryDetailPanel QPushButton:disabled {{
            color: {palette.TEXT_MUTED};
            border-color: {palette.BORDER_LIGHT};
        }}
        """
    )
