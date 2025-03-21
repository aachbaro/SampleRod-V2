# ./frontend/main_window.py

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
import sys
from frontend.record_widget import RecordWidgetWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SampleRod")
        self.setGeometry(500, 200, 800, 600)
        
        # Configuration du widget central et layout
        # central_widget = QWidget(self)
        # self.setCentralWidget(central_widget)
        # layout = QVBoxLayout(central_widget)
        
        # Création et affichage de la fenêtre RecordWidget
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