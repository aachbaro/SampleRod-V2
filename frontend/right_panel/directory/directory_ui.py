# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Constructeur d'UI et tokens de style pour le Directory tool.
# - Separe la construction du layout de la logique (directement dans
#   DirectoryWidget), suivant le meme pattern que library_ui.py.
#
# FONCTIONS (sommaire)
# - build_directory_widget_ui()  : layout principal du DirectoryWidget
# - build_directory_item_ui()    : carte "ligne" de la liste de fichiers
# - set_directory_path()         : met a jour breadcrumb + labels compat
# - _rebuild_breadcrumb()        : reconstruit les segments cliquables du breadcrumb
# - update_index_chip()          : passe le chip d'indexation entre 4 etats
# - set_item_playing()           : bascule l'icone play/pause d'une ligne
# - restyle_item()               : reapplique les couleurs du theme sur une ligne
# - apply_styles()               : QSS du widget principal (6 blocs separes)
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py    : appelle build_directory_widget_ui()
# - frontend/right_panel/directory/directory_item_widget.py : appelle build_directory_item_ui()
# - frontend/right_panel/directory/directory_list_widget.py : reference depuis build_directory_widget_ui
# - frontend/styles/theme.py                              : palettes de couleurs
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _accent_color() -> QColor:
    """Retourne la couleur ACCENT du theme courant sous forme de QColor."""
    try:
        return QColor(theme.manager.p.ACCENT)
    except Exception:
        return QColor(44, 198, 207)


# ---------------------------------------------------------------------------
# Widget principal
# ---------------------------------------------------------------------------

def build_directory_widget_ui(widget) -> None:
    """Construit le layout principal du DirectoryWidget.

    Attache les references de tous les sous-widgets directement sur `widget`
    (breadcrumb_widget, list_widget, index_button, compat_filter_row, etc.)
    pour que DirectoryWidget puisse y acceder sans stocker de sous-classes.

    Structure:
      header [breadcrumb | index_chip]
      index_progress  (barre mince pendant l'indexation)
      progress_label  (texte de progression)
      shortcuts_bar   (rappels clavier, affiche au focus)
      files_header    (compteur de fichiers)
      compat_filter_row (chip de filtre gamme, cache par defaut)
      list_widget     (liste des fichiers, prend tout l'espace restant)
    """
    widget.setObjectName("DirectoryWidget")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(6)

    # ── Header row: [Choisir] [↑] [breadcrumb…] [index chip]
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(6)

    widget.choose_root_button = QPushButton("Choisir")
    widget.choose_root_button.setObjectName("DirectoryChooseButton")
    widget.choose_root_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.choose_root_button.clicked.connect(widget.choose_root_directory)
    widget.choose_root_button.hide()

    widget.up_button = QPushButton("↑")
    widget.up_button.setObjectName("DirectoryUpButton")
    widget.up_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.up_button.setFixedSize(28, 28)
    widget.up_button.setToolTip("Dossier parent (←)")
    widget.up_button.clicked.connect(widget.go_to_parent_directory)
    widget.up_button.setText("↑")

    # Breadcrumb container — reconstructed on each navigation
    widget.breadcrumb_widget = QWidget()
    widget.breadcrumb_widget.setObjectName("DirectoryBreadcrumb")
    widget.breadcrumb_widget.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    widget._breadcrumb_layout = QHBoxLayout(widget.breadcrumb_widget)
    widget._breadcrumb_layout.setContentsMargins(4, 0, 4, 0)
    widget._breadcrumb_layout.setSpacing(0)
    # Initial placeholder
    _empty = QLabel("Aucun dossier")
    _empty.setObjectName("BreadcrumbEmpty")
    widget._breadcrumb_layout.addWidget(_empty)
    widget._breadcrumb_layout.addStretch(1)

    # path_label kept for backward compat (hidden)
    widget.path_label = QLabel("")
    widget.path_label.hide()

    widget.help_button = QPushButton("?")
    widget.help_button.setObjectName("DirectoryHelpButton")
    widget.help_button.setFixedSize(28, 28)
    widget.help_button.setToolTip(
        "Raccourcis\n↑↓ Sélectionner\nEspace Pré-écouter\n←/→ Reculer/avancer 1 s\n"
        "Entrée Ouvrir dans le Labo\nAlt+← Dossier parent\nAlt+→ Ouvrir le dossier\n"
        "F2 Renommer\nSuppr Supprimer"
    )

    # Commande stable : chaque clic relance une synchronisation récursive.
    widget.index_button = QPushButton("Synchroniser")
    widget.index_button.setObjectName("DirectoryIndexChip")
    widget.index_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.index_button.clicked.connect(widget.index_current_directory)

    # status_label kept for backward compat (hidden; text drives chip)
    widget.status_label = QLabel("Non indexe")
    widget.status_label.setObjectName("DirectoryStatusLabel")
    widget.status_label.hide()

    header.addWidget(widget.up_button)
    header.addWidget(widget.breadcrumb_widget, 1)
    header.addWidget(widget.help_button)

    summary = QHBoxLayout()
    summary.setContentsMargins(4, 2, 4, 2)
    summary_text = QVBoxLayout()
    summary_text.setContentsMargins(0, 0, 0, 0)
    summary_text.setSpacing(1)
    widget.files_count_label = QLabel("0 fichier audio")
    widget.files_count_label.setObjectName("DirectoryFilesCount")
    widget.index_summary_label = QLabel("0 indexé")
    widget.index_summary_label.setObjectName("DirectoryIndexSummary")
    summary_text.addWidget(widget.files_count_label)
    summary_text.addWidget(widget.index_summary_label)
    summary.addLayout(summary_text, 1)
    summary.addWidget(widget.index_button, 0, Qt.AlignmentFlag.AlignVCenter)

    # ── Progress / indexation feedback
    widget.progress_label = QLabel("")
    widget.progress_label.setObjectName("DirectoryProgressLabel")
    widget.progress_label.setVisible(False)

    widget.index_progress = QProgressBar()
    widget.index_progress.setObjectName("DirectoryProgressBar")
    widget.index_progress.setTextVisible(False)
    widget.index_progress.setFixedHeight(4)
    widget.index_progress.setVisible(False)

    # Conservée comme adaptateur interne, mais remplacée visuellement par ?.
    widget.shortcuts_bar = QWidget()
    widget.shortcuts_bar.setObjectName("DirectoryShortcutsBar")
    shortcuts_layout = QHBoxLayout(widget.shortcuts_bar)
    shortcuts_layout.setContentsMargins(6, 4, 6, 4)
    shortcuts_layout.setSpacing(18)
    for hint in [
        "↑↓ naviguer",
        "Espace preview",
        "→ avancer lecture",
        "Entrée labo",
        "← parent",
        "F2 renommer",
        "Suppr supprimer",
        "Clic droit actions",
    ]:
        lbl = QLabel(hint)
        lbl.setObjectName("DirectoryShortcutHint")
        shortcuts_layout.addWidget(lbl)
    shortcuts_layout.addStretch(1)
    widget.shortcuts_bar.hide()

    widget.list_count_label = QLabel("")
    widget.list_count_label.hide()

    # ── Compat filter row
    widget.compat_filter_row = QWidget()
    widget.compat_filter_row.setObjectName("DirectoryCompatFilterRow")
    compat_layout = QHBoxLayout(widget.compat_filter_row)
    compat_layout.setContentsMargins(8, 4, 8, 4)
    compat_layout.setSpacing(6)

    widget.compat_filter_label = QLabel("")
    widget.compat_filter_label.setObjectName("DirectoryCompatFilterLabel")

    widget.compat_filter_clear_button = QPushButton("×")
    widget.compat_filter_clear_button.setObjectName("DirectoryCompatFilterClearBtn")
    widget.compat_filter_clear_button.setFixedSize(22, 22)
    widget.compat_filter_clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.compat_filter_clear_button.setToolTip("Effacer le filtre de gamme")
    widget.compat_filter_clear_button.clicked.connect(widget.clear_compatible_scales_filter)

    compat_layout.addWidget(widget.compat_filter_label)
    compat_layout.addWidget(widget.compat_filter_clear_button)
    compat_layout.addStretch(1)
    widget.compat_filter_row.setVisible(False)

    def _clear_compat_filter_from_double_click(event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            widget.clear_compatible_scales_filter()
            event.accept()
            return
        QWidget.mouseDoubleClickEvent(widget.compat_filter_label, event)

    widget.compat_filter_label.mouseDoubleClickEvent = _clear_compat_filter_from_double_click  # type: ignore[assignment]

    # ── Main list
    widget.list_widget = DirectoryListWidget(widget)
    widget.list_widget.setObjectName("DirectoryList")
    widget.list_widget.setSpacing(1)
    widget.list_widget.setViewportMargins(0, 0, 12, 0)

    # ── Hidden tree view — kept so _init_tree_model / tree signals still work
    widget.tree_panel = QWidget()
    widget.tree_panel.setObjectName("DirectoryTreePanel")
    widget.tree_panel.hide()
    _tree_layout = QVBoxLayout(widget.tree_panel)
    _tree_layout.setContentsMargins(0, 0, 0, 0)
    widget.tree_view = QTreeView(widget.tree_panel)
    widget.tree_view.setObjectName("DirectoryTree")
    widget.tree_view.setHeaderHidden(True)
    _tree_layout.addWidget(widget.tree_view)

    # Stub attrs used elsewhere
    widget.tree_title = QLabel("Arborescence")
    widget.add_folder_button = QPushButton("+")
    widget.add_folder_button.clicked.connect(widget.choose_root_directory)

    # browser_splitter / files_panel kept as no-op stubs for backward compat
    widget.browser_splitter = QSplitter(Qt.Orientation.Horizontal)
    widget.browser_splitter.hide()
    widget.files_panel = QWidget()
    widget.files_panel.hide()
    widget.current_folder_label = QLabel()

    # ── Assemble
    layout.addLayout(header)
    layout.addLayout(summary)
    layout.addWidget(widget.index_progress)
    layout.addWidget(widget.progress_label)
    layout.addWidget(widget.compat_filter_row)
    layout.addWidget(widget.list_widget, 1)

    apply_styles(widget)


# ---------------------------------------------------------------------------
# Breadcrumb helpers
# ---------------------------------------------------------------------------

def set_directory_path(widget, path: str) -> None:
    """Appelé par open_directory : met à jour le breadcrumb et les labels compat."""
    lbl = getattr(widget, "path_label", None)
    if lbl is not None:
        lbl.setText(path)
        lbl.setToolTip(path)

    current_folder_label = getattr(widget, "current_folder_label", None)
    if current_folder_label is not None:
        current_folder_label.setText(
            f"Dossier courant: {os.path.basename(path) or path}"
        )

    _rebuild_breadcrumb(widget, path)


def _rebuild_breadcrumb(widget, path: str) -> None:
    """Reconstruit les segments cliquables du breadcrumb."""
    bc_layout = getattr(widget, "_breadcrumb_layout", None)
    if bc_layout is None:
        return

    # Clear
    while bc_layout.count():
        item = bc_layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()

    if not path:
        lbl = QLabel("Aucun dossier")
        lbl.setObjectName("BreadcrumbEmpty")
        bc_layout.addWidget(lbl)
        bc_layout.addStretch(1)
        return

    root_path = getattr(widget, "root_dir", "") or ""
    norm_path = os.path.normpath(path)
    norm_root = os.path.normpath(root_path) if root_path else ""

    # Collect ancestors from current dir up to root
    segments: list[tuple[str, str]] = []  # (display_label, full_path)
    current = norm_path
    while True:
        head, tail = os.path.split(current)
        if tail:
            segments.append((tail, current))
        else:
            # Drive root (e.g. "C:\\")
            segments.append((current, current))
            break
        if norm_root and current == norm_root:
            break
        if not head or head == current:
            break
        current = head
    segments.reverse()

    # Cap to 4 visible segments — show "…" for elided prefix
    if len(segments) > 4:
        segments = [("…", None)] + segments[-3:]

    for i, (label, seg_path) in enumerate(segments):
        if i > 0:
            sep = QLabel("  /  ")
            sep.setObjectName("BreadcrumbSep")
            bc_layout.addWidget(sep)

        is_last = i == len(segments) - 1
        shown = QFontMetrics(widget.font()).elidedText(
            label, Qt.TextElideMode.ElideMiddle, 120
        )
        btn = QPushButton(shown)
        btn.setToolTip(str(seg_path or label))
        btn.setObjectName("BreadcrumbCurrent" if is_last else "BreadcrumbSegment")
        btn.setFlat(True)
        btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        btn.setMaximumWidth(130)
        if not is_last and seg_path:
            _nav_path = seg_path  # capture for lambda
            btn.clicked.connect(
                lambda _checked=False, p=_nav_path: widget.open_directory(p)
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            btn.setCursor(Qt.CursorShape.ArrowCursor)
        bc_layout.addWidget(btn)

    bc_layout.addStretch(1)


def update_index_chip(widget, status_key: str, tracked: int = 0, total: int = 0) -> None:
    """
    Met à jour l'index chip selon l'état d'indexation.
    status_key: "none" | "partial" | "full" | "busy"
    """
    btn = getattr(widget, "index_button", None)
    if btn is None:
        return

    if status_key == "busy":
        btn.setText("Synchronisation…")
        btn.setProperty("chipState", "busy")
        btn.setEnabled(False)
    elif status_key == "full":
        btn.setText("Synchroniser")
        btn.setProperty("chipState", "full")
        btn.setEnabled(True)
    elif status_key == "partial":
        btn.setText("Synchroniser")
        btn.setProperty("chipState", "partial")
        btn.setEnabled(True)
    else:  # "none"
        btn.setText("Synchroniser")
        btn.setProperty("chipState", "none")
        btn.setEnabled(True)

    btn.style().unpolish(btn)
    btn.style().polish(btn)


# ---------------------------------------------------------------------------
# Item card
# ---------------------------------------------------------------------------

def build_directory_item_ui(
    item_widget,
    file_path: str,
    *,
    status_text: str,
    meta_text: str,
    on_start_rename,
    on_submit_rename,
    on_toggle_preview,
    on_find_compatibles,
    on_delete,
) -> None:
    """Construit la carte "ligne" d'un fichier audio (DirectoryListItemWidget).

    Attache sur `item_widget`:
      play_button, name_label, rename_input, duration_chip,
      key_badge, status_badge, meta_label, playback_slider, time_label,
      labo_button, delete_button.

    Layout interne:
      [play_button] [text_container]
        text_container:
          name_row: [name/rename] [key_badge] [status_badge]
          playback_row: [slider] [time_label]
    """
    item_widget.setObjectName("DirectoryRow")
    item_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    item_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    item_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    palette = theme.manager.p

    # ── Round play button
    accent = _accent_color()
    accent_hover = QColor(accent.red(), accent.green(), accent.blue(), 200)
    item_widget.play_button = HoverIconButton(
        icon_name=ICON_PLAY,
        size=28,
        icon_size=11,
        icon_color_normal=palette.TEXT_MUTED,
        icon_color_hover="#ffffff",
        border_color=palette.BORDER_LIGHT,
        bg_hover=accent_hover,
        parent=item_widget,
    )
    item_widget.play_button.setObjectName("DirectoryPlayBtn")
    item_widget.play_button.clicked.connect(on_toggle_preview)
    item_widget.play_button.setToolTip("Pre-ecouter (Espace)")
    item_widget.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.play_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ── Name label
    item_widget.name_label = QLabel(os.path.basename(file_path))
    item_widget.name_label.setObjectName("DirectoryItemName")
    item_widget.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    item_widget.name_label.setMinimumWidth(0)
    item_widget.name_label.setToolTip(file_path)
    item_widget.name_label.mouseDoubleClickEvent = on_start_rename  # type: ignore[assignment]

    # ── Rename input
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    item_widget.rename_input = QLineEdit(base_name)
    item_widget.rename_input.setObjectName("DirectoryRenameInput")
    item_widget.rename_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    item_widget.rename_input.setMinimumWidth(120)
    item_widget.rename_input.hide()
    item_widget.rename_input.editingFinished.connect(on_submit_rename)

    # ── Duration chip
    item_widget.duration_chip = QLabel("", item_widget)
    item_widget.duration_chip.setObjectName("DirectoryDurationChip")
    item_widget.duration_chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    item_widget.duration_chip.setFixedWidth(48)
    item_widget.duration_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item_widget.duration_chip.setVisible(False)

    # ── Key / note badge (clickable, shown when note detected)
    item_widget.key_badge = QPushButton("")
    item_widget.key_badge.setObjectName("DirectoryKeyBadge")
    item_widget.key_badge.setFixedHeight(20)
    item_widget.key_badge.setFixedWidth(38)
    item_widget.key_badge.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.key_badge.setVisible(False)
    item_widget.key_badge.clicked.connect(on_find_compatibles)

    # ── Status badge
    item_widget.status_badge = QLabel(status_text)
    item_widget.status_badge.setObjectName("DirectoryStatusBadge")
    item_widget.status_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    item_widget.status_slot = QWidget(item_widget)
    item_widget.status_slot.setObjectName("DirectoryStatusSlot")
    item_widget.status_slot.setFixedSize(74, 24)
    status_slot_layout = QHBoxLayout(item_widget.status_slot)
    status_slot_layout.setContentsMargins(0, 0, 0, 0)
    status_slot_layout.addWidget(item_widget.status_badge)

    item_widget.key_slot = QWidget(item_widget)
    item_widget.key_slot.setObjectName("DirectoryKeySlot")
    item_widget.key_slot.setFixedSize(38, 24)
    key_slot_layout = QHBoxLayout(item_widget.key_slot)
    key_slot_layout.setContentsMargins(0, 0, 0, 0)
    key_slot_layout.addWidget(item_widget.key_badge)

    # ── meta_label kept for backward compat (hidden)
    item_widget.meta_label = QLabel(meta_text, item_widget)
    item_widget.meta_label.setObjectName("DirectoryItemMeta")
    item_widget.meta_label.hide()

    # Slider commun aux modes autonome et Réserve.
    item_widget.playback_slider = QSlider(Qt.Orientation.Horizontal, item_widget)
    item_widget.playback_slider.setObjectName("DirectoryPlaybackSlider")
    item_widget.playback_slider.setRange(0, 1000)
    item_widget.playback_slider.setValue(0)
    item_widget.playback_slider.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.playback_slider.setFixedHeight(14)
    item_widget.playback_slider.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )

    # ── Time label
    item_widget.time_label = QLabel("00:00 / 00:00")
    item_widget.time_label.setObjectName("DirectoryTimeLabel")
    max_time_str = "00:00 / 00:00"
    time_w = item_widget.time_label.fontMetrics().horizontalAdvance(max_time_str) + 4
    item_widget.time_label.setFixedSize(time_w, 18)
    item_widget.time_label.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    item_widget.time_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ── Legacy action button kept off-layout for compatibility
    item_widget.labo_button = QPushButton("→ Labo", item_widget)
    item_widget.labo_button.setObjectName("DirectoryLaboBtn")
    item_widget.labo_button.setCursor(Qt.CursorShape.PointingHandCursor)
    item_widget.labo_button.setToolTip("Envoyer au labo (Entrée)")
    item_widget.labo_button.setVisible(False)
    item_widget.labo_button.clicked.connect(
        lambda: item_widget.parent_widget.send_path_to_composer(item_widget.file_path)
    )

    # ── Delete button — kept for context menu, NOT added to layout
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
    item_widget.delete_button.setVisible(False)  # only via context menu

    # ── Text container
    text_container = QWidget(item_widget)
    text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    text_container.setMinimumWidth(0)
    text_layout = QVBoxLayout(text_container)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(4)

    compact_reserve = bool(getattr(item_widget.parent_widget, "embedded_in_reserve", False))

    # Name row historique pour le mode autonome.
    name_row = QHBoxLayout()
    name_row.setContentsMargins(0, 0, 0, 0)
    name_row.setSpacing(4)
    name_stack = QVBoxLayout()
    name_stack.setContentsMargins(0, 0, 0, 0)
    name_stack.setSpacing(0)
    name_stack.addWidget(item_widget.name_label)
    name_stack.addWidget(item_widget.rename_input)
    name_row.addLayout(name_stack, 1)
    if not compact_reserve:
        name_row.addWidget(item_widget.status_slot, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(item_widget.key_slot, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(item_widget.duration_chip, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

    # Playback row: [slider ← stretch] [time]
    playback_row = QHBoxLayout()
    playback_row.setContentsMargins(0, 0, 0, 0)
    playback_row.setSpacing(6)
    if not compact_reserve:
        playback_row.addWidget(item_widget.playback_slider, 1)
        playback_row.addWidget(item_widget.time_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
    else:
        item_widget.time_label.hide()

    text_layout.addLayout(name_row)
    if not compact_reserve:
        text_layout.addLayout(playback_row)

    # ── Card layout
    layout = QHBoxLayout(item_widget)
    layout.setContentsMargins(6, 4, 8, 4)
    layout.setSpacing(8)
    layout.addWidget(item_widget.play_button, 0, Qt.AlignmentFlag.AlignVCenter)
    if compact_reserve:
        text_container.setFixedWidth(180)
        layout.addWidget(text_container, 0)
        layout.addWidget(item_widget.playback_slider, 1)
        layout.addWidget(item_widget.duration_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(item_widget.status_slot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(item_widget.key_slot, 0, Qt.AlignmentFlag.AlignVCenter)
        item_widget.setMinimumHeight(38)
        item_widget.setMaximumHeight(38)
    else:
        layout.addWidget(text_container, 1)


# ---------------------------------------------------------------------------
# State updates
# ---------------------------------------------------------------------------

def set_item_playing(item_widget, playing: bool) -> None:
    """Bascule l'icone du bouton play entre play et pause selon l'etat."""
    palette = theme.manager.p
    icon_name = ICON_PAUSE if playing else ICON_PLAY
    if hasattr(item_widget.play_button, "set_icon_pair"):
        item_widget.play_button.set_icon_pair(
            icon_name,
            icon_color_normal=palette.TEXT_MUTED,
            icon_color_hover="#ffffff",
        )
    else:
        item_widget.play_button.setIcon(qta.icon(icon_name, color="lightgray"))


def restyle_item(item_widget) -> None:
    """Reapplique les couleurs du theme courant sur le bouton play d'une ligne."""
    palette = theme.manager.p
    accent = _accent_color()
    accent_hover = QColor(accent.red(), accent.green(), accent.blue(), 200)
    if hasattr(item_widget, "play_button"):
        item_widget.play_button.set_bg_hover(accent_hover)
        item_widget.play_button.update_colors(palette.TEXT_MUTED, "#ffffff", palette.BORDER_LIGHT)



# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _qss_part1(p) -> str:
    return (
        f"QWidget#DirectoryWidget{{background:transparent;border:none;}}"
        f"QWidget#DirectoryBreadcrumb{{background:transparent;}}"
        f"QPushButton#BreadcrumbSegment{{background:transparent;color:{p.TEXT_MUTED};border:none;padding:2px 4px;font-size:12px;font-weight:500;}}"
        f"QPushButton#BreadcrumbSegment:hover{{color:{p.TEXT};text-decoration:underline;}}"
        f"QPushButton#BreadcrumbCurrent{{background:transparent;color:{p.TEXT};border:none;padding:2px 4px;font-size:12px;font-weight:700;}}"
        f"QLabel#BreadcrumbSep{{color:{p.TEXT_MUTED};font-size:11px;}}"
        f"QLabel#BreadcrumbEmpty{{color:{p.TEXT_MUTED};font-size:12px;font-style:italic;}}"
        f"QPushButton#DirectoryIndexChip{{font-size:11px;font-weight:600;padding:4px 10px;border-radius:10px;border:1px solid {p.BORDER};background:{p.BG_CARD};color:{p.TEXT_MUTED};}}"
        f"QPushButton#DirectoryIndexChip:hover{{background:{p.BG_HOVER};border-color:{p.WARNING};color:{p.WARNING};}}"
        f"QPushButton#DirectoryHelpButton{{background:transparent;color:{p.TEXT_MUTED};border:1px solid {p.BORDER};border-radius:14px;font-weight:700;}}"
        f"QPushButton#DirectoryHelpButton:hover{{color:{p.TEXT};border-color:{p.BORDER_LIGHT};}}"
    )

def _qss_part2(p) -> str:
    return (
        f"QPushButton#DirectoryIndexChip[chipState=\"none\"]{{border-color:{p.BORDER};color:{p.TEXT_MUTED};}}"
        f"QPushButton#DirectoryIndexChip[chipState=\"partial\"]{{border-color:{p.WARNING};color:{p.WARNING};background:transparent;}}"
        f"QPushButton#DirectoryIndexChip[chipState=\"full\"]{{border-color:{p.SUCCESS};color:{p.SUCCESS};background:transparent;}}"
        f"QPushButton#DirectoryIndexChip[chipState=\"busy\"]{{border-color:{p.BORDER};color:{p.TEXT_MUTED};}}"
        f"QPushButton#DirectoryChooseButton,QPushButton#DirectoryUpButton{{background:{p.BG_CARD};color:{p.TEXT};border:1px solid {p.BORDER};border-radius:8px;padding:4px 8px;font-size:12px;}}"
        f"QPushButton#DirectoryChooseButton:hover,QPushButton#DirectoryUpButton:hover{{background:{p.BG_HOVER};border-color:{p.ACCENT};}}"
        f"QPushButton#DirectoryChooseButton:disabled,QPushButton#DirectoryUpButton:disabled{{color:{p.TEXT_MUTED};border-color:{p.BORDER_LIGHT};}}"
        f"QWidget#DirectoryShortcutsBar{{background:transparent;}}"
        f"QLabel#DirectoryShortcutHint{{color:{p.TEXT_MUTED};font-size:11px;font-weight:500;}}"
        f"QLabel#DirectoryFilesCount{{color:{p.TEXT};font-size:12px;font-weight:600;}}"
        f"QLabel#DirectoryIndexSummary,QLabel#DirectoryDetailMeta,QLabel#DirectoryDetailPath{{color:{p.TEXT_MUTED};font-size:11px;}}"
    )

def _qss_part3(p) -> str:
    return (
        f"QLabel#DirectoryStatusLabel{{color:{p.TEXT_MUTED};font-size:11px;padding:3px 10px;background:{p.BG_CARD};border:1px solid {p.BORDER_LIGHT};border-radius:10px;}}"
        f"QLabel#DirectoryDetailTitle{{color:{p.TEXT};font-size:14px;font-weight:700;}}"
        f"QLabel#DirectoryDetailStatus{{color:{p.TEXT_MUTED};font-size:11px;padding:3px 10px;background:{p.BG_CARD};border:1px solid {p.BORDER_LIGHT};border-radius:10px;}}"
        f"QLabel#DirectoryProgressLabel{{color:{p.TEXT_MUTED};font-size:11px;}}"
        f"QProgressBar#DirectoryProgressBar{{border:none;border-radius:2px;background:{p.BORDER_LIGHT};}}"
        f"QProgressBar#DirectoryProgressBar::chunk{{background:{p.WARNING};border-radius:2px;}}"
        f"QWidget#DirectoryCompatFilterRow{{background:{p.BG_CARD};border:1px solid {p.INFO};border-radius:8px;}}"
        f"QLabel#DirectoryCompatFilterLabel{{color:{p.INFO};font-size:11px;font-weight:600;}}"
        f"QPushButton#DirectoryCompatFilterClearBtn{{background:transparent;color:{p.INFO};border:none;font-size:14px;font-weight:700;padding:0;}}"
        f"QPushButton#DirectoryCompatFilterClearBtn:hover{{color:{p.TEXT};}}"
    )

def _qss_part4(p) -> str:
    return (
        f"QTreeView#DirectoryTree{{background:transparent;color:{p.TEXT};border:none;outline:none;}}"
        f"QTreeView#DirectoryTree::item{{padding:5px 4px;}}"
        f"QTreeView#DirectoryTree::item:selected{{background:{p.BG_HOVER};color:{p.TEXT};}}"
        f"QListWidget#DirectoryList{{background:transparent;border:none;outline:none;}}"
        f"QListWidget#DirectoryList::item{{border:none;padding:0px;margin:0px;background:transparent;}}"
        f"QListWidget#DirectoryList::item:selected{{background:transparent;}}"
        f"QWidget#DirectoryRow{{background-color:transparent;border:none;border-radius:6px;}}"
        f"QWidget#DirectoryRow QWidget{{background-color:transparent;border:none;}}"
        f"QWidget#DirectoryRow QLabel{{background-color:transparent;}}"
        f"QWidget#DirectoryRow[focused=\"true\"]{{background-color:{p.BG_HOVER};border-left:2px solid {p.ACCENT};border-radius:6px;}}"
        f"QWidget#DirectoryRow:hover{{background-color:{p.BG_MEDIUM};border:none;border-radius:6px;}}"
        f"QPushButton#DirectoryPlayBtn{{border-radius:14px;border:1px solid {p.BORDER_LIGHT};background:{p.BG_CARD};}}"
        f"QPushButton#DirectoryPlayBtn:hover{{border-color:{p.ACCENT};}}"
    )

def _qss_part5(p) -> str:
    return (
        f"QLabel#DirectoryItemName{{color:{p.TEXT};font-size:12px;font-weight:600;background:transparent;}}"
        f"QLabel#DirectorySectionHeader{{color:{p.TEXT_MUTED};font-size:10px;font-weight:700;padding:8px 6px 3px 6px;background:transparent;}}"
        f"QLabel#DirectoryItemMeta{{color:{p.TEXT_MUTED};font-size:11px;background:transparent;}}"
        f"QLabel#DirectoryTimeLabel{{color:{p.TEXT_MUTED};font-size:10px;background:transparent;}}"
        f"QLabel#DirectoryDurationChip{{color:{p.TEXT_MUTED};font-size:10px;padding:0px;background:transparent;border:none;}}"
        f"QLabel#DirectoryStatusBadge{{color:{p.TEXT_MUTED};font-size:10px;font-weight:500;padding:2px 7px;background:{p.BG_CARD};border:1px solid {p.BORDER_LIGHT};border-radius:8px;}}"
        f"QPushButton#DirectoryKeyBadge{{background-color:#2196f3;color:#ffffff;border:none;border-radius:9px;padding:2px 6px;font-size:10px;font-weight:700;}}"
        f"QPushButton#DirectoryKeyBadge:hover{{background-color:{p.ACCENT};border:1px solid {p.TEXT};}}"
        f"QPushButton#DirectoryLaboBtn{{background:{p.ACCENT};color:{p.BG_DARK};border:none;border-radius:6px;padding:3px 10px;font-size:11px;font-weight:700;}}"
        f"QPushButton#DirectoryLaboBtn:hover{{background:{p.TEXT};color:{p.BG_DARK};}}"
    )

def _qss_part6(p) -> str:
    return (
        f"QSlider#DirectoryPlaybackSlider::groove:horizontal{{border:none;height:4px;background:{p.BORDER_LIGHT};margin:0px;border-radius:2px;}}"
        f"QSlider#DirectoryPlaybackSlider::sub-page:horizontal{{background:{p.ACCENT};border-radius:2px;}}"
        f"QSlider#DirectoryPlaybackSlider::add-page:horizontal{{background:{p.BORDER_LIGHT};border-radius:2px;}}"
        f"QSlider#DirectoryPlaybackSlider::handle:horizontal{{background:{p.TEXT_MUTED};border:none;width:10px;margin:-3px 0;border-radius:5px;}}"
        f"QLineEdit#DirectoryRenameInput{{background-color:{p.BG_CARD};color:{p.TEXT};border:1px solid {p.WARNING};border-radius:6px;padding:3px 6px;}}"
        f"QWidget#DirectoryDetailPanel QPushButton{{background:{p.BG_CARD};color:{p.TEXT};border:1px solid {p.BORDER};border-radius:8px;padding:6px 8px;}}"
        f"QWidget#DirectoryDetailPanel QPushButton:hover{{background:{p.BG_HOVER};border-color:{p.BORDER_LIGHT};}}"
        f"QWidget#DirectoryDetailPanel QPushButton:disabled{{color:{p.TEXT_MUTED};border-color:{p.BORDER_LIGHT};}}"
        f"QWidget#DirectorySubfolderRow{{background-color:transparent;border:1px solid transparent;border-radius:8px;}}"
        f"QWidget#DirectorySubfolderRow[focused=\"true\"]{{background-color:{p.BG_HOVER};border:1px solid {p.ACCENT};border-radius:8px;}}"
        f"QWidget#DirectorySubfolderRow:hover{{background-color:transparent;border:1px solid transparent;border-radius:8px;}}"
        f"QLabel#SubfolderIcon{{color:{p.TEXT_MUTED};font-size:13px;background:transparent;}}"
        f"QLabel#SubfolderName{{color:{p.TEXT};font-size:12px;font-weight:500;background:transparent;}}"
        f"QLabel#SubfolderCount{{color:{p.TEXT_MUTED};font-size:11px;background:transparent;}}"
        f"QLabel#SubfolderArrow{{color:{p.TEXT_MUTED};font-size:12px;background:transparent;}}"
    )


def apply_styles(widget) -> None:
    """Applique la feuille de style complete du Directory tool.

    Decomposee en 6 blocs pour contourner la limite de 64 kB par setStyleSheet
    en evitant les concatenations trop longues dans un seul f-string.
    """
    p = theme.manager.p
    qss = (
        _qss_part1(p) + _qss_part2(p) + _qss_part3(p)
        + _qss_part4(p) + _qss_part5(p) + _qss_part6(p)
    )
    widget.setStyleSheet(qss)
