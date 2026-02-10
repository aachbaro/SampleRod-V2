# ./app.py

import sys
from utils.logger import configure_logging, get_logger
configure_logging()
logger = get_logger("app")
if sys.platform.startswith("win"):
    import ctypes
    ctypes.windll.ole32.OleInitialize(0)

from backend.db import engine, Base
from PyQt6.QtWidgets import QApplication
import os
from backend.models.AppContext import AppContext
from backend.services.settings_service import SettingsService

from frontend.main_window import MainWindow

def create_database():
    """Crée la base de données et les tables."""
    logger.info("Création de la base de données...")
    Base.metadata.create_all(bind=engine)
    logger.info("Base de données créée avec succès.")

if __name__ == '__main__':
    create_database()
    app_context = AppContext()  # Initialisation du contexte de l'application
    gui = QApplication(sys.argv)
    gui.setStyleSheet(
        """
        QToolTip {
            background-color: #1e1e1e;
            color: #f2f2f2;
            border: 1px solid #3a3a3a;
            padding: 4px 6px;
        }
        """
    )
    main_window = MainWindow(app_context)
    main_window.show()
    sys.exit(gui.exec())
