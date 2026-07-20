# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres pour gerer les bibliotheques de samples.
# - Ajout, suppression et ordre des dossiers surveilles.
#
# FONCTIONS (sommaire)
# - SettingsLibrariesList    : widget de gestion des bibliotheques
# - toggleList()             : affiche/masque la liste des dossiers
# - selectDirectory()        : ouvre un FileDialog pour ajouter un dossier
# - deleteLibrary()          : supprime une bibliotheque via le service
# - updateLibraryOrder()     : persiste l'ordre apres un drag-and-drop
# - refreshLibraryList()     : reconstruit la liste depuis les bibliotheques
#
# LIENS CLES
# - backend/models/SampleLibrary.py
# - backend/services/settings_service.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/libraries_list.py

# ./frontend/settings_gui/libraries_list.py


from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, 
    QHBoxLayout, QFrame, QScrollArea, QGroupBox, QComboBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal, QObject, QRect, QThread, QSettings, Slot
from PySide6.QtGui import QIcon
from backend.models.SampleLibrary import SampleBank
from backend.models.AppContext import AppContext
from frontend.custom_widgets import QListWidgetDragBugFix
import time
from backend.services.settings_service import SettingsService
from backend.models.AppContext import AppContext

import os
import logging
logger = logging.getLogger("libraries_list")

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

    @Slot(list)
    def onLibrariesUpdated(self, libraries):
        """Slot appelé à chaque fois que la liste change."""
        self.refreshLibraryList(libraries)


    def toggleList(self):
        """Affiche ou masque la liste + le bouton d'ajout."""
        vis = self.library_list_widget.isVisible()
        self.library_list_widget.setVisible(not vis)
        self.add_library_button.setVisible(not vis)
        self.toggle_button.setText("▼" if vis else "▲")
        logger.info(f"[LibrariesList] Liste {'masquée' if vis else 'affichée'}")

    def selectDirectory(self):
        """Ouvre un dialog pour choisir un dossier et l’ajoute comme bibliotheque."""
        # 1) Récupère le dernier dossier ou, si vide, le home de l’utilisateur
        last = self._qs.value("lastLibraryDir", os.path.expanduser("~"), type=str)
        d = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier",
            last,
            QFileDialog.Option.ShowDirsOnly
        )
        if not d:
            logger.info("[LibrariesList] Sélection annulée")
            return
        self._qs.setValue("lastLibraryDir", d)
        self.settings_service.addSampleLibrary(d)
        logger.info(f"[LibrariesList] Bibliothèque ajoutée : {d}")

    def deleteLibrary(self, library_to_delete):
        """ Supprime une bibliothèque """
        self.settings_service.removeSampleLibrary(library_to_delete.id)
        logger.info(f"[LibrariesList] Bibliothèque supprimée id={library_to_delete.id}")

    def updateLibraryOrder(self):
        """Lit l'ordre courant de la QListWidget et le persiste via le service."""
        ordered_ids = []
        for idx in range(self.library_list_widget.count()):
            item = self.library_list_widget.item(idx)
            lib  = item.data(Qt.ItemDataRole.UserRole)  # un SampleBank
            ordered_ids.append(lib.id)
        self.settings_service.updateLibraryOrder(ordered_ids)
        logger.info(f"[LibrariesList] Nouvel ordre : {ordered_ids}")

    def refreshLibraryList(self, libraries=None):
        """ Met à jour l'affichage de la liste des bibliothèques """
        self.library_list_widget.clear()
        logger.info("[LibrariesList] Rafraîchissement de la liste des bibliothèques")

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



