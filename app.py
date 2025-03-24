# ./app.py

from backend.db import engine, Base
from PyQt6.QtWidgets import QApplication
import sys
import os
from backend.models.User import User

from frontend.main_window import MainWindow

def create_database():
    """Crée la base de données et les tables."""
    print("Création de la base de données...")
    Base.metadata.create_all(bind=engine)
    print("Base de données créée avec succès.")

if __name__ == '__main__':
    create_database()
    user = User()
    gui = QApplication(sys.argv)
    main_window = MainWindow(user)
    main_window.show()
    sys.exit(gui.exec())