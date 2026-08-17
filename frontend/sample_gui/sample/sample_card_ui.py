# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'interface visuelle de SampleCard.
# - Regroupe creation des widgets, styles et layouts.
# - Permet d'alleger sample_card.py (logique metier separable ensuite).
#
# CE QUI EST COUVERT
# - Styles QSS de la carte.
# - Widgets (labels, boutons, sliders, combobox).
# - Assemblage des layouts (header / details / playback / waveform).
#
# NON-OBJECTIFS
# - Logique metier (rename/delete/move).
# - Playback audio (togglePlay / updateSlider).
# - Shortcuts / drag & drop.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QStackedLayout,
    QGraphicsOpacityEffect,
    QSizePolicy,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QMenu,
    QWidget,
    QPushButton,
    QProgressBar,
)

from frontend.custom_widgets import CustomSlider
from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme
from frontend.reserve import format_reserve_clock_duration, format_reserve_date, format_reserve_duration
from frontend.ui import IconButton, themed_icon

# Cle QSettings globale : afficher le badge gamme sur toutes les cartes analysees.
SHOW_KEY_BADGE_KEY = "reserve/show_key_badge"


class SampleCardUIBuilder:
    def __init__(self, card):
        self.card = card

    def build(self):
        c = self.card

        # Pour que Qt applique le background-color defini en QSS
        c.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Permettre le focus au clic
        c.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Nom de l'objet pour cibler precisement en QSS
        c.setObjectName("SampleCard")
        # Empêche l'étirement vertical quand il y a peu de cartes
        # (la carte reste a sa taille naturelle, mais peut grandir si le waveform s'ouvre).
        c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        # Style global de la carte
        self._apply_card_stylesheet(c)

        btn_size = 24
        btn_icon = 10
        p = theme.manager.p
        icon_normal = p.TEXT_MUTED
        icon_hover = "#111111"

        # ---- Widgets
        c.checkbox = QCheckBox(c)
        c.checkbox.setObjectName("SelectBox")
        c.checkbox.toggled.connect(c.onCheckboxToggled)
        c.checkbox.setMinimumWidth(0)
        c.checkbox.setMaximumWidth(0)
        c.checkbox.hide()

        # Nom / renommage
        c.name_label = QLabel(c.get_sample_name(), c)
        c.name_label.setObjectName("SampleName")
        c.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        c.name_label.setMinimumWidth(0)
        c.name_label.setFixedHeight(24)
        c.name_label.mouseDoubleClickEvent = c.name_label_double_click
        c.name_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        c.rename_input = QLineEdit(c.get_sample_name(), c)
        c.rename_input.setObjectName("RenameInput")
        c.rename_input.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        c.rename_input.setMinimumWidth(200)
        c.rename_input.setMaximumWidth(360)
        c.rename_input.returnPressed.connect(c.submitRename)

        c.check_button = self._make_round_btn(
            "check",
            "Valider le renommage",
            color_normal=p.SUCCESS,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.check_button.clicked.connect(c.submitRename)

        c.cancel_button = self._make_round_btn(
            "x",
            "Annuler le renommage",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.cancel_button.clicked.connect(c.cancelRename)

        c.concat_button = self._make_round_btn(
            "chevron-down",
            "Concatener avec le sample precedent",
            color_normal=p.RETRO,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.concat_button.clicked.connect(c.onConcatWithPreviousClicked)
        c.concat_button.setVisible(False)

        c.concat_cancel_button = self._make_round_btn(
            "x",
            "Garder separe (ne pas concatener)",
            color_normal=p.ERROR,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.concat_cancel_button.clicked.connect(c.onDismissConcatClicked)
        c.concat_cancel_button.setVisible(False)

        c.delete_button = self._make_round_btn(
            "trash",
            "Supprimer",
            color_normal=p.ERROR,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.delete_button.clicked.connect(c.confirmDelete)
        c.delete_button.setVisible(False)

        c.archive_button = self._make_round_btn(
            "x",
            "Désindexer",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.archive_button.clicked.connect(c.onArchiveClicked)
        c.archive_button.setVisible(False)

        c.normalize_button = self._make_round_btn(
            "bolt",
            "Normaliser le sample",
            color_normal=p.WARNING,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.normalize_button.clicked.connect(c.onNormalizeButtonClicked)
        c.normalize_button.setVisible(False)

        c.waveform_button = self._make_round_btn(
            "wave",
            "Ouvrir dans la waveform",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.waveform_button.clicked.connect(c.toggleWaveform)
        c.waveform_button.setVisible(False)

        # Details
        c.change_dir_combobox = QComboBox(c)
        c.change_dir_combobox.setObjectName("DirCombo")
        c.change_dir_combobox.addItem(f"{c.get_folder_name(c.sample.path)}/")
        for library in sorted(c.settings.libraries, key=lambda lib: lib.position):
            lib_name = os.path.basename(library.path) + "/"
            c.change_dir_combobox.addItem(lib_name)
        c.change_dir_combobox.addItem("Autre...")
        c.change_dir_combobox.wheelEvent = lambda evt: evt.ignore()
        c.change_dir_combobox.setMinimumWidth(160)
        c.change_dir_combobox.setMaximumWidth(260)
        c.change_dir_combobox.setFixedHeight(24)
        c.change_dir_combobox.currentIndexChanged.connect(c.move_sample)

        c.length_label = QLabel(
            format_reserve_clock_duration(c.sample.duration), c
        )
        c.length_label.setObjectName("MetaLabel")
        c.length_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        c.length_label.setFixedHeight(24)
        c.length_label.setFixedWidth(48)
        # Do not call setVisible(True) before the label has been inserted into
        # the card layout.  A visible parentless QWidget is a native top-level
        # window, which caused one tiny flashing window per Recent sample.

        formatted_date = format_reserve_date(c.sample.created_at)
        c.date_label = QLabel(f"{formatted_date}", c)
        c.date_label.setObjectName("DateChip")
        c.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.date_label.setFixedHeight(22)

        c.id_label = QLabel(f"{c.sample.id}", c)
        c.id_label.setObjectName("IdChip")
        c.id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.id_label.setFixedHeight(22)

        # Badge gamme (key detection)
        c.key_badge = QPushButton("", c)
        c.key_badge.setObjectName("KeyBadge")
        c.key_badge.setFixedHeight(22)
        c.key_badge.setFixedWidth(38)
        c.key_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        c.key_badge.setToolTip("Gamme détectée — cliquer pour trouver les samples compatibles")
        c.key_badge.setVisible(False)
        c.key_slot = QWidget(c)
        c.key_slot.setObjectName("SampleCardKeySlot")
        c.key_slot.setFixedSize(38, 24)
        key_slot_layout = QHBoxLayout(c.key_slot)
        key_slot_layout.setContentsMargins(0, 0, 0, 0)
        key_slot_layout.addWidget(c.key_badge)

        # Statut normalisation
        c.status_label = QLabel("", c)
        c.status_label.setObjectName("StatusLabel")
        c.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.status_label.setFixedHeight(22)
        c.status_label.setMaximumWidth(74)
        c.status_label.setVisible(False)
        c.status_slot = QWidget(c)
        c.status_slot.setObjectName("SampleCardStatusSlot")
        c.status_slot.setFixedSize(74, 24)
        status_slot_layout = QHBoxLayout(c.status_slot)
        status_slot_layout.setContentsMargins(0, 0, 0, 0)
        status_slot_layout.addWidget(c.status_label)

        # Playback
        c.play_button = self._make_round_btn(
            "player-play",
            "Lire",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )

        c.playback_slider = CustomSlider(Qt.Orientation.Horizontal, c)
        c.playback_slider.setRange(0, 100)
        c.playback_slider.setValue(0)
        c.playback_slider.setFixedHeight(20)
        c.playback_slider.setMinimumWidth(80)
        c.playback_slider.setMaximumWidth(220)
        c.playback_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        c.playback_slider.setToolTip("Cliquer pour lire à partir de cette position")

        c.time_label = QLabel("00:00/00:00", c)
        # Largeur calculee sur le format max (mm:ss / mm:ss) pour:
        # - eviter les sauts de layout
        # - reduire au minimum l'espace reserve a droite
        max_time_str = "00:00 / 00:00"
        time_w = c.time_label.fontMetrics().horizontalAdvance(max_time_str) + 4
        c.time_label.setFixedSize(time_w, 24)
        c.time_label.setObjectName("TimeLabel")
        c.time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # L'overlay ne doit pas bloquer les clics/drag du slider.
        c.time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Waveform container (rempli dynamiquement).
        # Il sera affiche via un QStackedLayout dans l'espace "editor" (ligne 3).
        c.waveform_container = QWidget(c)
        c.waveform_container.setObjectName("WaveformContainer")
        c.waveform_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        c.waveform_layout = QHBoxLayout(c.waveform_container)
        c.waveform_layout.setContentsMargins(0, 0, 0, 0)
        c.waveform_layout.setSpacing(0)

        # ---- Menu d'options (remplace la rangee de boutons d'action)
        c.options_button = IconButton(
            "dots-vertical", tooltip="Options", size="s", parent=c
        )
        c.options_menu = self._build_options_menu(c)
        c.options_button.clicked.connect(
            lambda: c.options_menu.exec(
                c.options_button.mapToGlobal(c.options_button.rect().bottomLeft())
            )
        )

        # ---- Layout principal : une ligne dense + progression active discrète.
        main_layout = QVBoxLayout(c)
        main_layout.setContentsMargins(7, 4, 7, 4)
        main_layout.setSpacing(2)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        header_layout.addWidget(c.play_button)
        c.name_slot = QWidget(c)
        c.name_slot.setObjectName("SampleCardNameSlot")
        c.name_slot.setFixedWidth(180)
        name_slot_layout = QHBoxLayout(c.name_slot)
        name_slot_layout.setContentsMargins(0, 0, 0, 0)
        name_slot_layout.setSpacing(6)
        name_slot_layout.addWidget(c.checkbox)
        c.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        c.name_label.setMinimumWidth(0)
        c.name_label.setToolTip(str(c.sample.name))
        name_slot_layout.addWidget(c.name_label, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        name_slot_layout.addWidget(c.rename_input, 1)
        header_layout.addWidget(c.name_slot)
        # Preview directement dans la ligne : sa place est toujours reservee,
        # la carte ne change donc jamais de hauteur pendant la lecture.
        header_layout.addWidget(c.playback_slider, 1)
        header_layout.addWidget(c.length_label)
        header_layout.addWidget(c.check_button)
        header_layout.addWidget(c.cancel_button)
        header_layout.addWidget(c.concat_button)
        header_layout.addWidget(c.concat_cancel_button)
        # Vrai vide (pas un QLabel expansif) : cliquer ici = clic sur la card.
        # Colonnes terminales stables : leur largeur ne dépend ni de "C"/"C#",
        # ni du format de durée. Les lignes restent ainsi alignées verticalement.
        header_layout.addWidget(c.status_slot)
        header_layout.addWidget(c.key_slot)
        header_layout.addWidget(c.options_button)
        main_layout.addLayout(header_layout)

        # Elements desormais NON affiches : porteurs de donnees pour le tooltip
        # (date/id/dossier/duree/etat) et pour la logique (move via combobox).
        # On les place dans un conteneur MASQUE : meme si un controleur appelle
        # setVisible(True) dessus (ex: le statut "Normal"), le parent cache les
        # garde invisibles (sinon ils flottent a (0,0) par-dessus la carte).
        c._data_holder = QWidget(c)
        c._data_holder.setObjectName("SampleCardDataHolder")
        c._data_holder.setVisible(False)
        _holder_layout = QVBoxLayout(c._data_holder)
        _holder_layout.setContentsMargins(0, 0, 0, 0)
        _holder_layout.setSpacing(0)
        for _holder in (
            c.date_label, c.id_label, c.change_dir_combobox,
        ):
            _holder_layout.addWidget(_holder)

        # Playback container : on l'anime (maxHeight) en meme temps que le waveform
        # pour eviter l'effet "la card remonte puis redescend".
        c.playback_container = QWidget(c)
        c.playback_container.setObjectName("PlaybackContainer")
        c.playback_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        playback_layout = QHBoxLayout(c.playback_container)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(8)

        # Timeline : slider pleine largeur + time overlay a droite.
        c.timeline_container = QWidget(c.playback_container)
        c.timeline_container.setObjectName("TimelineContainer")
        c.timeline_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        c.timeline_container.setFixedHeight(24)
        c.timeline_stack = QStackedLayout(c.timeline_container)
        c.timeline_stack.setContentsMargins(0, 0, 0, 0)
        c.timeline_stack.setSpacing(0)
        c.timeline_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        # Base layer: slider + spacer reserve la place du time label pour que
        # la barre ne "passe pas dessous".
        base = QWidget(c.timeline_container)
        base.setObjectName("TimelineBase")
        base_layout = QHBoxLayout(base)
        base_layout.setContentsMargins(0, 0, 0, 0)
        base_layout.setSpacing(0)
        # playback_slider vit désormais dans la ligne principale. Ne pas
        # l'ajouter une seconde fois ici : Qt le reparenterait vers ce
        # conteneur historique masqué et il disparaîtrait de la carte compacte.
        base_layout.addStretch(1)
        c.timeline_right_spacer = QWidget(base)
        c.timeline_right_spacer.setObjectName("TimelineRightSpacer")
        # Reserve strictement la place du time label (pas plus).
        c.timeline_right_spacer.setFixedWidth(c.time_label.width())
        base_layout.addWidget(c.timeline_right_spacer)

        # Overlay layer: time label aligne a droite.
        overlay = QWidget(c.timeline_container)
        overlay.setObjectName("TimelineOverlay")
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay_layout = QHBoxLayout(overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(
            c.time_label,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        c.timeline_stack.addWidget(base)
        c.timeline_stack.addWidget(overlay)

        c.playback_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        playback_layout.addWidget(c.timeline_container, 1)
        # Fixe le maxHeight au sizeHint pour que l'animation parte d'une valeur reelle
        # (sinon maximumHeight == "inf" et l'anim ne se voit presque pas).
        c.playback_height_hint = c.playback_container.sizeHint().height()
        c.playback_container.setMaximumHeight(c.playback_height_hint)

        # Opacity effects (utilises par SampleCardWaveform pour des fades doux)
        c.playback_opacity_effect = QGraphicsOpacityEffect(c.playback_container)
        c.playback_opacity_effect.setOpacity(1.0)
        c.playback_container.setGraphicsEffect(c.playback_opacity_effect)

        c.waveform_opacity_effect = QGraphicsOpacityEffect(c.waveform_container)
        c.waveform_opacity_effect.setOpacity(1.0)
        c.waveform_container.setGraphicsEffect(c.waveform_opacity_effect)
        # Espace "editor" (ligne 3) : un seul bloc qui affiche soit le playback,
        # soit le waveform editor. On animera la hauteur de ce bloc pour que les
        # 2 premieres lignes ne bougent jamais.
        c.editor_container = QWidget(c)
        c.editor_container.setObjectName("EditorContainer")
        c.editor_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        c.editor_stack = QStackedLayout(c.editor_container)
        c.editor_stack.setContentsMargins(0, 0, 0, 0)
        c.editor_stack.setSpacing(0)
        c.editor_stack.addWidget(c.playback_container)
        c.editor_stack.addWidget(c.waveform_container)
        c.editor_stack.setCurrentWidget(c.playback_container)
        c.editor_container.setMaximumHeight(c.playback_height_hint)
        c.editor_container.setMinimumHeight(c.playback_height_hint)
        c.editor_container.hide()

        c.active_progress = QProgressBar(c)
        c.active_progress.setObjectName("RecentActiveProgress")
        c.active_progress.setRange(0, 1000)
        c.active_progress.setValue(0)
        c.active_progress.setTextVisible(False)
        c.active_progress.setFixedHeight(2)
        c.active_progress.hide()
        main_layout.addWidget(c.active_progress)

        # Si la carte obtient temporairement plus de hauteur (ex: pendant une anim),
        # cette stretch absorbe l'extra en bas et evite que les lignes 1/2 "flottent".

        # Masquer les champs de renommage par defaut
        c.rename_input.setVisible(False)
        c.check_button.setVisible(False)
        c.cancel_button.setVisible(False)

        # La logique playback est branchee dans SampleCardPlayback

        # Style du playback_slider
        self._apply_slider_stylesheet(c)

        # Tooltip initial (nom/id/dossier/date/duree/gamme/etat)
        self._refresh_tooltip(c)

        # Installer l'event filter sur tous les enfants pour gerer le focus visuel
        for child in c.findChildren(QWidget):
            child.installEventFilter(c)

    # ------------------------------------------------------------------
    # Menu d'options + tooltip (carte compacte)

    def _build_options_menu(self, c) -> QMenu:
        menu = QMenu(c)
        menu.addAction(
            themed_icon("music", size=16, color=theme.manager.p.INFO),
            "Analyser la gamme",
        ).triggered.connect(
            lambda: c.app_context.sample_store.batch_analyze_ids([c.sample.id])
        )
        menu.addAction(
            themed_icon("bolt", size=16, color=theme.manager.p.WARNING),
            "Normaliser",
        ).triggered.connect(c.onNormalizeButtonClicked)
        menu.addAction(
            themed_icon("wave", size=16, color=theme.manager.p.TEXT_MUTED),
            "Ouvrir dans la waveform\tCtrl+Right",
        ).triggered.connect(c.toggleWaveform)
        menu.addAction(
            themed_icon("pencil", size=16, color=theme.manager.p.TEXT_MUTED),
            "Renommer\tCtrl+R",
        ).triggered.connect(
            lambda: c.header_actions.start_rename()
        )
        c._move_menu = menu.addMenu("Déplacer vers")
        menu.aboutToShow.connect(lambda: self._populate_move_menu(c))
        menu.addSeparator()
        menu.addAction(
            themed_icon("x", size=16, color=theme.manager.p.TEXT_MUTED),
            "Désindexer\tCtrl+Shift+D",
        ).triggered.connect(c.onArchiveClicked)
        menu.addAction(
            themed_icon("trash", size=16, color=theme.manager.p.ERROR),
            "Supprimer\tCtrl+D",
        ).triggered.connect(c.confirmDelete)
        menu.addSeparator()
        menu.addAction("Ouvrir l'emplacement").triggered.connect(
            lambda: c.openInFoldersRequested.emit(os.path.dirname(c.sample.path))
        )
        if getattr(getattr(c, "sample", None), "dominant_note", None):
            menu.addAction("Trouver les compatibles").triggered.connect(
                lambda: c.findCompatiblesRequested.emit(int(c.sample.id))
            )
        return menu

    @staticmethod
    def _populate_move_menu(c) -> None:
        move_menu = getattr(c, "_move_menu", None)
        if move_menu is None:
            return
        move_menu.clear()
        combo = c.change_dir_combobox
        for idx in range(1, combo.count()):  # 0 = dossier courant
            action = move_menu.addAction(combo.itemText(idx))
            action.triggered.connect(
                lambda checked=False, i=idx: c.change_dir_combobox.setCurrentIndex(i)
            )

    @staticmethod
    def _refresh_tooltip(c) -> None:
        parts = [c.get_sample_name(), f"ID {c.sample.id}"]
        folder = c.get_folder_name(c.sample.path)
        if folder:
            parts.append(f"Dossier : {folder}")
        try:
            parts.append(f"Date : {format_reserve_date(c.sample.created_at)}")
        except Exception:
            pass
        duration = getattr(c.sample, "duration", None)
        if duration:
            parts.append(
                f"Durée : {format_reserve_duration(duration, compact=True)}"
            )
        key = c.key_badge.text().strip() if getattr(c, "key_badge", None) else ""
        if key:
            parts.append(f"Gamme : {key}")
        state = c.status_label.text().strip() if getattr(c, "status_label", None) else ""
        if state:
            parts.append(f"État : {state}")
        c.setToolTip("\n".join(p for p in parts if p))

    def _make_round_btn(
        self,
        icon_name: str,
        tooltip: str,
        color_normal: str,
        color_hover: str,
        size: int,
        icon_size: int,
    ) -> HoverIconButton:
        bg_hover = (
            QColor(255, 255, 255, 210) if theme.manager.is_dark()
            else QColor(30, 30, 30, 55)
        )
        btn = HoverIconButton(
            icon_name=icon_name,
            size=size,
            icon_size=icon_size,
            icon_color_normal=color_normal,
            icon_color_hover=color_hover,
            border_color=theme.manager.p.BG_CARD,
            bg_hover=bg_hover,
            parent=self.card,
        )
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    @staticmethod
    def _apply_card_stylesheet(card):
        p = theme.manager.p
        card.setStyleSheet(f"""
        SampleCard {{
            background-color: {p.BG_MEDIUM};
            border: 1px solid {p.BORDER_LIGHT};
            border-radius: 10px;
        }}
        SampleCard:hover {{
            background-color: {p.BG_HOVER};
            border-color: {p.BORDER};
        }}
        SampleCard[focused="true"] {{
            border: 1px solid {p.WARNING};
        }}
        SampleCard[checked="true"] {{
            background-color: {p.BG_HOVER};
            border-color: {p.WARNING};
        }}
        SampleCard[concatPreview="true"] {{
            border: 1px solid {p.RETRO};
        }}
        /* Conteneurs internes transparents — evitent l'artefact BG vs BG_MEDIUM */
        QWidget#PlaybackContainer, QWidget#EditorContainer,
        QWidget#WaveformContainer, QWidget#TimelineContainer,
        QWidget#TimelineBase, QWidget#TimelineOverlay,
        QWidget#TimelineRightSpacer,
        QWidget#SampleCardDataHolder,
        QWidget#SampleCardNameSlot, QWidget#SampleCardKeySlot, QWidget#SampleCardStatusSlot,
        QWidget#InfoLeft, QWidget#InfoCenter, QWidget#InfoRight {{
            background: transparent;
            border: none;
        }}
        QCheckBox#SelectBox {{ background:transparent; border:none; spacing:0px; }}
        QLabel#SampleName {{
            font-weight: 600;
            font-size: 14px;
            color: {p.TEXT};
        }}
        QLabel#MetaLabel {{
            color: {p.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#StatusLabel {{
            color: {p.TEXT_MUTED};
            font-size: 11px;
        }}
        QLabel#TimeLabel {{
            color: {p.TEXT};
            font-size: 11px;
        }}
        QLabel#DateChip {{
            background-color: {p.BG_CARD};
            color: {p.TEXT_MUTED};
            border-radius: 10px;
            padding: 2px 10px;
        }}
        QLabel#IdChip {{
            background-color: {p.BG_CARD};
            color: {p.TEXT_MUTED};
            border-radius: 10px;
            padding: 2px 10px;
        }}
        QPushButton#KeyBadge {{
            background-color: {p.INFO};
            color: #ffffff;
            border: none;
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 600;
        }}
        QPushButton#KeyBadge:hover {{
            background-color: {p.INFO};
            opacity: 0.85;
        }}
        QLineEdit#RenameInput {{
            background-color: {p.BG_CARD};
            color: {p.TEXT};
            border: 1px solid {p.WARNING};
            padding: 4px 6px;
            border-radius: 4px;
        }}
        QProgressBar#RecentActiveProgress {{ border:none; background:{p.BORDER}; }}
        QProgressBar#RecentActiveProgress::chunk {{ background:{p.ACCENT}; }}
        QComboBox#DirCombo {{
            background-color: transparent;
            color: {p.TEXT_MUTED};
            border: none;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        """)

    @staticmethod
    def _apply_slider_stylesheet(card):
        p = theme.manager.p
        card.playback_slider.setStyleSheet(f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                height: 3px;
                background: {p.BORDER};
                margin: 0px;
                border-radius: 1px;
            }}
            QSlider::sub-page:horizontal {{
                background: {p.ACCENT};
                border-radius: 1px;
            }}
            QSlider::add-page:horizontal {{
                background: {p.BORDER};
                border-radius: 1px;
            }}
            QSlider::handle:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {p.TEXT_MUTED}, stop:1 {p.BORDER_LIGHT});
                border: 1px solid {p.BORDER_LIGHT};
                width: 8px;
                margin: -3px 0;
                border-radius: 4px;
            }}
        """)

    @staticmethod
    def restyle(card):
        """Re-applique le style selon le theme courant. Appeler sur themeChanged."""
        SampleCardUIBuilder._apply_card_stylesheet(card)
        SampleCardUIBuilder._apply_slider_stylesheet(card)
        p = theme.manager.p
        border = p.BG_CARD
        icon_hover = "#111111"
        bg_hover = (
            QColor(255, 255, 255, 210) if theme.manager.is_dark()
            else QColor(30, 30, 30, 55)
        )
        for btn in (
            card.check_button, card.cancel_button, card.concat_button,
            card.concat_cancel_button, card.delete_button, card.archive_button,
            card.normalize_button, card.waveform_button, card.play_button,
        ):
            btn.set_bg_hover(bg_hover)
        card.check_button.update_colors(p.SUCCESS, icon_hover, border)
        card.cancel_button.update_colors(p.TEXT_MUTED, icon_hover, border)
        card.concat_button.update_colors(p.RETRO, icon_hover, border)
        card.concat_cancel_button.update_colors(p.ERROR, icon_hover, border)
        card.delete_button.update_colors(p.ERROR, icon_hover, border)
        card.archive_button.update_colors(p.TEXT_MUTED, icon_hover, border)
        card.normalize_button.update_colors(p.WARNING, icon_hover, border)
        card.waveform_button.update_colors(p.TEXT_MUTED, icon_hover, border)
        card.play_button.update_colors(p.TEXT_MUTED, icon_hover, border)
