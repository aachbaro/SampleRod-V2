# ./app


import sys
from PyQt6.QtWidgets import QApplication
from frontend.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()






# import sys
# from PyQt6.QtWidgets import QApplication
# from frontend.main_window import MainWindow
# from backend.models import create_tables, User, Session
# import os

# def setup_database():
#     # Créer la base de données si elle n'existe pas encore
#     if not os.path.exists('samples.db'):
#         create_tables()
#         print("Base de données créée avec succès.")
#     else:
#         print("Base de données déjà existante.")

#     # Créer un utilisateur par défaut si nécessaire
#     session = Session()
#     user = session.query(User).first()
#     if user is None:
#         user = User(name="Default User")  # Créer un nouvel utilisateur
#         session.add(user)
#         session.commit()
#     session.close()

#     return user

# def main():
#     # Initialisation de la base de données
#     user = setup_database()

#     # Lancement de l'application PyQt
#     app = QApplication(sys.argv)
#     main_window = MainWindow()
#     main_window.show()
#     sys.exit(app.exec())

# if __name__ == '__main__':
#     main()