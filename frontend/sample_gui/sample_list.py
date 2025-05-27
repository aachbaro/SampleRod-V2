from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
from PyQt6.QtCore import pyqtSignal
from frontend.sample_gui.sample_card import SampleCard
from backend.models.sample import Sample
from backend.db import Base, SessionLocal
import os
from backend.models.User import User
import shutil
from backend.db import SessionLocal
from backend.models.sample import Sample as DBSample

class SampleListWidget(QWidget):
    # Signal pour notifier des actions sur un sample, à connecter aux fonctions de ton store/backend
    sampleRenameSuccess = pyqtSignal(int, str)  # ID et nouveau nom
    sampleRenameError = pyqtSignal(int, str)
    sampleMoved = pyqtSignal(int, str)

    def __init__(self, samples, user: User, parent=None):
        super().__init__(parent)
        self.samples = samples
        self.user    = user
        self._card_widgets = {}  

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
        # 1) on crée la liste inversée des Sample (pour afficher du plus récent au plus ancien)
        new_samples = list(reversed(self.samples))

        # 2) on ouvre une session pour merger et récupérer les ids en session active
        session = SessionLocal()
        try:
            merged = [session.merge(s) for s in new_samples]
            new_ids = {s.id for s in merged}
            
            # 3) on supprime du layout les widgets dont l’id n’est plus dans new_ids
            for old_id in list(self._card_widgets):
                if old_id not in new_ids:
                    w = self._card_widgets.pop(old_id)
                    self.content_layout.removeWidget(w)
                    w.deleteLater()

            # 4) on prépare la liste ordonnée des widgets à afficher
            ordered = []
            for samp in merged:
                if samp.id in self._card_widgets:
                    card = self._card_widgets[samp.id]
                else:
                    # nouvelle carte
                    card = SampleCard(samp, self.user)
                    card.deleteSample.connect(self.delete_sample)
                    card.renameSample.connect(self.rename_sample)
                    card.sampleMoved.connect(self.move_sample)
                    self.sampleRenameSuccess.connect(card.onRenameSuccess)
                    self.sampleRenameError.connect(card.onRenameError)
                    self.sampleMoved.connect(card.onMoveSuccess)
                    card.newSampleSaved.connect(self.addSampleToList)
                    self._card_widgets[samp.id] = card
                ordered.append(card)

        finally:
            session.close()

        # 5) on vide le layout (sans supprimer les widgets)
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                self.content_layout.removeWidget(w)

        # 6) on ré‐insère dans l’ordre
        for w in ordered:
            self.content_layout.addWidget(w)
        self.content_layout.addStretch()

    def addSampleToList(self, new_path: str):
        """
        Après avoir sauvegardé un WAV (overwrite ou copy),
        on met à jour **in-place** la carte existante ou on en crée une nouvelle.
        """
        from backend.db import SessionLocal
        from backend.models.sample import Sample as DBSample

        session = SessionLocal()
        try:
            # 1) Récupère l'enregistrement qui vient d’être écrit
            fresh = session.query(DBSample).filter_by(path=new_path).first()
            if not fresh:
                return

            # 2) Si on a déjà une carte pour ce sample → overwrite
            if fresh.id in self._card_widgets:
                card = self._card_widgets[fresh.id]
                # Met à jour à la fois le modèle et l'affichage
                card.sample.duration   = fresh.duration
                card.sample.created_at = fresh.created_at
                card.length_label.setText(f"{fresh.duration:.1f}s")
                card.date_label.setText(fresh.created_at.strftime("%d/%m/%Y %H:%M"))

            # 3) Sinon c'est une copy → on ajoute un nouveau SampleCard
            else:
                # On garde la liste interne à jour
                self.samples.insert(0, fresh)

                # Création et branchement des signaux
                card = SampleCard(fresh, self.user)
                card.deleteSample.connect(self.delete_sample)
                card.renameSample.connect(self.rename_sample)
                card.sampleMoved.connect(self.move_sample)
                self.sampleRenameSuccess.connect(card.onRenameSuccess)
                self.sampleRenameError.connect(card.onRenameError)
                self.sampleMoved.connect(card.onMoveSuccess)
                card.newSampleSaved.connect(self.addSampleToList)

                # On garde la référence puis on insère en haut de la vue
                self._card_widgets[fresh.id] = card
                self.content_layout.insertWidget(0, card)
        finally:
            session.close()

    def delete_sample(self, sample_to_delete_id):
        print("frontend: sample_list: delete sample:", sample_to_delete_id)
        session = SessionLocal()
        try:
            session.expire_on_commit = False
            sample = session.query(Sample).get(sample_to_delete_id)
            if not sample:
                print(f"Sample {sample_to_delete_id} introuvable en DB.")
                return

            # 1) Si on est en train de lire CE sample, on stoppe et on unload
            if getattr(self.user.audio_player, "current_sample_path", None) == sample.path:
                self.user.audio_player.clear_audio()
                try:
                    # pygame 2.1+ : décharge le fichier de la mémoire  
                    import pygame
                    pygame.mixer.music.unload()
                except Exception:
                    pass

            # 2) Fermer tout WaveformWidget éventuel dans les SampleCard
            #    (si tu as un signal pour ça, tu peux l'émettre ici)
            #    Par exemple :
            self.close_waveforms_for_path(sample.path)

            # 3) Supprimer le fichier du disque
            if os.path.exists(sample.path):
                try:
                    os.remove(sample.path)
                    print(f"Fichier {sample.path} supprimé du disque.")
                except Exception as e:
                    print(f"Erreur suppr. fichier : {e}")
            else:
                print(f"Fichier introuvable: {sample.path}")

            # 4) Supprimer l’entrée en base
            session.delete(sample)
            session.commit()
        finally:
            session.close()

        # 5) Recharger la liste depuis la base et rafraîchir l'UI
        self.reload_samples_from_db()
        self.refreshList()

    def close_waveforms_for_path(self, path):
        for i in range(self.content_layout.count()):
            w = self.content_layout.itemAt(i).widget()
            if isinstance(w, SampleCard) and w.sample.path == path and w.wave_edition_widget:
                # stoppe la lecture
                try:
                    w.wave_edition_widget.stop_audio()
                except:
                    pass
                try:
                    w.wave_edition_widget.timer.stop()
                except:
                    pass

                w.waveform_layout.removeWidget(w.wave_edition_widget)
                w.wave_edition_widget.deleteLater()
                w.wave_edition_widget = None

    def reload_samples_from_db(self):
        """Recharge self.samples depuis la base."""
        session = SessionLocal()
        try:
            self.samples = session.query(Sample).all()
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

            if getattr(self.user.audio_player, "current_sample_path", None) == sample.path:
                self.user.audio_player.clear_audio()
                try:
                    # pygame 2.1+ : décharge le fichier de la mémoire  
                    import pygame
                    pygame.mixer.music.unload()
                except Exception:
                    pass

            self.close_waveforms_for_path(sample.path)

            # 🛑 Etape 2 : fermer tout WaveformWidget affichant ce fichier
            self.close_waveforms_for_path(old_path)

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
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, SampleCard) and widget.sample.id == sample_id:
                # ancien path
                old = widget.sample.path
                directory = os.path.dirname(old)
                ext = os.path.splitext(old)[1]
                new_path = os.path.join(directory, new_name + ext)

                widget.sample.name = new_name
                widget.sample.path = new_path

                widget.refresh_display()
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