# ./frontend/settings_gui/libraries_list.py


from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect, QThread, QSettings, pyqtSlot
from PyQt6.QtGui import QIcon
from backend.models.SampleLibrary import SampleBank
from backend.models.AppContext import AppContext
from backend.db import Base, SessionLocal
from frontend.custom_widgets import QListWidgetDragBugFix
import time
from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext

import os

class SettingsLibrariesList(QWidget):
    """ Widget pour gérer la liste des bibliothèques de samples """
    def __init__(self, app_context: AppContext):
        super().__init__()
        self._qs = QSettings("SampleRod", "Main")
        self.setLayout(QVBoxLayout())
        self.app_context = app_context
        self.settings_service = self.app_context.settings
        
        # En-tête pour la liste des bibliothèques
        self.header_layout = QHBoxLayout()
        self.toggle_button = QPushButton("▲")  # Pour simuler le changement d'icône
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

        self.layout().addWidget(self.library_list_widget)

        # Ajouter un bouton pour ajouter une bibliothèque
        self.add_library_button.setIcon(QIcon("folder-plus.png"))
        self.add_library_button.clicked.connect(self.selectDirectory)
        self.layout().addWidget(self.add_library_button)


        # Connecter le signal de changement de bibliothèques
        self.settings_service.librariesChanged.connect(self.onLibrariesUpdated)

        self.refreshLibraryList(self.settings_service.libraries)

    @pyqtSlot(list)
    def onLibrariesUpdated(self, libraries):
        """Slot appelé à chaque fois que la liste change."""
        self.refreshLibraryList(libraries)


    def toggleList(self):
        vis = self.library_list_widget.isVisible()
        self.library_list_widget.setVisible(not vis)
        self.add_library_button.setVisible(not vis)
        self.toggle_button.setText("▼" if vis else "▲")

    def selectDirectory(self):
        # 1) Récupère le dernier dossier ou, si vide, le home de l’utilisateur
        last = self._qs.value("lastLibraryDir", os.path.expanduser("~"), type=str)
        d = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier",
            last,
            QFileDialog.Option.ShowDirsOnly
        )
        if not d:
            return
        self._qs.setValue("lastLibraryDir", d)
        self.settings_service.addSampleLibrary(d)

    def deleteLibrary(self, library_to_delete):
        """ Supprime une bibliothèque """
        self.settings_service.removeSampleLibrary(library_to_delete.id)

    def updateLibraryOrder(self):
        ordered_ids = []
        for idx in range(self.library_list_widget.count()):
            item = self.library_list_widget.item(idx)
            lib  = item.data(Qt.ItemDataRole.UserRole)  # un SampleBank
            ordered_ids.append(lib.id)
        self.settings_service.updateLibraryOrder(ordered_ids)

    def refreshLibraryList(self, libraries=None):
        """ Met à jour l'affichage de la liste des bibliothèques """
        self.library_list_widget.clear()

        for library in sorted(libraries, key=lambda lib: lib.position):
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



