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
    Base.metadata.drop_all(bind=engine)  # Supprime toutes les tables existantes
    Base.metadata.create_all(bind=engine)  # Recrée les tables
    print("Base de données créée avec succès.")

if __name__ == '__main__':
    create_database()
    user = User()
    gui = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(gui.exec())

# import threading
# from backend.models.User import User
# from backend.models import db
# from flask import Flask
# from flask_sqlalchemy import SQLAlchemy

# app = Flask(__name__)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///samples.db'
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# db.init_app(app)

# # Fonction qui démarre le serveur Flask
# def run_flask_app():
#     with app.app_context():
#         if not os.path.exists('samples.db'):
#             db.create_all()
#             print("Base de données créée avec succès.")
#         else:
#             print("Base de données déjà existante.")
        
#         user = User()  # Crée un utilisateur, par exemple
#         app.run(debug=True, use_reloader=False)  # Ne pas utiliser reloader en raison de PyQt

# # Fonction qui démarre l'interface graphique
# def start_gui():
#     gui = QApplication(sys.argv)
#     main_window = MainWindow()
#     main_window.show()
#     sys.exit(gui.exec())

# if __name__ == '__main__':
#     # Démarre Flask dans un thread séparé
#     flask_thread = threading.Thread(target=run_flask_app)
#     flask_thread.start()

#     # Démarre l'interface graphique
#     start_gui()