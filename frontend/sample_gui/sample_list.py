from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import pyqtSlot
from frontend.sample_gui.sample_card import SampleCard
from backend.models.AppContext import AppContext
from backend.services.sample_service import SampleService
import os
from backend.models.normalize_worker import NormalizeWorker


class SampleListWidget(QWidget):
    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)

        # stocke le contexte et le service métier
        self.app_context  = app_context
        self.sample_store: SampleService = app_context.sample_store
        self.samples = []  # liste des samples à afficher

        # 1) abonnements aux signaux du service
        self.sample_store.samplesChanged.   connect(self.onSamplesChanged)
        self.sample_store.sampleAdded.      connect(self.onSampleAdded)
        self.sample_store.sampleDeleted.    connect(self.onSampleDeleted)
        self.sample_store.sampleRenamed.    connect(self.onSampleRenamed)
        self.sample_store.sampleMoved.      connect(self.onSampleMoved)
        # -> Abonnement aux nouveaux signaux de normalisation
        self.sample_store.sampleStartedNormalization.connect(self.onStartedNormalization)
        self.sample_store.sampleFinishedNormalization.connect(self.onFinishedNormalization)
        self.sample_store.sampleNormalizationFailed.connect(self.onNormalizationFailed)
        # 2) stockage des cartes existantes
        self._card_widgets = {}

        # 3) création de l’UI
        self.init_ui()

        # 4) initialisation de la liste avec le cache actuel
        self.onSamplesChanged(self.sample_store.get_cached())

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

    @pyqtSlot(list)
    def onSamplesChanged(self, samples: list):
        """
        Slot appelé quand SampleService met à jour son cache.
        » Met à jour la liste interne et reconstruit les cartes.
        """
        # 1) on stocke la nouvelle liste
        self.samples = samples
        # 2) on reconstruit l'affichage
        self.refreshList()

    @pyqtSlot(int)
    def onSampleAdded(self, sample_id: int):
        """
        Quand un nouveau sample est ajouté :
        - on le récupère dans le cache
        - on l'ajoute en tête de self.samples
        - on crée et on affiche sa SampleCard tout en haut
        """
        # 1) trouve l'objet Sample dans le cache du service
        new_sample = next(
            (s for s in self.sample_store.get_cached() if s.id == sample_id),
            None
        )
        if new_sample is None:
            return

        # 2) l'ajoute en début de liste interne
        self.samples.insert(0, new_sample)

        # 3) crée la carte et connecte uniquement ses signaux
        card = SampleCard(new_sample, self.app_context)
        card.deleteSample.connect(self.delete_sample)
        card.renameSample.connect(self.rename_sample)
        card.sampleMoved.connect(self.move_sample)
        # signaux retour (rename/move)
        self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
        self.sample_store.sampleMoved  .connect(card.onMoveSuccess)

        # 4) stocke la carte et affiche-la en tête du layout
        self._card_widgets[sample_id] = card
        self.content_layout.insertWidget(0, card)

    @pyqtSlot(int)
    def delete_sample(self, sample_id: int):
        """Déclenche la suppression via le service."""
        self.sample_store.delete(sample_id)

    @pyqtSlot(int, str)
    def rename_sample(self, sample_id: int, new_name: str):
        """Déclenche le renommage via le service."""
        self.sample_store.rename(sample_id, new_name)

    @pyqtSlot(int, str)
    def move_sample(self, sample_id: int, target_folder: str):
        """Déclenche le déplacement via le service."""
        self.sample_store.move(sample_id, target_folder)

    @pyqtSlot(int)
    def onStartedNormalization(self, sample_id: int):
        card = self._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationStarted()

    @pyqtSlot(int)
    def onFinishedNormalization(self, sample_id: int):
        card = self._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationFinished()

    @pyqtSlot(int)
    def onNormalizeClicked(self, sample_id: int):
        """
        Lorsque l'utilisateur clique sur "Normalize" manuellement dans la carte :
        on crée un NormalizeWorker ad-hoc et on l'exécute.
        """
        samp = next((s for s in self.sample_store.get_cached() if s.id == sample_id), None)
        if samp is None:
            return

        worker = NormalizeWorker(
            sample_id=sample_id,
            file_path=samp.path,
            mode="lufs",
            target_db=self.app_context.settings.getNormalizationLevel()
        )
        worker.startedNormalization.connect(self.onStartedNormalization)
        worker.finishedNormalization.connect(self.onFinishedNormalization)
        worker.start()
        # Conserver la référence pour ne pas que le thread soit détruit
        self.app_context.sample_store._normalize_threads[sample_id] = worker

    @pyqtSlot(int, str)
    def onNormalizationFailed(self, sample_id: int, message: str):
        card = self._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationError(message)

    def refreshList(self):
        # 1) on prend la liste inversée (du plus récent au plus ancien)
        ordered_samples = list(reversed(self.samples))

        # 2) on supprime les cartes obsolètes
        ids_courants = {s.id for s in ordered_samples}
        for ancien_id in list(self._card_widgets):
            if ancien_id not in ids_courants:
                w = self._card_widgets.pop(ancien_id)
                self.content_layout.removeWidget(w)
                w.deleteLater()

        # 3) on (ré)crée / met à jour les cartes dans l'ordre
        cartes_ordonnees = []
        for samp in ordered_samples:
            if samp.id in self._card_widgets:
                card = self._card_widgets[samp.id]
                # Si on veut rafraîchir la donnée du sample (en cas de mise à jour)
                card.sample = samp
                card.refresh_display()
            else:
                # nouvelle carte, connexion des signaux
                card = SampleCard(samp, self.app_context)
                card.deleteSample.connect(self.delete_sample)
                card.renameSample.connect(self.rename_sample)
                card.sampleMoved.connect(self.move_sample)
                card.normalizeClicked.connect(self.onNormalizeClicked)

                # Signaux retour du service
                self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
                self.sample_store.sampleMoved   .connect(card.onMoveSuccess)
                # On stocke la carte
                self._card_widgets[samp.id] = card
            cartes_ordonnees.append(card)

        # 4) on vide le layout (sans supprimer les widgets)
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                self.content_layout.removeWidget(w)

        # 5) on ajoute les cartes dans l’ordre, puis un stretch final
        for w in cartes_ordonnees:
            self.content_layout.addWidget(w)
        self.content_layout.addStretch()


    # ──────────── SLOTS SERVICE → UI ────────────
    @pyqtSlot(int)
    def onSampleDeleted(self, sample_id: int):
        """Après suppression : ferme la waveform et supprime la carte."""
        card = self._card_widgets.get(sample_id)
        if card:
            self.close_waveforms_for_path(card.sample.path)
            self.content_layout.removeWidget(card)
            card.deleteLater()
            del self._card_widgets[sample_id]

    @pyqtSlot(int, str)
    def onSampleRenamed(self, sample_id: int, new_name: str):
        """Après renommage : ferme la waveform, met à jour nom & chemin, rafraîchit."""
        card = self._card_widgets.get(sample_id)
        if card:
            old_path = card.sample.path
            self.close_waveforms_for_path(old_path)
            ext = os.path.splitext(old_path)[1]
            new_path = os.path.join(os.path.dirname(old_path), new_name + ext)
            card.sample.name = new_name
            card.sample.path = new_path
            card.refresh_display()

    @pyqtSlot(int, str)
    def onSampleMoved(self, sample_id: int, target_folder: str):
        """Après déplacement : ferme la waveform, met à jour le chemin, rafraîchit."""
        card = self._card_widgets.get(sample_id)
        if card:
            old_path = card.sample.path
            self.close_waveforms_for_path(old_path)
            new_path = os.path.join(target_folder, os.path.basename(old_path))
            card.sample.path = new_path
            card.refresh_display()

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

