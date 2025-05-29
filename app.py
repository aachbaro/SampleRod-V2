# ./app.py

import sys
if sys.platform.startswith("win"):
    import ctypes
    ctypes.windll.ole32.OleInitialize(0)

from backend.db import engine, Base
from PyQt6.QtWidgets import QApplication
import sys
import os
from backend.models.AppContext import AppContext
from backend.services.settings_service import SettingsService

from frontend.main_window import MainWindow

def create_database():
    """Crée la base de données et les tables."""
    print("Création de la base de données...")
    Base.metadata.create_all(bind=engine)
    print("Base de données créée avec succès.")

if __name__ == '__main__':
    create_database()
    app_context = AppContext()  # Initialisation du contexte de l'application
    gui = QApplication(sys.argv)
    main_window = MainWindow(app_context)
    main_window.show()
    sys.exit(gui.exec())