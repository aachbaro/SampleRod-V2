from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, \
    QSpacerItem, QSizePolicy, QLineEdit, QMessageBox, QComboBox, QApplication, QCheckBox, QFileDialog

from PyQt6.QtCore import pyqtSignal, Qt, QSize, QTimer
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtCore import QEvent
import qtawesome as qta
from utils.utils import get_folder_name
from datetime import datetime
import os
from backend.models.sample import Sample
from frontend.custom_widgets import CustomSlider
from frontend.sample_gui.wave_form import WaveformWidget
from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext



class SampleCard(QWidget):
    # ───────────────── Signaux ─────────────────
    deleteSample       = pyqtSignal(int)          # émet l’ID du sample à supprimer
    renameSample       = pyqtSignal(int, str)     # émet (ID, nouveau nom)
    playSample         = pyqtSignal(object)       # émet l'objet Sample à jouer
    sampleMoved        = pyqtSignal(int, str)     # émet (ID, nouveau dossier)
    newSampleSaved     = pyqtSignal(str)          # émet le path quand on sauvegarde
    normalizeClicked   = pyqtSignal(int)          # émet l’ID pour normaliser manuellement
    selectionChanged   = pyqtSignal(int, bool)    # Nouvel signal : émet (ID du sample, état coché)
    removeFromHistory  = pyqtSignal(int)          # émet l’ID du sample à retirer de l’historique
    

    def __init__(self, sample: Sample, app_context: AppContext, parent=None):
        """
        sample : objet Sample, avec au moins les attributs :
            - id, name (ou filename), created_at, duration.
        """
        super().__init__(parent)

        self.app_context = app_context
        self.settings = self.app_context.settings
        self.sample = sample
        self.isRenaming = False
        self.showWaveform = False
        self.wave_edition_widget = None

        self.isChecked = False

        # self.app_context.audio_player.signals.positionChanged.connect(self.updateSlider)
        self.settings.librariesChanged.connect(self.updateLibraryCombo)

        self.init_ui()
        self._build_shortcuts()

    def init_ui(self):
        """
        Initialise l’interface visuelle de la SampleCard.
        Les widgets sont créés en premier, puis tous les addWidget / addLayout
        sont regroupés à la fin pour clarifier l’assemblage visuel.
        """

        # Pour que Qt applique le background-color défini en QSS
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Permettre le focus au clic
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Nom de l’objet pour cibler précisément en QSS
        self.setObjectName("SampleCard")

        # Un seul setStyleSheet, fusionnant tous tes styles
        self.setStyleSheet("""
        SampleCard {
            background-color: transparent;
            border-radius: 8px;
        }
        SampleCard:hover {
            background-color: rgba(255,255,255,0.05);
        }
        SampleCard[focused="true"] {
            border: 2px solid #888888;
        }
        SampleCard[checked="true"] {
            background-color: rgba(255,255,255,0.1);
        }
        """)

        # ─── Création des widgets (sans encore les ajouter aux layouts) ───

        self.checkbox = QCheckBox()
        self.checkbox.setStyleSheet("margin-left: 5px;")
        self.checkbox.toggled.connect(self.onCheckboxToggled)

        # ---- Header : Nom, input de renommage et boutons

        self.name_label = QLabel(self.get_sample_name())
        self.name_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        self.name_label.setFixedHeight(30)
        self.name_label.mouseDoubleClickEvent = self.name_label_double_click
        self.name_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.rename_input = QLineEdit(self.get_sample_name())
        self.rename_input.setStyleSheet(
            "background-color: #444; color: #ffffff; border: 1px solid #f7cd36; padding: 4px;"
        )

        self.check_button = QPushButton()
        self.check_button.setIcon(qta.icon('fa5s.check', color='green'))
        self.check_button.clicked.connect(self.submitRename)

        self.cancel_button = QPushButton()
        self.cancel_button.setIcon(qta.icon('fa5s.times', color='lightgray'))
        self.cancel_button.clicked.connect(self.cancelRename)

        self.rename_button = QPushButton()
        self.rename_button.setIcon(qta.icon('fa6s.pen', color='lightgray'))
        self.rename_button.setToolTip("Renommer")
        self.rename_button.setFixedSize(30, 30)
        self.rename_button.clicked.connect(self.startRename)

        self.delete_button = QPushButton()
        self.delete_button.setIcon(qta.icon('fa5s.trash-alt', color='red'))
        self.delete_button.setToolTip("Supprimer")
        self.delete_button.setFixedSize(30, 30)
        self.delete_button.clicked.connect(self.confirmDelete)

        # ─── Bouton « archive » (supprimer de l'historique seulement) ───
        self.archive_button = QPushButton()
        self.archive_button.setIcon(qta.icon('fa5s.times-circle', color='lightgray'))
        self.archive_button.setToolTip("Retirer de l'historique")
        self.archive_button.setFixedSize(30, 30)
        self.archive_button.clicked.connect(self.onArchiveClicked)

        # Par défaut, on masque les champs de renommage
        self.rename_input.setVisible(False)
        self.check_button.setVisible(False)
        self.cancel_button.setVisible(False)

        # ---- Normalisation : bouton + label de statut
        self.normalize_button = QPushButton()
        self.normalize_button.setIcon(qta.icon('fa5s.bolt', color='orange'))
        self.normalize_button.setToolTip("Normalize sample")
        self.normalize_button.setFixedSize(30, 30)
        self.normalize_button.clicked.connect(self.onNormalizeButtonClicked)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #cccccc; font-size: 12px;")

        # ---- Détails : combobox dossier, durée, date, bouton waveform
        self.change_dir_combobox = QComboBox()
        # Remplit la combobox avec le dossier courant et les bibliothèques
        self.change_dir_combobox.addItem(f"{SampleCard.get_folder_name(self.sample.path)}/")
        for library in sorted(self.settings.libraries, key=lambda lib: lib.position):
            lib_name = os.path.basename(library.path) + "/"
            self.change_dir_combobox.addItem(lib_name)
        self.change_dir_combobox.addItem("Autre…")

        # Désactiver la molette (optionnel, si vous préférez la méthode 2.1)
        self.change_dir_combobox.wheelEvent = lambda evt: evt.ignore()

        self.change_dir_combobox.setFixedSize(80, 30)
        self.change_dir_combobox.currentIndexChanged.connect(self.move_sample)

        self.length_label = QLabel(f"{self.sample.duration:.1f}s")
        self.length_label.setStyleSheet("color: #cccccc; margin: 5px 0; font-size: 12px;")
        self.length_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.length_label.setFixedHeight(30)

        formatted_date = self.sample.created_at.strftime("%d/%m/%Y %H:%M")
        self.date_label = QLabel(f"{formatted_date}")
        self.date_label.setStyleSheet("color: #cccccc; margin: 5px 0; font-size: 12px;")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.date_label.setFixedHeight(30)

        self.waveform_button = QPushButton()
        self.waveform_button.setIcon(qta.icon('mdi.waveform'))
        self.waveform_button.setIconSize(QSize(26, 26))
        self.waveform_button.setFixedSize(30, 30)
        self.waveform_button.clicked.connect(self.toggleWaveform)

        # ---- Playback : bouton play, slider, label temps
        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.setToolTip("Lire")
        self.play_button.clicked.connect(self.togglePlay)

        self.playback_slider = CustomSlider(Qt.Orientation.Horizontal)
        self.playback_slider.setRange(0, 100)
        self.playback_slider.setValue(0)
        self.playback_slider.setFixedHeight(30)

        self.time_label = QLabel("00:00/00:00")
        self.time_label.setFixedSize(80, 30)
        self.time_label.setStyleSheet("font-size: 12px; color: #ffffff;")

        # ---- Waveform container (sera rempli dynamiquement)
        self.waveform_layout = QHBoxLayout()

        # ─── Assemblage des layouts (addWidget / addLayout) ───
        main_layout = QVBoxLayout(self)

        # ---- Header : nom, renommage, puis boutons delete, normalize (+ statut), et toggle waveform à droite
        header_layout = QHBoxLayout()
        
        header_layout.addWidget(self.checkbox) 

        # Côté gauche : nom et zone de renommage
        header_layout.addWidget(self.name_label)
        header_layout.addWidget(self.rename_input)
        header_layout.addWidget(self.check_button)
        header_layout.addWidget(self.cancel_button)
        header_layout.addWidget(self.rename_button)
        
        # Espace vide pour pousser les boutons à droite
        header_layout.addStretch()
        
        # Côté droit : suppression, normalisation, statut et affichage waveform
        header_layout.addWidget(self.normalize_button)
        header_layout.addWidget(self.waveform_button)
        header_layout.addWidget(self.delete_button)
        header_layout.addWidget(self.archive_button)
        
        main_layout.addLayout(header_layout)

        # ---- Détails : dossier, durée, date, puis statut à droite
        details_layout = QHBoxLayout()
        
        # Côté gauche : dossier, durée, date
        details_layout.addWidget(self.change_dir_combobox)
        details_layout.addItem(QSpacerItem(20, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        details_layout.addWidget(self.length_label)
        details_layout.addItem(QSpacerItem(20, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        details_layout.addWidget(self.date_label)
        
        # Espace vide pour aligner le statut à droite
        details_layout.addStretch()
        
        # Côté droit : indicateur de statut de normalisation
        details_layout.addWidget(self.status_label)
        
        main_layout.addLayout(details_layout)

        # ---- Playback : bouton play, slider, label temps
        playback_layout = QHBoxLayout()
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.playback_slider)
        playback_layout.addWidget(self.time_label)
        main_layout.addLayout(playback_layout)

        # ---- WaveForm container (sera rempli dynamiquement)
        main_layout.addLayout(self.waveform_layout)

        # ─── Reste des branchements et styles ───

        # Mise à jour initiale du slider et connexion du signal
        self.updateSlider()
        self.playback_slider.sliderMoved.connect(self.seekAudio)

        # Style du playback_slider
        self.playback_slider.setStyleSheet("""
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

        # Installer l’event filter sur tous les enfants pour gérer le focus visuel
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def _build_shortcuts(self):
        """Raccourcis actifs seulement quand **cette** SampleCard (ou un de ses enfants) a le focus."""
        for seq, handler in [
            ("Ctrl+X", lambda: self._with_wave(lambda w: w._on_cut_shortcut())),
            ("Ctrl+Z", lambda: self._with_wave(lambda w: w.undo())),
            ("Ctrl+Shift+Z", lambda: self._with_wave(lambda w: w.redo())),
            ("Ctrl+S", lambda: self._with_wave(lambda w: w.onSaveClicked())),
            ("Ctrl+L", lambda: self._with_wave(lambda w: w.loop_button.toggle())),
            ("Ctrl+G", lambda: self._with_wave(lambda w: w.toggle_marker_mode(not w.marker_mode))),
            ("Space", lambda: self._with_wave(lambda w: w.pause_or_resume())),
            ("Ctrl+Space", lambda: self._with_wave(lambda w: w.play_from_start())),
            ("Ctrl+E", lambda: self._with_wave(lambda w: w._on_export_shortcut())),
            ("Ctrl+Shift+G", lambda: self._with_wave(lambda w: w.add_markers_to_region())),
            # ajoute ici d’autres raccourcis si besoin…
        ]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)


    def _with_wave(self, fn):
        """Helper : si le waveform est ouvert, appelle fn(wave_edition_widget)."""
        if hasattr(self, "wave_edition_widget") and self.wave_edition_widget:
            fn(self.wave_edition_widget)

    def mousePressEvent(self, event):
        # 1) on prend le focus au niveau de la carte
        self.setFocus()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        # 1) Échap pour annuler un renommage en cours
        if self.isRenaming and event.key() == Qt.Key.Key_Escape:
            self.cancelRename()
            return


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
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

            # Ajouter le widget de forme d'onde
            self.wave_edition_widget = WaveformWidget(self.sample.path, self.app_context)
            self.wave_edition_widget.waveformSaved.connect(self.newSampleSaved)
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
        """
        Stoppe la lecture si ce sample est en cours, 
        puis émet le signal pour supprimer fichier + DB.
        """
        # 1) Si ce sample est en cours de lecture, on arrête et décharge l’audio
        if self.app_context.audio_player.current_sample_id == self.sample.id:
            try:
                self.app_context.audio_player.clear_audio()
                # remettre l’icône play à zéro
                self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            except Exception:
                pass
        # 2) On émet enfin le signal de suppression
        self.deleteSample.emit(self.sample.id)

    def onArchiveClicked(self):
        """
        Stoppe la lecture si ce sample est en cours, 
        puis émet le signal pour retirer seulement de l’historique.
        """
        if self.app_context.audio_player.current_sample_id == self.sample.id:
            try:
                self.app_context.audio_player.clear_audio()
                self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            except Exception:
                pass
        self.removeFromHistory.emit(self.sample.id)

    def togglePlay(self):
        self.playSample.emit(self.sample)
        is_playing = self.app_context.audio_player.toggle_play(self.sample.id, self.sample.path, self.sample.duration)
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def seekAudio(self, value):
        """Déplace la position de lecture lorsque l'utilisateur interagit avec le slider"""
        new_position = int((value / 100) * (self.sample.duration * 1000))
        is_playing = self.app_context.audio_player.seek_position(self.sample.id, self.sample.path, self.sample.duration, new_position)
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def updateSlider(self):
        """Met à jour la position du slider, le temps affiché et détecte la fin de lecture"""
        position = int(self.app_context.audio_player.get_position())
        sample_id = self.app_context.audio_player.current_sample_id
        duration = int(self.app_context.audio_player.current_sample_duration * 1000)
        if sample_id == self.sample.id:
            self.playback_slider.setValue(int((position / duration) * 100))
            self.time_label.setText(f"{format_time(position)} / {format_time(int(self.sample.duration * 1000))}")
        else:
            self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            self.playback_slider.setValue(int((0 / duration) * 100))
            self.time_label.setText(f"{format_time(0)} / {format_time(int(self.sample.duration * 1000))}")
        if self.app_context.audio_player.is_playing and self.sample.id == sample_id:
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
    
    def move_sample(self, index: int):
        """
        - index==0 : dossier courant → rien à faire
        - 1 ≤ index ≤ len(libs) : déplacer vers settings.libraries[index-1]
        - index == dernier item : ouvrir un QFileDialog pour dossier « Autre… »
        """
        count = self.change_dir_combobox.count()
        # si dossier courant, on reste
        if index == 0:
            return

        # si « Autre… » sélectionné
        if index == count - 1:
            # ouvre le dialogue
            folder = QFileDialog.getExistingDirectory(
                self,
                "Choisir un dossier de destination",
                os.path.dirname(self.sample.path)
            )
            # si annulation, on réinitialise la combo et on sort
            if not folder:
                self.change_dir_combobox.setCurrentIndex(0)
                return
            new_dir = folder
        else:
            # sélection d'une librairie existante
            try:
                target_library = self.settings.libraries[index - 1]
                new_dir = target_library.path
            except IndexError:
                return

        # si on est en train de jouer, on arrête la lecture
        if self.app_context.audio_player.current_sample_id == self.sample.id:
            try:
                self.app_context.audio_player.clear_audio()
                self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            except Exception:
                pass

        print(f"[SampleCard] Déplacer l’échantillon {self.sample.id} → {new_dir}")
        # émet vers le SampleListWidget → SampleService.move()
        self.sampleMoved.emit(self.sample.id, new_dir)
        # on repasse la combo sur « dossier courant »
        self.change_dir_combobox.setCurrentIndex(0)

    def onMoveSuccess(self, sample_id, new_dir):
        if self.sample.id == sample_id:
            self.sample.path = os.path.join(new_dir, os.path.basename(self.sample.path))
            # Mettre à jour la combo “dossier” dans la carte
            self.updateLibraryCombo(self.settings.libraries)
            self.refresh_display()

    def focusInEvent(self, event):
        # quand **tout** (parent ou enfant) reçoit le focus, on marque la carte comme “focused”
        self.setProperty("focused", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # on récupère le widget qui a maintenant le focus
        fw = QApplication.focusWidget()
        # si c'est encore un des enfants, on ne change pas l’état “focused”
        if fw and (fw is self or self.isAncestorOf(fw)):
            return
        # sinon on le retire
        self.setProperty("focused", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            # dès qu’on clique sur un enfant, on redonne le focus à la carte
            self.setFocus()
        return super().eventFilter(watched, event)

    def onNormalizeButtonClicked(self):
        # 1) Si et seulement si c'est cet échantillon qui est joué, on arrête la lecture.
        current_id = self.app_context.audio_player.current_sample_id
        if current_id == self.sample.id:
            try:
                # clear_audio() stoppe et décharge le fichier de pygame
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

        # 2) On met à jour l’état visuel avant de lancer la normalisation
        self.status_label.setText("⏳ Normalisation…")
        self.normalize_button.setEnabled(False)
        self.normalizeClicked.emit(self.sample.id)

    def indicateNormalizationStarted(self):
        self.status_label.setText("⏳ Normalisation…")
        self.normalize_button.setEnabled(False)

    def indicateNormalizationFinished(self):
        self.status_label.setText("✔️ Normalisé")
        self.normalize_button.setEnabled(True)

    def indicateNormalizationError(self, message: str):
        self.status_label.setText(f"❌ Erreur: {message}")
        self.normalize_button.setEnabled(True)

    def onCheckboxToggled(self, checked: bool):
        """
        :param checked: True si la case est cochée, False si elle vient d'être décochée.
        """
        self.isChecked = checked
        # On émet directement le booléen vers le parent
        self.selectionChanged.emit(self.sample.id, checked)
        print(f"Checkbox toggled: {self.sample.id} is now {'checked' if checked else 'unchecked'}")
        # Conserver le style visuel si vous voulez colorer la carte quand elle est cochée :
        self.setProperty("checked", checked)
        self.style().unpolish(self)
        self.style().polish(self)

    def updateLibraryCombo(self, libs: list):
        """
        Met à jour le contenu de self.change_dir_combobox 
        à chaque fois que la liste des bibliothèques change,
        sans émettre de signal currentIndexChanged (pour éviter la boucle).
        """
        current_folder = SampleCard.get_folder_name(self.sample.path) + "/"
        # 1) On empêche les indexChanged pendant la reconstruction
        self.change_dir_combobox.blockSignals(True)
        # 2) On reconstruit …
        self.change_dir_combobox.clear()
        self.change_dir_combobox.addItem(current_folder)
        for library in sorted(libs, key=lambda lib: lib.position):
            nom = os.path.basename(library.path) + "/"
            self.change_dir_combobox.addItem(nom)
        self.change_dir_combobox.addItem("Autre…")
        # 3) On réactive les signaux
        self.change_dir_combobox.blockSignals(False)

def format_time(milliseconds):
    minutes = (milliseconds // 1000) // 60
    seconds = (milliseconds // 1000) % 60

    return f"{minutes:02}:{seconds:02}"