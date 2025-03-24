# ./frontend/settings_gui/libraries_list.py

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from backend.models.SampleLibrary import SampleBank
from backend.models.User import User
from backend.db import Base, SessionLocal

import os

class SettingsLibrariesList(QWidget):
    def __init__(self, user: User):
        super().__init__()
        self.setLayout(QVBoxLayout())
        self.user = user
        
        # En-tête pour la liste des bibliothèques
        self.header_layout = QHBoxLayout()
        self.header_label = QLabel("Sample Libraries")
        self.toggle_button = QPushButton("▲")  # Pour simuler le changement d'icône
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
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.library_list_widget)
        self.scroll_area.setWidgetResizable(True)
        self.layout().addWidget(self.scroll_area)

        # Ajouter un bouton pour ajouter une bibliothèque
        self.add_library_button = QPushButton("Add Sample Library")
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
                
        except Exception as error:
            print("Add Sample library: ", error)

    def refreshLibraryList(self):
        """ Met à jour l'affichage de la liste des bibliothèques """
        # Vider la mise en page avant d'ajouter de nouveaux éléments
        for i in range(self.library_list_layout.count()):
            item = self.library_list_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        # Ajouter les bibliothèques à la liste
        for library in self.user.libraries:
            library_name = library.path  # Suppose que chaque bibliothèque a un attribut `name`
            library_label = QLabel(library_name)
            self.library_list_layout.addWidget(library_label)

