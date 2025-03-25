# ./frontend/settings_gui/libraries_list.py

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QMimeData, QByteArray
from PyQt6.QtGui import QIcon, QDrag
from backend.models.SampleLibrary import SampleBank
from backend.models.User import User
from backend.db import Base, SessionLocal
import json

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
        self.library_list_widget.setAcceptDrops(True)

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

# ---------------------------------------------------------------- Gestion librairies

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
# ---------------------------------------------------------------- Drag and drop
    def mousePressEvent(self, event):
        """ Début du drag-and-drop """
        item = self.library_list_widget.childAt(event.pos())
        if item and isinstance(item, QWidget):
            layout = item.layout()
            if layout and layout.itemAt(0) and layout.itemAt(0).widget():
                label = layout.itemAt(0).widget()
                if isinstance(label, QLabel):
                    index = self.library_list_layout.indexOf(item)
                    mime_data = QMimeData()
                    mime_data.setText(str(index))
                    drag = QDrag(self)
                    drag.setMimeData(mime_data)
                    drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        """ Autoriser le drag-and-drop """
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """ Autoriser le mouvement """
        event.acceptProposedAction()

    def dropEvent(self, event):
        """ Gérer le drop """
        dropped_index = int(event.mimeData().text())
        target_item = self.library_list_widget.childAt(event.pos())
        if target_item and isinstance(target_item, QWidget):
            target_index = self.library_list_layout.indexOf(target_item)
            if dropped_index != target_index:
                self.reorderLibraries(dropped_index, target_index)

    def reorderLibraries(self, from_index, to_index):
        """ Réordonner les bibliothèques """
        library_to_move = self.user.libraries.pop(from_index)
        self.user.libraries.insert(to_index, library_to_move)

        # Mettre à jour les positions dans la base de données
        session = SessionLocal()
        for index, library in enumerate(self.user.libraries):
            db_library = session.query(SampleBank).filter(SampleBank.id == library.id).first()
            if db_library:
                db_library.position = index
        session.commit()
        session.close()

        self.refreshLibraryList()
        self.librariesUpdated.emit()

# ---------------------------------------------------------------- reaffichage

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
            container.setMouseTracking(True) #Permet de suivre la souris.

            self.library_list_layout.addWidget(container)

        self.library_list_widget.adjustSize()
        self.scroll_area.setWidget(self.library_list_widget)

