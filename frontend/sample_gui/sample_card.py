from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton,
                             QHBoxLayout, QVBoxLayout, QSpacerItem, QSizePolicy, 
                             QSlider, QLineEdit, QFrame, QMessageBox, QComboBox)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QTimer
from PyQt6.QtGui import QIcon
import qtawesome as qta
from utils.utils import get_folder_name
from datetime import datetime
import os
from backend.models.User import User
from backend.models.sample import Sample
from frontend.custom_widgets import CustomSlider
from frontend.sample_gui.wave_form import WaveformWidget


class SampleCard(QWidget):
    # Signaux pour communiquer avec la liste
    deleteSample = pyqtSignal(object)      # émet l'objet sample à supprimer
    renameSample = pyqtSignal(object, str)   # émet l'objet sample et le nouveau nom
    playSample = pyqtSignal(object)          # émet l'objet sample à jouer
    sampleMoved = pyqtSignal(int, str)
    

    def __init__(self, sample:Sample, user: User, parent=None):
        """
        sample : objet Sample, avec au moins les attributs :
            - id, name (ou filename), created_at, duration.
        """
        super().__init__(parent)
        self.user = user
        self.sample = sample
        self.isRenaming = False
        self.showWaveform = False
        self.wave_edition_widget = None


        # self.user.audio_player.signals.positionChanged.connect(self.updateSlider)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        # main_layout.setSpacing(5)
        # main_layout.setContentsMargins(10, 10, 10, 10)

# ------------------------- Header : Nom du sample, boutons renommer et supprimer

        header_layout = QHBoxLayout()

    # -------- Conteneur pour name_label et rename_section

            # NAME
        self.name_label = QLabel(self.get_sample_name())
        self.name_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        self.name_label.setFixedHeight(30)
        header_layout.addWidget(self.name_label)
        self.name_label.mouseDoubleClickEvent = self.name_label_double_click
        self.name_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            # RENAME
        self.rename_input = QLineEdit(self.get_sample_name())
        self.rename_input.setStyleSheet("background-color: #444; color: #ffffff; border: 1px solid #f7cd36; padding: 4px;")
        header_layout.addWidget(self.rename_input)

        self.check_button = QPushButton()
        self.check_button.setIcon(qta.icon('fa5s.check', color='green'))
        self.check_button.clicked.connect(self.submitRename)
        header_layout.addWidget(self.check_button)

        self.cancel_button = QPushButton()
        self.cancel_button.setIcon(qta.icon('fa5s.times', color='lightgray'))
        self.cancel_button.clicked.connect(self.cancelRename)
        header_layout.addWidget(self.cancel_button)


        self.rename_button = QPushButton()
        self.rename_button.setIcon(qta.icon('fa6s.pen', color='lightgray'))
        self.rename_button.setToolTip("Renommer")
        self.rename_button.setFixedSize(30, 30)
        self.rename_button.clicked.connect(self.startRename)
        header_layout.addWidget(self.rename_button)

        self.rename_input.setVisible(False)
        self.check_button.setVisible(False)
        self.cancel_button.setVisible(False)

    # ---------------------------------------------------------
        header_layout.addStretch()

        self.delete_button = QPushButton()
        self.delete_button.setIcon(qta.icon('fa5s.trash-alt', color='red'))
        self.delete_button.setToolTip("Supprimer")
        self.delete_button.clicked.connect(self.confirmDelete)
        self.delete_button.setFixedSize(30, 30)
        header_layout.addWidget(self.delete_button)

        main_layout.addLayout(header_layout)

# ------------------------- Détails : Dossier, durée, date de création
        details_layout = QHBoxLayout()

        # library selector
        self.change_dir_combobox = QComboBox()
        self.change_dir_combobox.addItem(f"{SampleCard.get_folder_name(self.sample.path)}/")
        for library in sorted(self.user.libraries, key=lambda lib: lib.position):
            library_dir_name = os.path.basename(library.path)
            # self.change_dir_combobox.addItem(library_dir_name + "/")
            # if library_dir_name != SampleCard.get_folder_name(self.sample.path):
            self.change_dir_combobox.addItem(library_dir_name + "/")
        self.change_dir_combobox.setFixedSize(80, 30)
        self.change_dir_combobox.setStyleSheet("color: #cccccc; margin: 5px 0; font-size: 12px;")
        
        self.change_dir_combobox.currentIndexChanged.connect(self.move_sample)
        
        details_layout.addWidget(self.change_dir_combobox)

        spacer1 = QSpacerItem(20, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        details_layout.addItem(spacer1)

        self.length_label = QLabel(f"{self.sample.duration:.1f}s")
        self.length_label.setStyleSheet("color: #cccccc; margin: 5px 0; font-size: 12px;")  # Ajouter des marges verticales
        self.length_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # Aligner verticalement
        self.length_label.setFixedHeight(30)
        details_layout.addWidget(self.length_label)


        spacer2 = QSpacerItem(20, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        details_layout.addItem(spacer2)

        # Formatage de la date
        formatted_date = self.sample.created_at.strftime("%d/%m/%Y %H:%M")
        self.date_label = QLabel(f"{formatted_date}")
        self.date_label.setStyleSheet("color: #cccccc; margin: 5px 0; font-size: 12px;")  # Ajouter des marges verticales
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # Aligner verticalement
        self.date_label.setFixedHeight(30)
        details_layout.addWidget(self.date_label)

        details_layout.addStretch()  # Pousse le bouton à droite

        # Ajouter le bouton avec l'icône de forme d'onde
        self.waveform_button = QPushButton()
        self.waveform_button.setIcon(qta.icon('mdi.waveform'))  # Utiliser une icône de forme d'onde
        self.waveform_button.setIconSize(QSize(26, 26))
        self.waveform_button.setFixedSize(30, 30)  # Augmenter la taille du bouton
        details_layout.addWidget(self.waveform_button)
        self.waveform_button.clicked.connect(self.toggleWaveform)

        main_layout.addLayout(details_layout)

# ------------------------- Sample play back
        playback_layout = QHBoxLayout()

        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.setToolTip("Lire")
        self.play_button.clicked.connect(self.togglePlay)
        playback_layout.addWidget(self.play_button)

        self.playback_slider = CustomSlider(Qt.Orientation.Horizontal)
        self.playback_slider.setRange(0, 100)
        self.playback_slider.setValue(0)
        self.playback_slider.setFixedHeight(30)
        playback_layout.addWidget(self.playback_slider)

        self.time_label = QLabel("00:00/00:00")
        self.time_label.setFixedSize(80,30)
        self.time_label.setStyleSheet("font-size: 12px; color: #ffffff;")
        playback_layout.addWidget(self.time_label)

        main_layout.addLayout(playback_layout)

        self.updateSlider()
        self.playback_slider.sliderMoved.connect(self.seekAudio)

# --------------------------- WaveForm
        self.waveform_layout = QHBoxLayout()


        main_layout.addLayout(self.waveform_layout)

#------------------- Style général du SampleCard pour fond sombre
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
            }
        """)

        self.playback_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #e2e2e2; /* Couleur de fond par défaut */
            }

            QSlider::groove:horizontal:add-page {
                background: #e2e2e2; /* Couleur avant le curseur (jaune) */
            }

            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """)



    def get_sample_name(self):
        """Retourne le nom du sample à partir du chemin."""
        return os.path.basename(self.sample.name)
    
    @staticmethod #Ajout du décorateur staticmethod
    def get_folder_name(path):
        """Retourne le nom du dernier dossier dans le chemin."""
        return os.path.basename(os.path.dirname(path))

    def name_label_double_click(self, event):
        self.startRename()

    def startRename(self):
        self.isRenaming = True
        self.rename_input.setText(self.get_sample_name())

        self.rename_input.setVisible(True)
        self.check_button.setVisible(True)
        self.cancel_button.setVisible(True)

        self.name_label.setVisible(False)
        self.rename_button.setVisible(False)

        self.rename_input.setFocus()

    def cancelRename(self):
        self.isRenaming = False

        self.rename_input.setVisible(False)
        self.check_button.setVisible(False)
        self.cancel_button.setVisible(False)

        self.name_label.setVisible(True)
        self.rename_button.setVisible(True)

    def submitRename(self):
        new_name = self.rename_input.text().strip()
        if new_name and new_name != self.get_sample_name():
            self.renameSample.emit(self.sample.id, new_name)
        self.isRenaming = False

        self.rename_input.setVisible(False)
        self.check_button.setVisible(False)
        self.cancel_button.setVisible(False)

        self.name_label.setVisible(True)
        self.rename_button.setVisible(True)

    def toggleWaveform(self):
        self.showWaveform = not self.showWaveform

        if self.showWaveform:
            # Masquer les widgets de lecture
            self.play_button.setVisible(False)
            self.playback_slider.setVisible(False)
            self.time_label.setVisible(False)
            try:
                self.user.audio_player.clear_audio()
            except Exception:
                pass

            # Ajouter le widget de forme d'onde
            self.wave_edition_widget = WaveformWidget(self.sample.path)
            self.waveform_layout.addWidget(self.wave_edition_widget)
        else:
            # Afficher les widgets de lecture
            self.play_button.setVisible(True)
            self.playback_slider.setVisible(True)
            self.time_label.setVisible(True)

            # Supprimer le widget de forme d'onde
            if self.wave_edition_widget:
                # 1) stopper la lecture en cours
                try:
                    self.wave_edition_widget.stop_audio()
                except Exception:
                    pass

                # 2) arrêter aussi le timer de mise à jour
                try:
                    self.wave_edition_widget.timer.stop()
                except Exception:
                    pass

                # 3) enfin retirer et détruire le widget
                self.waveform_layout.removeWidget(self.wave_edition_widget)
                self.wave_edition_widget.deleteLater()
                self.wave_edition_widget = None
            

    def confirmDelete(self):
        """Appelle la méthode delete_sample et émet le signal."""
        self.deleteSample.emit(self.sample.id)  # Passe l'ID du sample

    def togglePlay(self):
        self.playSample.emit(self.sample)
        is_playing = self.user.audio_player.toggle_play(self.sample.id, self.sample.path, self.sample.duration)
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def seekAudio(self, value):
        """Déplace la position de lecture lorsque l'utilisateur interagit avec le slider"""
        new_position = int((value / 100) * (self.sample.duration * 1000))
        is_playing = self.user.audio_player.seek_position(self.sample.id, self.sample.path, self.sample.duration, new_position)
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def keyPressEvent(self, event):
        if self.isRenaming and event.key() == Qt.Key.Key_Escape:
            self.cancelRename()

    def updateSlider(self):
        """Met à jour la position du slider, le temps affiché et détecte la fin de lecture"""
        position = int(self.user.audio_player.get_position())
        sample_id = self.user.audio_player.current_sample_id
        duration = int(self.user.audio_player.current_sample_duration * 1000)
        if sample_id == self.sample.id:
            self.playback_slider.setValue(int((position / duration) * 100))
            self.time_label.setText(f"{format_time(position)} / {format_time(int(self.sample.duration * 1000))}")
        else:
            self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            self.playback_slider.setValue(int((0 / duration) * 100))
            self.time_label.setText(f"{format_time(0)} / {format_time(int(self.sample.duration * 1000))}")
        if self.user.audio_player.is_playing and self.sample.id == sample_id:
             QTimer.singleShot(100, self.updateSlider)

    def onRenameSuccess(self, sample_id, new_name):
        if self.sample.id == sample_id:
            # 1) reconstruire le nouveau chemin
            old_path = self.sample.path
            directory = os.path.dirname(old_path)
            ext = os.path.splitext(old_path)[1]
            new_path = os.path.join(directory, new_name + ext)

            # 2) mettre à jour le modèle et l'affichage
            self.sample.name = new_name
            self.sample.path = new_path
            self.name_label.setText(new_name)

            # réinitialiser l'UI de renommage
            self.cancelRename()

    def onRenameError(self, sample_id, error_msg):
        if self.sample.id == sample_id:
            QMessageBox.critical(self, "Erreur de renommage", f"Impossible de renommer: {error_msg}")
    
    def refresh_display(self):
        """Met à jour l'affichage du nom du sample."""
        self.name_label.setText(self.sample.name)
    
    def move_sample(self, index):
        new_dir = self.user.libraries[index - 1].path  # -1 car index 0 est le dossier actuel
        print(new_dir)
        print(self.sample.path)
        self.sampleMoved.emit(self.sample.id, new_dir)

    def onMoveSuccess(self, sample_id, new_dir):
        if self.sample.id == sample_id:
            self.sample.path = os.path.join(new_dir, os.path.basename(self.sample.path))
            self.refresh_display()


def format_time(milliseconds):
    minutes = (milliseconds // 1000) // 60
    seconds = (milliseconds // 1000) % 60

    return f"{minutes:02}:{seconds:02}"