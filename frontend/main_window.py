# ./frontend/main_window.py

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from frontend.record_widget import RecordWidgetWindow
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from backend.models.User import User

class MainWindow(QMainWindow):
    def __init__(self, user: User):
        super().__init__()
        self.setWindowTitle("SampleRod")
        self.setGeometry(500, 200, 800, 600)
        self.user = user

        # Création de l'onglet principal (QTabWidget)
        self.tab_widget = QTabWidget(self)
        self.setCentralWidget(self.tab_widget)

        # Création de l'onglet Liste de Samples
        self.samples_tab = QWidget()
        self.samples_layout = QVBoxLayout(self.samples_tab)
        self.samples_layout.addWidget(QLabel("Liste des Samples"))
        self.samples_layout.addWidget(QPushButton("Ajouter un sample"))  # Exemple de bouton pour l'onglet des samples
        self.tab_widget.addTab(self.samples_tab, "Liste des Samples")

        # Création de l'onglet Paramètres
        self.settings_tab = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_tab)
        self.tab_widget.addTab(self.settings_tab, "Paramètres")
        
        self.settings_layout.addWidget(SettingsLibrariesList(self.user))


        # Configuration de l'onglet RecordWidget
        self.record_widget = RecordWidgetWindow()
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
        # Ajoutez ici d'éventuelles actions de nettoyage (sauvegarde, fermeture de connexion, etc.)
