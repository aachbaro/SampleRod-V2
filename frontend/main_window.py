from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt

from frontend.record_widget import RecordWidgetWindow
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
from frontend.sample_gui.sample_list import SampleListWidget

from backend.models.sample import Sample
from backend.models.AppContext import AppContext

class MainWindow(QMainWindow):
    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.settings = self.app_context.settings
        
        self._setup_window()
        self._build_ui()
        self._init_signals()

    def _setup_window(self):
        """Configure la fenêtre principale"""
        self.setWindowTitle("SampleRod")
        self.setGeometry(500, 200, 800, 600)

    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Conteneur d'onglets
        self.tab_widget = QTabWidget(self)
        self.setCentralWidget(self.tab_widget)

        # --- Onglet 'Enregistrement' (pop-up flottant)
        self.record_widget = RecordWidgetWindow(self.app_context)
        self.record_widget.show()
        # On ne l'ajoute pas aux tabs, c'est une fenêtre indépendante

        # --- Onglet 'Liste des Samples'
        samples_tab = QWidget()
        samples_layout = QVBoxLayout(samples_tab)
        self.sample_list_widget = SampleListWidget(
            samples=Sample.get_all_samples(),
            app_context=self.app_context
        )
        samples_layout.addWidget(self.sample_list_widget)
        self.tab_widget.addTab(samples_tab, "Liste des Samples")

        # --- Onglet 'Paramètres'
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        self.settings_libraries_list = SettingsLibrariesList(self.app_context)
        self.settings_retro_widget = RetroRecordingWidget(self.settings)
        settings_layout.addWidget(self.settings_libraries_list)
        settings_layout.addWidget(self.settings_retro_widget)
        settings_layout.addStretch()
        self.tab_widget.addTab(settings_tab, "Paramètres")

    def _init_signals(self):
        """Connecte les signaux entre composants"""
        # Quand un nouvel échantillon est enregistré, on l'ajoute à la liste
        self.record_widget.newSampleRecorded.connect(
            self.sample_list_widget.addSampleToList
        )

    def closeEvent(self, event):
        """Nettoyage lors de la fermeture de la fenêtre principale"""
        self._exit_procedure()
        # Fermer aussi la fenêtre d'enregistrement si ouverte
        try:
            self.record_widget.close()
        except Exception:
            pass
        event.accept()

    def _exit_procedure(self):
        """Actions de nettoyage avant fermeture"""
        print("Fermeture de l'application proprement...")
        if self.app_context.recorder.is_recording:
            self.app_context.recorder.stop()
        # TODO: autres nettoyages (sauvegarde, etc.)