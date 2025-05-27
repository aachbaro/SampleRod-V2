# ./frontend/settings_gui/libraries_list.py


from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect, QThread
from PyQt6.QtGui import QIcon
from backend.models.SampleLibrary import SampleBank
from backend.models.User import User
from backend.db import Base, SessionLocal
from frontend.custom_widgets import QListWidgetDragBugFix
import time

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
        # self.scroll_area = QScrollArea()
        self.add_library_button = QPushButton("Add Sample Library")
        self.header_label = QLabel("Sample Libraries")
        self.library_list_widget = QListWidgetDragBugFix()

        self.toggle_button.setFixedSize(30, 30)
        self.toggle_button.clicked.connect(self.toggleList)
        self.header_layout.addWidget(self.header_label)
        self.header_layout.addWidget(self.toggle_button)
        
        self.layout().addLayout(self.header_layout)

        # Zone de contenu pour la liste des bibliothèques
        self.library_list_layout = QVBoxLayout(self.library_list_widget)


        self.library_list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.library_list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.library_list_widget.model().rowsMoved.connect(self.updateLibraryOrder)



        # Zone de défilement
        # self.scroll_area.setWidget(self.library_list_widget)
        # self.scroll_area.setWidgetResizable(True)
        # self.layout().addWidget(self.scroll_area)
        self.layout().addWidget(self.library_list_widget)

        # Ajouter un bouton pour ajouter une bibliothèque
        self.add_library_button.setIcon(QIcon("folder-plus.png"))
        self.add_library_button.clicked.connect(self.selectDirectory)
        self.layout().addWidget(self.add_library_button)

        self.refreshLibraryList()


    def toggleList(self):
        vis = self.library_list_widget.isVisible()
        self.library_list_widget.setVisible(not vis)
        self.add_library_button.setVisible(not vis)
        self.toggle_button.setText("▼" if vis else "▲")

    def selectDirectory(self):
        d = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier",
            "",  # répertoire de départ
            QFileDialog.Option.ShowDirsOnly
        )
        if d:
            SampleBank(d)  # enregistre en base
            self.user.libraries = SampleBank.get_all_libraries()
            self.refreshLibraryList()
            self.updateLibraryOrder()
            self.librariesUpdated.emit()

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
                self.updateLibraryOrder()
            session.close()
            self.librariesUpdated.emit()
        except Exception as e:
            print(f"Error deleting library: {e}")

    def updateLibraryOrder(self):
        session = SessionLocal()
        # On parcourt la QListWidget qui s'appelle library_list_widget, pas library_list
        for idx in range(self.library_list_widget.count()):
            item = self.library_list_widget.item(idx)
            lib  = item.data(Qt.ItemDataRole.UserRole)
            lib.position = idx
            session.merge(lib)
        session.commit()
        session.close()

        # re-rafraîchir si besoin
        time.sleep(0.1)
        self.refreshLibraryList()
        self.librariesUpdated.emit()


    def refreshLibraryList(self):
        """ Met à jour l'affichage de la liste des bibliothèques """
        self.library_list_widget.clear()

        for library in sorted(self.user.libraries, key=lambda lib: lib.position):
            item_widget = QWidget()
            layout = QHBoxLayout(item_widget)
            layout.setContentsMargins(5, 5, 5, 5)

            label_text = f"{library.position} - {library.path}"
            label = QLabel(label_text)
            # label = QLabel(library.path)
            delete_button = QPushButton("❌")
            delete_button.setFixedSize(30, 30)
            delete_button.clicked.connect(lambda _, lib=library: self.deleteLibrary(lib))

            layout.addWidget(label)
            layout.addStretch()
            layout.addWidget(delete_button)

            item_widget.setLayout(layout)

            list_item = QListWidgetItem(self.library_list_widget)
            list_item.setSizeHint(item_widget.sizeHint())

            # Stocker l'objet SampleBank dans l'item pour le récupérer plus tard
            list_item.setData(Qt.ItemDataRole.UserRole, library)

            self.library_list_widget.addItem(list_item)
            self.library_list_widget.setItemWidget(list_item, item_widget)



