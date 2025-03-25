# ./frontend/settings_gui/libraries_list.py

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QIcon
from backend.models.SampleLibrary import SampleBank
from backend.models.User import User
from backend.db import Base, SessionLocal

import os

class SettingsLibrariesList(QWidget):
    librariesUpdated = pyqtSignal()

    def __init__(self, user: User):
        super().__init__()
        self.setLayout(QVBoxLayout())
        self.user = user
        
        # En-tête pour la liste des bibliothèques
        self.header_layout = QHBoxLayout()
        self.toggle_button = QPushButton("▲")  # Pour simuler le changement d'icône
        self.scroll_area = QScrollArea()
        self.add_library_button = QPushButton("Add Sample Library")
        self.header_label = QLabel("Sample Libraries")
        self.toggle_button.setFixedSize(30, 30)
        self.toggle_button.clicked.connect(self.toggleList)
        self.header_layout.addWidget(self.header_label)
        self.header_layout.addWidget(self.toggle_button)
        
        self.layout().addLayout(self.header_layout)

        # Zone de contenu pour la liste des bibliothèques
        self.library_list_widget = QWidget()
        self.library_list_layout = QVBoxLayout(self.library_list_widget)

        print("Libraries : ",self.user.libraries)
        for library in self.user.libraries:
            print("libraries: ", library.to_dict())
        self.refreshLibraryList()


        # Zone de défilement
        self.scroll_area.setWidget(self.library_list_widget)
        self.scroll_area.setWidgetResizable(True)
        self.layout().addWidget(self.scroll_area)

        # Ajouter un bouton pour ajouter une bibliothèque
        self.add_library_button.setIcon(QIcon("folder-plus.png"))
        self.add_library_button.clicked.connect(self.selectDirectory)
        self.layout().addWidget(self.add_library_button)


    def toggleList(self):
        """ Toggle affichage de la liste """
        if self.scroll_area.isVisible():
            self.scroll_area.setVisible(False)
            self.toggle_button.setText("▼")
        else:
            self.scroll_area.setVisible(True)
            self.toggle_button.setText("▲")

    def selectDirectory(self):
        """ Ouvrir un dialogue pour choisir un répertoire """
        try: 
            directory = QFileDialog.getExistingDirectory(self, "Select Folder")
            if directory:
                new_library = SampleBank(directory)
                if  new_library:
                    print("Library succesfully added: ", directory)
                    self.user.libraries = SampleBank.get_all_libraries()
                    self.refreshLibraryList()
                    self.librariesUpdated.emit()
                
        except Exception as error:
            print("Add Sample library: ", error)

    def deleteLibrary(self, library_to_delete):
        """ Supprime une bibliothèque """
        try:
            session = SessionLocal()
            session.expire_on_commit = False
            library = session.query(SampleBank).filter(SampleBank.id == library_to_delete.id).first()
            if library:
                session.delete(library)
                session.commit()
                self.user.libraries = SampleBank.get_all_libraries()
                self.refreshLibraryList()
            session.close()
            self.librariesUpdated.emit()
        except Exception as e:
            print(f"Error deleting library: {e}")

    def refreshLibraryList(self):
        """ Met à jour l'affichage de la liste des bibliothèques avec un bouton de suppression """
        # Vider correctement la mise en page
        while self.library_list_layout.count():
            item = self.library_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Recréer les éléments de la liste
        print("RefreshLibraryList: ", [lib.path for lib in self.user.libraries])
        for library in self.user.libraries:
            library_name = library.path
            library_layout = QHBoxLayout()

            library_label = QLabel(library_name)
            library_layout.addWidget(library_label)

            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(lambda checked, lib=library: self.deleteLibrary(lib))
            library_layout.addWidget(delete_button)

            container = QWidget()
            container.setLayout(library_layout)

            self.library_list_layout.addWidget(container)

        self.library_list_widget.adjustSize()
        self.scroll_area.setWidget(self.library_list_widget)

