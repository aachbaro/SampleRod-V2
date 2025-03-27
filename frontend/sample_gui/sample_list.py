from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
from PyQt6.QtCore import pyqtSignal
from frontend.sample_gui.sample_card import SampleCard
from backend.models.sample import Sample
from backend.db import Base, SessionLocal

class SampleListWidget(QWidget):
    # Signal pour notifier des actions sur un sample, à connecter aux fonctions de ton store/backend
    sampleDeleted = pyqtSignal(object)
    sampleRenamed = pyqtSignal(object, str)
    samplePlayed = pyqtSignal(object)

    def __init__(self, samples, parent=None):
        """
        samples : liste d'objets Sample.
        """
        super().__init__(parent)
        self.samples = samples  # La liste des samples
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(10)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        self.refreshList()

    def refreshList(self):
        # Vider le contenu
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Inverser l'ordre des samples avant de les parcourir
        session = SessionLocal()  # Créez une nouvelle session ici
        try:
            for sample in reversed(self.samples):
                # Rafraîchir l'objet sample avec la session courante
                sample = session.merge(sample)
                if sample is not None: #Verifie que le sample n'est pas None
                    card = SampleCard(sample)
                    card.deleteSample.connect(self.delete_sample)
                    card.renameSample.connect(self.sampleRenamed.emit)
                    card.playSample.connect(self.samplePlayed.emit)
                    self.content_layout.addWidget(card)

                    # Ajouter un séparateur après chaque SampleCard
                    separator = QFrame()
                    separator.setFrameShape(QFrame.Shape.HLine)
                    separator.setFrameShadow(QFrame.Shadow.Sunken)
                    self.content_layout.addWidget(separator)
        finally:
            session.close() #ferme la session

        self.content_layout.addStretch()

    def addSampleToList(self, new_sample):
        to_add = Sample(new_sample)
        self.samples.append(to_add)
        self.refreshList()

    def delete_sample(self, sample_to_delete_id):
        """Supprime le sample de self.samples, rafraîchit la liste et émet le signal."""
        # Supprime l'objet sample de la liste en utilisant l'ID
        session = SessionLocal()
        session.expire_on_commit = False
        self.samples = [sample for sample in list(self.samples) if sample.id != sample_to_delete_id]
        self.refreshList()
        self.sampleDeleted.emit(sample_to_delete_id) #emit l'id
        session.close()