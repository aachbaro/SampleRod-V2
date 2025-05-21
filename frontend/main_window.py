# ./frontend/main_window.py

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from frontend.record_widget import RecordWidgetWindow
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
from backend.models.User import User
from backend.models.sample import Sample
from frontend.sample_gui.sample_list import SampleListWidget

class MainWindow(QMainWindow):
    def __init__(self, user: User):
        super().__init__()
        self.setWindowTitle("SampleRod")
        self.setGeometry(500, 200, 800, 600)
        self.user = user

        # Création de l'onglet principal (QTabWidget)
        self.tab_widget = QTabWidget(self)
        self.setCentralWidget(self.tab_widget)
        self.record_widget = RecordWidgetWindow(self.user)

        # Création de l'onglet Liste de Samples
        self.samples_tab = QWidget()
        self.samples_layout = QVBoxLayout(self.samples_tab)
        self.sample_list_widget = SampleListWidget(Sample.get_all_samples(), self.user)
        self.samples_layout.addWidget(self.sample_list_widget)
        self.tab_widget.addTab(self.samples_tab, "Liste des Samples")

        # Création de l'onglet Paramètres
        self.settings_tab = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_tab)
        self.tab_widget.addTab(self.settings_tab, "Paramètres")
        
        self.settings_libraries_list = SettingsLibrariesList(self.user)
        self.settings_retro_recording = RetroRecordingWidget(self.user)

        self.settings_layout.addWidget(self.settings_libraries_list)
        self.settings_layout.addWidget(self.settings_retro_recording)

        # Connecte le signal au widget d'enregistrement
        self.settings_libraries_list.librariesUpdated.connect(self.record_widget.updateLibraryCount)
        self.settings_retro_recording.retroRecordingUpdated.connect(self.record_widget.updateRetroRecording)
        self.record_widget.newSampleRecorded.connect(self.sample_list_widget.addSampleToList)
        # Configuration de l'onglet RecordWidget
        self.record_widget.show()

    def closeEvent(self, event):
        """ Méthode appelée lors de la fermeture de la fenêtre principale """
        self.exit_procedure()
        # Ferme la fenêtre RecordWidget si elle existe
        if hasattr(self, 'record_widget'):
            self.record_widget.close()
        event.accept()  # Accepte l'événement de fermeture

    def exit_procedure(self):
        """ Fonction de nettoyage lors de la fermeture de l'application """
        print("Fermeture de l'application proprement...")
        if self.user.settings:
            self.user.settings.retro_recording_enabled = False
            self.user.settings.set_retro_recording_state(False)
            self.user.recorder.disable_retro()
        if self.user.recorder.is_recording:
            self.user.recorder.is_recording = False
        # Ajoutez ici d'éventuelles actions de nettoyage (sauvegarde, fermeture de connexion, etc.)
