from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
from PyQt6.QtCore import pyqtSignal
from frontend.sample_gui.sample_card import SampleCard
from backend.models.sample import Sample
from backend.db import Base, SessionLocal
import os

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
                    card.renameSample.connect(self.rename_sample)
                    card.renameSample.connect(self.sampleRenamed.emit)
                    card.playSample.connect(self.samplePlayed.emit)

                    self.content_layout.addWidget(card)

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
        print("frontend: sample_list: delete sample: ", sample_to_delete_id)

        # Trouver et supprimer le SampleCard correspondant
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, SampleCard) and widget.sample.id == sample_to_delete_id:
                    widget.deleteLater()
                    self.content_layout.removeWidget(widget)
                    break  # Arrêter dès qu'on a supprimé le bon widget

        # Supprimer aussi le sample de self.samples
        self.samples = [s for s in self.samples if s.id != sample_to_delete_id]
        try:
            session = SessionLocal()
            session.expire_on_commit = False
            sample = session.query(Sample).filter(Sample.id == sample_to_delete_id).first()
            if sample:
                if os.path.exists(sample.path):
                    try:
                        os.remove(sample.path)
                        print(f"Fichier {sample.path} supprimé du système de fichiers.")
                    except Exception as e:
                        print(f"Erreur lors de la suppression du fichier {sample.path}: {str(e)}")
                else:
                    print(f"Fichier {sample.path} introuvable dans le système de fichiers. Suppression uniquement dans la base de données.")
                session.delete(sample)
                session.commit()
        finally:
            session.close()

    def rename_sample(self, sample_id, new_name):
        """Renomme le fichier associé à un sample et met à jour l'interface et la base de données."""
        print(f"frontend: sample_list: rename sample {sample_id} -> {new_name}")

        try:
            session = SessionLocal()
            session.expire_on_commit = False

            # Trouver le sample dans la base de données
            sample = session.query(Sample).filter(Sample.id == sample_id).first()

            if sample:
                old_path = sample.path
                dir_name = os.path.dirname(old_path)  # Répertoire du fichier
                file_ext = os.path.splitext(old_path)[1]  # Extension du fichier
                new_path = os.path.join(dir_name, new_name + file_ext)  # Nouveau chemin

                if os.path.exists(old_path):
                    try:
                        os.rename(old_path, new_path)  # Renommer le fichier
                        print(f"Fichier renommé : {old_path} -> {new_path}")

                        # Mettre à jour le sample dans la base de données
                        sample.name = new_name
                        sample.path = new_path
                        session.commit()
                    except Exception as e:
                        print(f"Erreur lors du renommage du fichier : {str(e)}")
                else:
                    print(f"Fichier introuvable : {old_path}. Mise à jour uniquement en base de données.")

                    # Mettre à jour seulement en base de données
                    sample.name = new_name
                    session.commit()

                # Mettre à jour l'affichage du SampleCard correspondant
                for i in range(self.content_layout.count()):
                    item = self.content_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, SampleCard) and widget.sample.id == sample_id:
                            break  # Arrêter après mise à jour du bon widget

        finally:
            session.close()
