from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
from PyQt6.QtCore import pyqtSignal
from frontend.sample_gui.sample_card import SampleCard
from backend.models.sample import Sample
from backend.db import Base, SessionLocal
import os
from backend.models.User import User
import shutil

class SampleListWidget(QWidget):
    # Signal pour notifier des actions sur un sample, à connecter aux fonctions de ton store/backend
    sampleRenameSuccess = pyqtSignal(int, str)  # ID et nouveau nom
    sampleRenameError = pyqtSignal(int, str)
    sampleMoved = pyqtSignal(int, str)

    def __init__(self, samples, user: User, parent=None):
        """
        samples : liste d'objets Sample.
        """
        super().__init__(parent)
        self.samples = samples  # La liste des samples
        self.user = user
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
                    card = SampleCard(sample, self.user)
                    card.deleteSample.connect(self.delete_sample)
                    card.renameSample.connect(self.rename_sample)
                    card.sampleMoved.connect(self.move_sample)
                    self.sampleRenameSuccess.connect(card.onRenameSuccess)
                    self.sampleRenameError.connect(card.onRenameError)
                    self.sampleMoved.connect(card.onMoveSuccess)

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

            if not sample:
                print(f"Sample introuvable en base : {sample_id}")
                return

            old_path = sample.path

            if not old_path or not os.path.exists(old_path):
                print(f"Fichier introuvable : {old_path}. Mise à jour uniquement en base de données.")
                sample.name = new_name
                session.commit()
                self.update_sample_card(sample_id, new_name)
                return

            dir_name = os.path.dirname(old_path)  # Répertoire du fichier
            file_ext = os.path.splitext(old_path)[1]  # Extension du fichier
            new_path = os.path.join(dir_name, new_name + file_ext)  # Nouveau chemin

            if os.path.exists(new_path):
                print(f"Erreur : un fichier avec ce nom existe déjà -> {new_path}")
                return

            try:
                os.rename(old_path, new_path)  # Renommer le fichier
                print(f"Fichier renommé : {old_path} -> {new_path}")

                # Mettre à jour le sample dans la base de données
                sample.name = new_name
                sample.path = new_path
                session.commit()
            except Exception as e:
                print(f"Erreur lors du renommage du fichier : {str(e)}")
            finally:
                self.update_sample_card(sample_id, new_name)

        finally:
            session.close()

    def move_sample(self, sample_id, new_dir):
        """Déplace le fichier associé à un sample et met à jour l'interface et la base de données."""
        print(f"frontend: sample_list: move sample {sample_id} -> {new_dir}")

        try:
            session = SessionLocal()
            session.expire_on_commit = False

            sample = session.query(Sample).filter(Sample.id == sample_id).first()

            if not sample:
                print(f"Sample introuvable en base : {sample_id}")
                return

            old_path = sample.path

            if not old_path or not os.path.exists(old_path):
                print(f"Fichier introuvable : {old_path}. Mise à jour uniquement en base de données.")
                sample.path = os.path.join(new_dir, os.path.basename(old_path))
                session.commit()
                self.update_sample_card_move(sample_id, new_dir)
                return

            new_path = os.path.join(new_dir, os.path.basename(old_path))
            print("new_dir:", new_dir)
            print("basename etc..:",os.path.basename(old_path))
            print("new_path: ", new_path)

            if os.path.exists(new_path):
                print(f"Erreur : un fichier avec ce nom existe déjà dans le répertoire de destination -> {new_path}")
                return

            try:
                shutil.move(old_path, new_path)
                print(f"Fichier déplacé : {old_path} -> {new_path}")

                sample.path = new_path
                session.commit()
            except Exception as e:
                print(f"Erreur lors du déplacement du fichier : {str(e)}")
            finally:
                self.update_sample_card_move(sample_id, new_dir)

        finally:
            session.close()

    def update_sample_card(self, sample_id, new_name):
        """Met à jour le SampleCard correspondant à l'ID donné."""
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, SampleCard) and widget.sample.id == sample_id:
                    widget.sample.name = new_name  # Mise à jour du modèle de données
                    widget.refresh_display()  # Ajoute cette ligne si une méthode similaire existe
                    break

    def update_sample_card_move(self, sample_id, new_dir):
        """Met à jour le SampleCard correspondant à l'ID donné après le déplacement."""
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, SampleCard) and widget.sample.id == sample_id:
                    widget.sample.path = os.path.join(new_dir, os.path.basename(widget.sample.path))
                    widget.refresh_display()
                    break