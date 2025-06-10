from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QSpacerItem,
    QSizePolicy,
    QLineEdit,
    QMessageBox,
    QComboBox,
    QApplication,
    QCheckBox,
    QFileDialog,
)

from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import QEvent
import qtawesome as qta
from datetime import datetime
import os
from backend.models.sample import Sample
from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext

from frontend.sample_gui.playback_controls import PlaybackControls
from frontend.sample_gui.waveform_handler import WaveformHandler



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

        self.isChecked = False

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

        # ---- Playback controls
        self.playback_controls = PlaybackControls(self.sample, self.app_context)
        self.playback_controls.playSample.connect(self.playSample)

        # ---- Waveform container (sera rempli dynamiquement)
        self.waveform_layout = QHBoxLayout()

        self.waveform_handler = WaveformHandler(
            self.sample,
            self.app_context,
            self.playback_controls,
            self.waveform_layout,
        )
        self.waveform_handler.waveformSaved.connect(self.newSampleSaved)
        self.waveform_button.clicked.connect(self.waveform_handler.toggle_waveform)

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

        # ---- Playback
        main_layout.addWidget(self.playback_controls)

        # ---- WaveForm container (sera rempli dynamiquement)
        main_layout.addLayout(self.waveform_layout)


        # ─── Reste des branchements et styles ───

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
        self.waveform_handler.with_wave(fn)

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
                self.playback_controls.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
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
                self.playback_controls.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            except Exception:
                pass
        self.removeFromHistory.emit(self.sample.id)


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
                self.playback_controls.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
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
