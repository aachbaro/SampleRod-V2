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

from PySide6.QtCore import Qt
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
    QWidget,
)

from frontend.custom_widgets import CustomSlider
from frontend.sample_gui.waveform.waveform_ui import HoverIconButton


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
        c.setStyleSheet("""
        SampleCard {
            background-color: #1b1b1b;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
        }
        SampleCard:hover {
            background-color: #202020;
            border-color: #3a3a3a;
        }
        SampleCard[focused="true"] {
            /* Garder la meme epaisseur de bordure pour eviter les "sauts" de layout */
            border: 1px solid #f2c94c;
        }
        SampleCard[checked="true"] {
            background-color: #232a33;
            border-color: #f2c94c;
        }
        SampleCard[concatPreview="true"] {
            border: 1px solid #2cc6cf;
        }
        QLabel#SampleName {
            font-weight: 600;
            font-size: 14px;
            color: #f5f5f5;
        }
        QLabel#MetaLabel {
            color: #b9b9b9;
            font-size: 11px;
        }
        QLabel#StatusLabel {
            color: #a6a6a6;
            font-size: 11px;
        }
        QLabel#TimeLabel {
            color: #e6e6e6;
            font-size: 11px;
        }
        QLabel#DateChip {
            background-color: #2a2a2a;
            color: #cfcfcf;
            border-radius: 10px;
            padding: 2px 10px;
        }
        QLabel#IdChip {
            background-color: #2a2a2a;
            color: #cfcfcf;
            border-radius: 10px;
            padding: 2px 10px;
        }
        QLineEdit#RenameInput {
            background-color: #2a2a2a;
            color: #ffffff;
            border: 1px solid #f2c94c;
            padding: 4px 6px;
            border-radius: 4px;
        }
        QComboBox#DirCombo {
            background-color: #222222;
            color: #e6e6e6;
            border: 1px solid #333333;
            padding: 2px 6px;
            border-radius: 4px;
        }
        """)

        btn_size = 24
        btn_icon = 10
        icon_normal = "#cfcfcf"
        icon_hover = "#121212"

        # ---- Widgets
        c.checkbox = QCheckBox()
        c.checkbox.setObjectName("SelectBox")
        c.checkbox.toggled.connect(c.onCheckboxToggled)

        # Nom / renommage
        c.name_label = QLabel(c.get_sample_name())
        c.name_label.setObjectName("SampleName")
        c.name_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        c.name_label.setFixedHeight(24)
        c.name_label.mouseDoubleClickEvent = c.name_label_double_click
        c.name_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        c.rename_input = QLineEdit(c.get_sample_name())
        c.rename_input.setObjectName("RenameInput")
        c.rename_input.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        c.rename_input.setMinimumWidth(200)
        c.rename_input.setMaximumWidth(360)
        c.rename_input.returnPressed.connect(c.submitRename)

        c.check_button = self._make_round_btn(
            "fa5s.check",
            "Valider le renommage",
            color_normal="#9bd18f",
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.check_button.clicked.connect(c.submitRename)

        c.cancel_button = self._make_round_btn(
            "fa5s.times",
            "Annuler le renommage",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.cancel_button.clicked.connect(c.cancelRename)

        c.concat_button = self._make_round_btn(
            "fa5s.arrow-down",
            "Concatener avec le sample precedent",
            color_normal="#2cc6cf",
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.concat_button.clicked.connect(c.onConcatWithPreviousClicked)
        c.concat_button.setVisible(False)

        c.concat_cancel_button = self._make_round_btn(
            "fa5s.times",
            "Garder separe (ne pas concatener)",
            color_normal="#b97a7a",
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.concat_cancel_button.clicked.connect(c.onDismissConcatClicked)
        c.concat_cancel_button.setVisible(False)

        c.delete_button = self._make_round_btn(
            "fa5s.trash-alt",
            "Supprimer",
            color_normal="#d77a7a",
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.delete_button.clicked.connect(c.confirmDelete)

        c.archive_button = self._make_round_btn(
            "fa5s.times-circle",
            "Retirer de l'historique",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.archive_button.clicked.connect(c.onArchiveClicked)

        c.normalize_button = self._make_round_btn(
            "fa5s.bolt",
            "Normaliser le sample",
            color_normal="#c9a75a",
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.normalize_button.clicked.connect(c.onNormalizeButtonClicked)

        c.waveform_button = self._make_round_btn(
            "mdi.waveform",
            "Afficher le waveform",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )
        c.waveform_button.clicked.connect(c.toggleWaveform)

        # Details
        c.change_dir_combobox = QComboBox()
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

        c.length_label = QLabel(f"{c.sample.duration:.1f}s")
        c.length_label.setObjectName("MetaLabel")
        c.length_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        c.length_label.setFixedHeight(24)
        c.length_label.setVisible(False)

        formatted_date = c.sample.created_at.strftime("%d/%m/%Y %H:%M")
        c.date_label = QLabel(f"{formatted_date}")
        c.date_label.setObjectName("DateChip")
        c.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.date_label.setFixedHeight(22)

        c.id_label = QLabel(f"{c.sample.id}", c)
        c.id_label.setObjectName("IdChip")
        c.id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.id_label.setFixedHeight(22)

        # Statut normalisation
        c.status_label = QLabel("")
        c.status_label.setObjectName("StatusLabel")
        c.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.status_label.setFixedHeight(22)
        c.status_label.setVisible(False)

        # Playback
        c.play_button = self._make_round_btn(
            "fa5s.play",
            "Lire",
            color_normal=icon_normal,
            color_hover=icon_hover,
            size=btn_size,
            icon_size=btn_icon,
        )

        c.playback_slider = CustomSlider(Qt.Orientation.Horizontal)
        c.playback_slider.setRange(0, 100)
        c.playback_slider.setValue(0)
        c.playback_slider.setFixedHeight(24)

        c.time_label = QLabel("00:00/00:00")
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
        c.waveform_container = QWidget()
        c.waveform_container.setObjectName("WaveformContainer")
        c.waveform_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        c.waveform_layout = QHBoxLayout(c.waveform_container)
        c.waveform_layout.setContentsMargins(0, 0, 0, 0)
        c.waveform_layout.setSpacing(0)

        # ---- Layouts
        main_layout = QVBoxLayout(c)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        left_header = QHBoxLayout()
        left_header.setSpacing(8)
        left_header.addWidget(c.checkbox)
        left_header.addWidget(c.name_label, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        left_header.addWidget(c.rename_input, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        left_header.addWidget(c.check_button)
        left_header.addWidget(c.cancel_button)
        # Le reste de la ligne est du "vrai" vide (pas un QLabel expansif),
        # donc cliquer hors du nom se comporte comme un clic sur la card.
        left_header.addStretch(1)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)
        actions_layout.addWidget(c.concat_button)
        actions_layout.addWidget(c.concat_cancel_button)
        actions_layout.addWidget(c.normalize_button)
        actions_layout.addWidget(c.waveform_button)
        actions_layout.addWidget(c.archive_button)
        actions_layout.addWidget(c.delete_button)

        header_layout.addLayout(left_header, 1)
        header_layout.addLayout(actions_layout)
        main_layout.addLayout(header_layout)

        info_layout = QHBoxLayout()
        info_layout.setSpacing(0)

        left_box = QWidget()
        left_layout = QHBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(c.change_dir_combobox, alignment=Qt.AlignmentFlag.AlignLeft)

        center_box = QWidget()
        center_layout = QHBoxLayout(center_box)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(c.date_label, alignment=Qt.AlignmentFlag.AlignCenter)

        right_box = QWidget()
        right_layout = QHBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(c.status_label, alignment=Qt.AlignmentFlag.AlignRight)
        right_layout.addSpacing(6)
        right_layout.addWidget(c.id_label, alignment=Qt.AlignmentFlag.AlignRight)

        info_layout.addWidget(left_box, 1)
        info_layout.addWidget(center_box, 1)
        info_layout.addWidget(right_box, 1)
        main_layout.addLayout(info_layout)

        # Playback container : on l'anime (maxHeight) en meme temps que le waveform
        # pour eviter l'effet "la card remonte puis redescend".
        c.playback_container = QWidget()
        c.playback_container.setObjectName("PlaybackContainer")
        c.playback_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        playback_layout = QHBoxLayout(c.playback_container)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(0)
        playback_layout.addWidget(c.play_button)

        # Timeline : slider pleine largeur + time overlay a droite.
        c.timeline_container = QWidget()
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
        base = QWidget()
        base_layout = QHBoxLayout(base)
        base_layout.setContentsMargins(0, 0, 0, 0)
        base_layout.setSpacing(0)
        base_layout.addWidget(c.playback_slider, 1)
        c.timeline_right_spacer = QWidget()
        # Reserve strictement la place du time label (pas plus).
        c.timeline_right_spacer.setFixedWidth(c.time_label.width())
        base_layout.addWidget(c.timeline_right_spacer)

        # Overlay layer: time label aligne a droite.
        overlay = QWidget()
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
        c.editor_container = QWidget()
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
        main_layout.addWidget(c.editor_container)

        # Si la carte obtient temporairement plus de hauteur (ex: pendant une anim),
        # cette stretch absorbe l'extra en bas et evite que les lignes 1/2 "flottent".
        main_layout.addStretch(1)

        # Masquer les champs de renommage par defaut
        c.rename_input.setVisible(False)
        c.check_button.setVisible(False)
        c.cancel_button.setVisible(False)

        # La logique playback est branchee dans SampleCardPlayback

        # Style du playback_slider
        c.playback_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #2f2f2f;
                margin: 0px;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #8e8e8e;
                border-radius: 3px;
            }
            QSlider::add-page:horizontal {
                background: #2f2f2f;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b0b0b0, stop:1 #7e7e7e);
                border: 1px solid #4a4a4a;
                width: 12px;
                margin: -3px 0;
                border-radius: 6px;
            }
        """)

        # Installer l'event filter sur tous les enfants pour gerer le focus visuel
        for child in c.findChildren(QWidget):
            child.installEventFilter(c)

    def _make_round_btn(
        self,
        icon_name: str,
        tooltip: str,
        color_normal: str,
        color_hover: str,
        size: int,
        icon_size: int,
    ) -> HoverIconButton:
        btn = HoverIconButton(
            icon_name=icon_name,
            size=size,
            icon_size=icon_size,
            icon_color_normal=color_normal,
            icon_color_hover=color_hover,
            border_color="#2a2a2a",
            parent=self.card,
        )
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn
