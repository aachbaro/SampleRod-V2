from PyQt6.QtWidgets import (
    QWidget,
    QFileDialog,
    QSizePolicy,
)
import logging
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import pyqtSlot, QSettings
from frontend.sample_gui.sample.sample_card import SampleCard
from backend.models.AppContext import AppContext
from backend.services.sample_service import SampleService
import os
from backend.models.normalize_worker import NormalizeWorker
from frontend.sample_gui.sample.sample_list_ui import SampleListUIBuilder
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination

logger = logging.getLogger("sample_list")


class SampleListWidget(QWidget):
    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # stocke le contexte et le service métier
        self.app_context  = app_context
        self.sample_store: SampleService = app_context.sample_store
        self.settings = self.app_context.settings
        self.samples = []  # liste des samples à afficher
        self.selected_ids  = set()        # ensemble des IDs cochés
        self._qs = QSettings("SampleRod", "Main")
        self.samples_per_page = self.settings.getSamplesPerPage()
        self.current_page = 1

        # 1) abonnements aux signaux du service
        self.sample_store.samplesChanged.   connect(self.onSamplesChanged)
        self.sample_store.sampleAdded.      connect(self.onSampleAdded)
        self.sample_store.sampleDeleted.    connect(self.onSampleDeleted)
        self.sample_store.sampleRenamed.    connect(self.onSampleRenamed)
        self.sample_store.sampleMoved.      connect(self.onSampleMoved)
        self.sample_store.sampleDurationChanged.connect(self.onSampleDurationChanged)
        # -> Abonnement aux nouveaux signaux de normalisation
        self.sample_store.sampleStartedNormalization.connect(self.onStartedNormalization)
        self.sample_store.sampleFinishedNormalization.connect(self.onFinishedNormalization)
        self.sample_store.sampleNormalizationFailed.connect(self.onNormalizationFailed)
        self.sample_store.sampleRemovedFromHistory.connect(self.onSampleRemovedFromHistory)
        # 2) stockage des cartes existantes
        self._card_widgets = {}

        # mise à jour en cas de changement de paramètres
        self.settings.samplesPerPageChanged.connect(self.onSamplesPerPageChanged)

        # 3) création de l’UI
        self.init_ui()
        self.pagination = SampleListPagination(self)

        # 4) initialisation de la liste avec le cache actuel
        self.onSamplesChanged(self.sample_store.get_cached())

    def init_ui(self):
        """Construit l'UI (toolbar, scroll, pagination)."""
        self.ui_builder = SampleListUIBuilder(self)
        self.ui_builder.build()

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
        self.updateSelectActions()

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
        card.removeFromHistory.connect(self.sample_store.removeFromHistory)
        card.renameSample.connect(self.rename_sample)
        card.sampleMoved.connect(self.move_sample)

        card.selectionChanged.connect(self.onSelectionChanged)
        card.normalizeClicked.connect(self.onNormalizeClicked)

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

    @pyqtSlot(int, bool)
    def onSelectionChanged(self, sample_id: int, checked: bool):
        logger.info("onSelectionChanged: sample_id=%s, checked=%s", sample_id, checked)
        if checked:
            self.selected_ids.add(sample_id)
        else:
            self.selected_ids.discard(sample_id)

        any_selected = len(self.selected_ids) > 0
        self.bulk_delete_act.setEnabled(any_selected)
        self.bulk_move_act.setEnabled(any_selected)
        self.bulk_normalize_act.setEnabled(any_selected)
        self.bulk_archive_act.setEnabled(any_selected)

        # Désactive le bouton “Renommer” si plus d’un sample est coché
        multiple = len(self.selected_ids) > 1
        for sid, card in self._card_widgets.items():
            card.rename_button.setEnabled(not multiple)

        self.updateSelectActions()

    @pyqtSlot()
    def onAddFiles(self):
        """
        Ouvre un QFileDialog pour sélectionner un ou plusieurs fichiers,
        puis les ajoute un par un via SampleService.add().
        """
        # Filtre les fichiers audio WAV (à adapter si tu veux d'autres extensions)
        last_dir = self._qs.value("lastSampleDir", os.path.expanduser("~"), type=str)
        fichiers, _ = QFileDialog.getOpenFileNames(
            self,
            "Sélectionner des fichiers audio",
            last_dir,
            "Fichiers WAV (*.wav);;Tous les fichiers (*)"
        )
        if not fichiers:
            return  # annulation
        new_dir = os.path.dirname(fichiers[0])
        self._qs.setValue("lastSampleDir", new_dir)

        # Ajouter chaque sample au service (création FS + BD + normalisation auto si activée)
        for path in fichiers:
            existing = next((s for s in self.sample_store.get_cached() if s.path == path), None)
            if existing:
                answer = QMessageBox.question(
                    self,
                    "Sample déjà importé",
                    "Ce sample existe déjà.\nVoulez-vous le retirer de la bibliothèque puis le réimporter en tête ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if answer == QMessageBox.StandardButton.No:
                    continue
                self.sample_store.delete_record_by_path(path)
            try:
                self.sample_store.add(path)
            except Exception as e:
                # En cas d’erreur, on affiche un message et on continue
                QMessageBox.warning(
                    self,
                    "Erreur d’ajout",
                    f"Impossible d’ajouter le fichier :\n{path}\n\n{e}"
                )

    @pyqtSlot(int)
    def onSampleRemovedFromHistory(self, sample_id: int):
        """
        Slot appelé quand on retire un sample de l'historique (BD only) :
        ferme la waveform et détruit la carte sans toucher au fichier.
        """
        card = self._card_widgets.get(sample_id)
        if card:
            # ferme la waveform si ouverte
            self.close_waveforms_for_path(card.sample.path)
            # retire la carte de l’UI
            self.content_layout.removeWidget(card)
            card.deleteLater()
            del self._card_widgets[sample_id]
            # mettre à jour selected_ids si besoin
            self.selected_ids.discard(sample_id)
        self.updateSelectActions()

    @pyqtSlot()
    def bulkRemoveFromHistory(self):
        """Retire en bloc les samples sélectionnés de l’historique (BD only)."""
        if not self.selected_ids:
            return

        # confirmation
        reply = QMessageBox.question(
            self,
            "Confirmer la suppression de l'historique",
            f"Voulez-vous vraiment retirer les {len(self.selected_ids)} échantillons de l’historique ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        to_remove = list(self.selected_ids)
        for sample_id in to_remove:
            self.sample_store.removeFromHistory(sample_id)

        # on vide la sélection et on désactive les actions
        self.selected_ids.clear()
        self.bulk_delete_act.setEnabled(False)
        self.bulk_move_act.setEnabled(False)
        self.bulk_normalize_act.setEnabled(False)
        self.bulk_archive_act.setEnabled(False)
        self.updateSelectActions()

    def refreshList(self):
        """Reconstruit la liste des cartes en fonction de la pagination."""
        # 1) tri décroissant par date de création
        ordered_samples = sorted(
            self.samples, key=lambda s: s.id, reverse=True
        )

        total_samples = len(ordered_samples)
        start_idx = (self.current_page - 1) * self.samples_per_page
        end_idx = start_idx + self.samples_per_page
        page_samples = ordered_samples[start_idx:end_idx]

        # 2) on supprime les cartes obsolètes
        ids_courants = {s.id for s in page_samples}
        for ancien_id in list(self._card_widgets):
            if ancien_id not in ids_courants:
                w = self._card_widgets.pop(ancien_id)
                # stoppe toute lecture via waveform avant de retirer la carte
                self.close_waveforms_for_path(w.sample.path)
                self.content_layout.removeWidget(w)
                w.deleteLater()

        # 3) on (ré)crée / met à jour les cartes dans l'ordre de la page
        cartes_ordonnees = []
        for samp in page_samples:
            if samp.id in self._card_widgets:
                card = self._card_widgets[samp.id]
                # Si on veut rafraîchir la donnée du sample (en cas de mise à jour)
                card.sample = samp
                card.refresh_display()
            else:
                # nouvelle carte, connexion des signaux
                card = SampleCard(samp, self.app_context)
                card.deleteSample.connect(self.delete_sample)
                card.removeFromHistory.connect(self.sample_store.removeFromHistory)
                card.renameSample.connect(self.rename_sample)
                card.sampleMoved.connect(self.move_sample)
                card.normalizeClicked.connect(self.onNormalizeClicked)
                card.selectionChanged.connect(self.onSelectionChanged)

                # Signaux retour du service
                self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
                self.sample_store.sampleMoved   .connect(card.onMoveSuccess)
                # On stocke la carte
                self._card_widgets[samp.id] = card

                # Si l'ID était déjà dans self.selected_ids, on coche la checkbox
                if samp.id in self.selected_ids:
                    card.checkbox.setChecked(True)

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

        if total_samples == 0:
            self.updatePaginationLabel(0, 0, 0)
        else:
            self.updatePaginationLabel(
                start_idx + 1, min(end_idx, total_samples), total_samples
            )

        self.updateSelectActions()


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
            self.selected_ids.discard(sample_id)
        self.updateSelectActions()

    @pyqtSlot(int, str, str)
    def onSampleRenamed(self, sample_id: int, old_path: str, new_path: str):
        """Après renommage : ferme la waveform et met à jour la carte."""
        card = self._card_widgets.get(sample_id)
        if card:
            self.close_waveforms_for_path(old_path)
            card.sample.name = os.path.splitext(os.path.basename(new_path))[0]
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
            # 1) On reconstruit la combo “dossier” pour refléter le nouveau folder
            card.updateLibraryCombo(self.app_context.settings.libraries)
            # 2) On rafraîchit tout de même l’affichage du nom (et autres labels)
            card.refresh_display()

    @pyqtSlot(int, float)
    def onSampleDurationChanged(self, sample_id: int, new_duration: float):
        card = self._card_widgets.get(sample_id)
        if card:
            card.sample.duration = new_duration
            card.length_label.setText(f"{new_duration:.1f}s")

    # ─────────────────── Bulk Actions ───────────────────
    def bulkDelete(self):
        """Supprime tous les samples sélectionnés après confirmation."""
        if not self.selected_ids:
            return
        reply = QMessageBox.question(
            self,
            "Confirmer la suppression",
            f"Voulez-vous vraiment supprimer les {len(self.selected_ids)} échantillons sélectionnés ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Attention : créer une copie de la liste avant d'itérer, 
            # car delete() met à jour self.selected_ids via onSampleDeleted
            to_delete = list(self.selected_ids)
            # Si on supprime un sample en cours de lecture, on coupe l'audio…
            current = self.app_context.audio_player.current_sample_id
            if current in to_delete:
                self.app_context.audio_player.clear_audio()

            self.sample_store.bulkDelete(to_delete)
            # Après suppression, on vide selected_ids
            self.selected_ids.clear()
            self.bulk_delete_act.setEnabled(False)
            self.bulk_move_act.setEnabled(False)
            self.bulk_normalize_act.setEnabled(False)
            self.updateSelectActions()

    def bulkMove(self):
        if not self.selected_ids:
            return

        # Ouvre un QDialog pour choisir un dossier cible
        dossier = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination"
        )
        if not dossier:
            return

        for sample_id in list(self.selected_ids):
            self.sample_store.move(sample_id, dossier)

        # (Optionnel) Décoche tout à la fin :
        self.selected_ids.clear()
        self.bulk_delete_act.setEnabled(False)
        self.bulk_move_act.setEnabled(False)
        self.bulk_normalize_act.setEnabled(False)
        self.updateSelectActions()

    def bulkNormalize(self):
        """
        Lance une normalisation LUFS sur tous les samples cochés.
        """
        if not self.selected_ids:
            return
        for sample_id in list(self.selected_ids):
            samp = next((s for s in self.sample_store.get_cached() if s.id == sample_id), None)
            if samp is None:
                continue
            # Créer un NormalizeWorker pour chacun
            worker = NormalizeWorker(
                sample_id=sample_id,
                file_path=samp.path,
                mode="lufs",
                target_db=self.app_context.settings.getNormalizationLevel()
            )
            worker.startedNormalization.connect(self.onStartedNormalization)
            worker.finishedNormalization.connect(self.onFinishedNormalization)
            worker.normalizationFailed.connect(self.onNormalizationFailed)
            worker.start()
            self.app_context.sample_store._normalize_threads[sample_id] = worker

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

    def updateSelectActions(self):
        any_samples = bool(self._card_widgets)
        all_selected = len(self.selected_ids) == len(self._card_widgets)
        none_selected = len(self.selected_ids) == 0

        self.select_all_act.setEnabled(any_samples and not all_selected)
        self.deselect_all_act.setEnabled(any_samples and not none_selected)

    @pyqtSlot()
    def onSelectAll(self):
        for card in self._card_widgets.values():
            card.checkbox.setChecked(True)

    @pyqtSlot()
    def onDeselectAll(self):
        for card in self._card_widgets.values():
            card.checkbox.setChecked(False)

    # ─── Drag & Drop depuis l’explorateur ───

    def dragEnterEvent(self, event):
        fmt = event.mimeData().formats()
        print("DirectoryWidget dragEnter formats:", fmt)
        # N’accepte que si on a des URLs (fichiers)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # Même logique qu’au dragEnter
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """
        Lorsqu’on lâche des fichiers :
        - on récupère les chemins locaux
        - on crée les samples
        - on coche automatiquement les cases correspondantes
        """
        urls = event.mimeData().urls()
        if not urls:
            return

        # 1) Extraire les fichiers locaux .wav (à adapter si besoin)
        paths = []
        for u in urls:
            local = u.toLocalFile()
            if os.path.isfile(local) and local.lower().endswith(".wav"):
                paths.append(local)

        if not paths:
            return

        # 2) Hook temporaire pour récupérer les nouveaux IDs
        new_ids = []
        def _on_added(sid):
            new_ids.append(sid)
        self.sample_store.sampleAdded.connect(_on_added)

        # 3) Ajouter chaque fichier
        for p in paths:
            existing = next((s for s in self.sample_store.get_cached() if s.path == p), None)
            if existing:
                answer = QMessageBox.question(
                    self,
                    "Sample déjà importé",
                    "Ce sample existe déjà.\nVoulez-vous le retirer de la bibliothèque puis le réimporter en tête ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if answer == QMessageBox.StandardButton.No:
                    continue
                self.sample_store.delete_record_by_path(p)
            self.sample_store.add(p)

        # 4) Déconnecter le hook
        self.sample_store.sampleAdded.disconnect(_on_added)

        # 5) Cocher automatiquement les cartes créées
        for sid in new_ids:
            card = self._card_widgets.get(sid)
            if card:
                card.checkbox.setChecked(True)

        # 6) On scroll vers le haut pour voir les nouveaux items
        self.scroll_area.verticalScrollBar().setValue(0)

    def updatePaginationLabel(self, start_idx: int, end_idx: int, total_samples: int):
        """Met à jour le label de pagination."""
        self.pagination.update_label(start_idx, end_idx, total_samples)

    @pyqtSlot(int)
    def onSamplesPerPageChanged(self, count: int):
        """Slot appelé lorsque le paramètre de pagination change."""
        self.pagination.on_samples_per_page_changed(count)

    def setCurrentPage(self, page: int):
        """Change la page actuelle et rafraîchit la liste."""
        self.pagination.set_current_page(page)

    def change_page(self, page: int):
        """Gere le changement de page et arrete la lecture si necessaire."""
        self.pagination.change_page(page)

    def _prev_page(self):
        self.pagination.prev_page()

    def _next_page(self):
        self.pagination.next_page()

