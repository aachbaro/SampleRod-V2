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
import qtawesome as qta

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QWidget,
)

from frontend.custom_widgets import CustomSlider


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
            border: 2px solid #5b8def;
        }
        SampleCard[checked="true"] {
            background-color: #232a33;
            border-color: #3b4b5a;
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
        QLineEdit#RenameInput {
            background-color: #2a2a2a;
            color: #ffffff;
            border: 1px solid #f2c94c;
            padding: 4px 6px;
            border-radius: 4px;
        }
        QPushButton[iconBtn="true"] {
            background: transparent;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 4px;
        }
        QPushButton[iconBtn="true"]:hover {
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.08);
        }
        QComboBox#DirCombo {
            background-color: #222222;
            color: #e6e6e6;
            border: 1px solid #333333;
            padding: 2px 6px;
            border-radius: 4px;
        }
        """)

        btn_size = 28
        btn_icon = QSize(16, 16)
        play_btn_size = 32
        play_icon = QSize(18, 18)

        # ---- Widgets
        c.checkbox = QCheckBox()
        c.checkbox.setObjectName("SelectBox")
        c.checkbox.toggled.connect(c.onCheckboxToggled)

        # Nom / renommage
        c.name_label = QLabel(c.get_sample_name())
        c.name_label.setObjectName("SampleName")
        c.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        c.name_label.setFixedHeight(24)
        c.name_label.mouseDoubleClickEvent = c.name_label_double_click
        c.name_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        c.rename_input = QLineEdit(c.get_sample_name())
        c.rename_input.setObjectName("RenameInput")
        c.rename_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        c.rename_input.setMinimumWidth(220)
        c.rename_input.returnPressed.connect(c.submitRename)

        c.check_button = QPushButton()
        c.check_button.setProperty("iconBtn", True)
        c.check_button.setIcon(qta.icon('fa5s.check', color='green'))
        c.check_button.setFixedSize(btn_size, btn_size)
        c.check_button.setIconSize(btn_icon)
        c.check_button.clicked.connect(c.submitRename)

        c.cancel_button = QPushButton()
        c.cancel_button.setProperty("iconBtn", True)
        c.cancel_button.setIcon(qta.icon('fa5s.times', color='lightgray'))
        c.cancel_button.setFixedSize(btn_size, btn_size)
        c.cancel_button.setIconSize(btn_icon)
        c.cancel_button.clicked.connect(c.cancelRename)

        c.rename_button = QPushButton()
        c.rename_button.setProperty("iconBtn", True)
        c.rename_button.setIcon(qta.icon('fa6s.pen', color='lightgray'))
        c.rename_button.setToolTip("Renommer")
        c.rename_button.setFixedSize(btn_size, btn_size)
        c.rename_button.setIconSize(btn_icon)
        c.rename_button.clicked.connect(c.startRename)

        c.delete_button = QPushButton()
        c.delete_button.setProperty("iconBtn", True)
        c.delete_button.setIcon(qta.icon('fa5s.trash-alt', color='red'))
        c.delete_button.setToolTip("Supprimer")
        c.delete_button.setFixedSize(btn_size, btn_size)
        c.delete_button.setIconSize(btn_icon)
        c.delete_button.clicked.connect(c.confirmDelete)

        c.archive_button = QPushButton()
        c.archive_button.setProperty("iconBtn", True)
        c.archive_button.setIcon(qta.icon('fa5s.times-circle', color='lightgray'))
        c.archive_button.setToolTip("Retirer de l'historique")
        c.archive_button.setFixedSize(btn_size, btn_size)
        c.archive_button.setIconSize(btn_icon)
        c.archive_button.clicked.connect(c.onArchiveClicked)

        c.normalize_button = QPushButton()
        c.normalize_button.setProperty("iconBtn", True)
        c.normalize_button.setIcon(qta.icon('fa5s.bolt', color='orange'))
        c.normalize_button.setToolTip("Normalize sample")
        c.normalize_button.setFixedSize(btn_size, btn_size)
        c.normalize_button.setIconSize(btn_icon)
        c.normalize_button.clicked.connect(c.onNormalizeButtonClicked)

        c.waveform_button = QPushButton()
        c.waveform_button.setProperty("iconBtn", True)
        c.waveform_button.setIcon(qta.icon('mdi.waveform'))
        c.waveform_button.setFixedSize(btn_size, btn_size)
        c.waveform_button.setIconSize(btn_icon)
        c.waveform_button.clicked.connect(c.toggleWaveform)

        # Statut normalisation
        c.status_label = QLabel("")
        c.status_label.setObjectName("StatusLabel")

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
        c.change_dir_combobox.setFixedHeight(28)
        c.change_dir_combobox.currentIndexChanged.connect(c.move_sample)

        c.length_label = QLabel(f"{c.sample.duration:.1f}s")
        c.length_label.setObjectName("MetaLabel")
        c.length_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        c.length_label.setFixedHeight(24)

        formatted_date = c.sample.created_at.strftime("%d/%m/%Y %H:%M")
        c.date_label = QLabel(f"{formatted_date}")
        c.date_label.setObjectName("MetaLabel")
        c.date_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        c.date_label.setFixedHeight(24)

        # Playback
        c.play_button = QPushButton()
        c.play_button.setFixedSize(play_btn_size, play_btn_size)
        c.play_button.setIconSize(play_icon)
        c.play_button.setProperty("iconBtn", True)
        c.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        c.play_button.setToolTip("Lire")

        c.playback_slider = CustomSlider(Qt.Orientation.Horizontal)
        c.playback_slider.setRange(0, 100)
        c.playback_slider.setValue(0)
        c.playback_slider.setFixedHeight(24)

        c.time_label = QLabel("00:00/00:00")
        c.time_label.setFixedSize(90, 24)
        c.time_label.setObjectName("TimeLabel")

        # Waveform container (rempli dynamiquement)
        c.waveform_layout = QHBoxLayout()

        # ---- Layouts
        main_layout = QVBoxLayout(c)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        left_header = QHBoxLayout()
        left_header.setSpacing(8)
        left_header.addWidget(c.checkbox)
        left_header.addWidget(c.name_label, 1)
        left_header.addWidget(c.rename_input, 1)
        left_header.addWidget(c.check_button)
        left_header.addWidget(c.cancel_button)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)
        actions_layout.addWidget(c.rename_button)
        actions_layout.addWidget(c.normalize_button)
        actions_layout.addWidget(c.waveform_button)
        actions_layout.addWidget(c.archive_button)
        actions_layout.addWidget(c.delete_button)

        header_layout.addLayout(left_header, 1)
        header_layout.addLayout(actions_layout)
        main_layout.addLayout(header_layout)

        details_layout = QHBoxLayout()
        details_layout.setSpacing(10)

        folder_label = QLabel("Dossier")
        folder_label.setObjectName("MetaLabel")
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        folder_row.addWidget(folder_label)
        folder_row.addWidget(c.change_dir_combobox)

        details_layout.addLayout(folder_row)
        details_layout.addSpacing(6)
        details_layout.addWidget(c.length_label)
        details_layout.addWidget(c.date_label)
        details_layout.addStretch()
        details_layout.addWidget(c.status_label)
        main_layout.addLayout(details_layout)

        playback_layout = QHBoxLayout()
        playback_layout.setSpacing(8)
        playback_layout.addWidget(c.play_button)
        playback_layout.addWidget(c.playback_slider, 1)
        playback_layout.addWidget(c.time_label)
        main_layout.addLayout(playback_layout)

        main_layout.addLayout(c.waveform_layout)

        c.id_label = QLabel(f"ID: {c.sample.id}", c)
        c.id_label.setObjectName("MetaLabel")
        c.id_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(c.id_label)

        # Masquer les champs de renommage par defaut
        c.rename_input.setVisible(False)
        c.check_button.setVisible(False)
        c.cancel_button.setVisible(False)

        # La logique playback est branchee dans SampleCardPlayback

        # Style du playback_slider
        c.playback_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #e2e2e2;
            }
            QSlider::groove:horizontal:add-page {
                background: #e2e2e2;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """)

        # Installer l'event filter sur tous les enfants pour gerer le focus visuel
        for child in c.findChildren(QWidget):
            child.installEventFilter(c)
