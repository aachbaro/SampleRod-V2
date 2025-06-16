from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QToolBar,
    QToolButton,
    QMenu,
    QFileDialog,
    QSizePolicy,
    QLabel,
    QHBoxLayout,
)
import logging
logger = logging.getLogger("sample_list")
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import pyqtSlot, pyqtSignal, QSize, Qt, QSettings, QThread
import qtawesome as qta
from frontend.sample_gui.sample_card import SampleCard
from backend.models.AppContext import AppContext
from backend.services.sample_service import SampleService
from frontend.sample_gui.directory_filter_card import DirectoryFilterCard
import os
from backend.models.normalize_worker import NormalizeWorker


class SampleListWidget(QWidget):
    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # stocke le contexte et le service métier
        self.app_context  = app_context
        self.sample_store: SampleService = app_context.sample_store
        self.samples = []  # liste des samples à afficher
        self.active_dirs = set()  # dossiers actifs pour le filtrage
        self.selected_ids  = set()        # ensemble des IDs cochés
        self._qs = QSettings("SampleRod", "Main")
        # Utilisé pour ignorer le rafraîchissement global quand on met à jour
        # un seul sample (ajout, renommage, suppression, déplacement…) depuis
        # cette vue.
        self._ignore_next_refresh = False

        # pagination
        self.page_size = 50
        self.current_offset = 0
        self.is_loading = False
        self.more_available = True
        self._loader_thread = None

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
        self.sample_store.sampleRemovedFromHistory.connect(self.onSampleRemovedFromHistory)
        self.app_context.settings.librariesChanged.connect(self.updateFilterOptions)
        # 2) stockage des cartes existantes
        self._card_widgets = {}
        self._filter_cards = {}

        # 3) création de l’UI
        self.init_ui()

        # 4) initialisation de la liste avec le cache actuel
        self.refresh_samples()

    def init_ui(self):
        """
        Construit l’UI, comprenant en haut une barre de 'bulk actions' 
        (boutons Supprimer, Déplacer, Normaliser la sélection),
        puis la zone scrollable des cartes.
        """
        main_layout = QVBoxLayout(self)

        # ─── Zone 'Bulk Actions' ───

        self.toolbar = QToolBar("Bulk Actions")
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        main_layout.addWidget(self.toolbar)

        # Action principale : ajout de fichiers
        self.add_files_act = QAction(qta.icon('fa5s.folder-open'), "Ajouter fichiers…", self)
        self.add_files_act.setToolTip("Ajouter un ou plusieurs fichiers audio")
        self.add_files_act.triggered.connect(self.onAddFiles)
        self.toolbar.addAction(self.add_files_act)

        self.select_all_act   = QAction(qta.icon('fa5s.check-double'), "Tout cocher", self)
        self.deselect_all_act = QAction(qta.icon('fa5s.times-circle'), "Tout décocher", self)
        self.select_all_act.triggered.connect(self.onSelectAll)
        self.deselect_all_act.triggered.connect(self.onDeselectAll)
        self.toolbar.addAction(self.select_all_act)
        self.toolbar.addAction(self.deselect_all_act)

        self.toolbar.addSeparator()

        # Actions sur la sélection
        self.bulk_archive_act = QAction(qta.icon('fa5s.times-circle', color='lightgray'), "Retirer de l’historique", self)
        self.bulk_archive_act.setEnabled(False)
        self.bulk_archive_act.triggered.connect(self.bulkRemoveFromHistory)

        self.bulk_delete_act = QAction(qta.icon('fa5s.trash-alt', color='red'), "Supprimer", self)
        self.bulk_delete_act.setEnabled(False)
        self.bulk_delete_act.triggered.connect(self.bulkDelete)

        self.bulk_move_act = QAction(qta.icon('fa5s.folder', color='lightgray'), "Déplacer…", self)
        self.bulk_move_act.setEnabled(False)
        self.bulk_move_act.triggered.connect(self.bulkMove)

        self.bulk_normalize_act = QAction(qta.icon('fa5s.bolt', color='orange'), "Normaliser", self)
        self.bulk_normalize_act.setEnabled(False)
        self.bulk_normalize_act.triggered.connect(self.bulkNormalize)

        self.actions_menu = QMenu(self)
        self.actions_menu.addAction(self.bulk_archive_act)
        self.actions_menu.addAction(self.bulk_delete_act)
        self.actions_menu.addAction(self.bulk_move_act)
        self.actions_menu.addAction(self.bulk_normalize_act)

        self.actions_btn = QToolButton(self)
        self.actions_btn.setText("Actions sélection")
        self.actions_btn.setIcon(qta.icon('fa5s.list'))
        self.actions_btn.setMenu(self.actions_menu)
        self.actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.actions_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.addWidget(self.actions_btn)

        # ─── Filtres sous forme de cartes ───
        self.filter_scroll = QScrollArea()
        self.filter_scroll.setWidgetResizable(True)
        self.filter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.filter_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.filter_scroll.setFixedHeight(50)
        self.filter_container = QWidget()
        self.filter_layout = QHBoxLayout(self.filter_container)
        self.filter_layout.setContentsMargins(5, 5, 5, 5)
        self.filter_layout.setSpacing(5)
        self.filter_scroll.setWidget(self.filter_container)
        main_layout.addWidget(self.filter_scroll)
        self.updateFilterOptions()

         # ─── Autoriser le glisser-déposer de fichiers ───
        self.setAcceptDrops(True)

        # ─── Zone scrollable des SampleCard ───
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(10)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)

        # Indicateur de chargement
        self.loading_label = QLabel("Chargement...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.hide()
        self.content_layout.addWidget(self.loading_label)

        # Scroll listener pour chargement progressif
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.onScrollValueChanged)

    @pyqtSlot(list)
    def onSamplesChanged(self, samples: list):
        """
        Slot appelé quand SampleService met à jour son cache.
        » Met à jour la liste interne et reconstruit les cartes.
        """
        self.updateFilterOptions()
        if self._ignore_next_refresh:
            # L'ajout/suppression/renommage d'un sample déclenche également
            # samplesChanged. Dans ces cas, la vue est déjà à jour via les
            # slots dédiés, on se contente donc d'ignorer ce rafraîchissement
            # global pour éviter de recharger toute la liste.
            self._ignore_next_refresh = False
            return

        self.refresh_samples()

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
            None,
        )
        if new_sample is None:
            return

        if not self._path_matches_filter(new_sample.path):
            return

        # 2) l'ajoute en début de liste interne
        self.samples.insert(0, new_sample)

        # 3) crée la carte et connecte uniquement ses signaux
        card = SampleCard(new_sample, self.app_context)
        card.deleteSample.connect(self.delete_sample)
        card.removeFromHistory.connect(self.remove_from_history)
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
        self.current_offset += 1
        self.updateSelectActions()

    @pyqtSlot(int)
    def delete_sample(self, sample_id: int):
        """Déclenche la suppression via le service."""
        self._ignore_next_refresh = True
        self.sample_store.delete(sample_id)

    @pyqtSlot(int, str)
    def rename_sample(self, sample_id: int, new_name: str):
        """Déclenche le renommage via le service."""
        self._ignore_next_refresh = True
        self.sample_store.rename(sample_id, new_name)

    @pyqtSlot(int, str)
    def move_sample(self, sample_id: int, target_folder: str):
        """Déclenche le déplacement via le service."""
        self._ignore_next_refresh = True
        self.sample_store.move(sample_id, target_folder)

    @pyqtSlot(int)
    def remove_from_history(self, sample_id: int):
        """Déclenche la suppression de l'historique via le service."""
        self._ignore_next_refresh = True
        self.sample_store.removeFromHistory(sample_id)

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
        logger.info("onSelectionChanged:", sample_id, checked)
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
            try:
                self._ignore_next_refresh = True
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
            if self.current_offset > 0:
                self.current_offset -= 1
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
            self._ignore_next_refresh = True
            self.sample_store.removeFromHistory(sample_id)

        # on vide la sélection et on désactive les actions
        self.selected_ids.clear()
        self.bulk_delete_act.setEnabled(False)
        self.bulk_move_act.setEnabled(False)
        self.bulk_normalize_act.setEnabled(False)
        self.bulk_archive_act.setEnabled(False)
        self.updateSelectActions()

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
                card.removeFromHistory.connect(self.remove_from_history)
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
            if self.current_offset > 0:
                self.current_offset -= 1
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

            self._ignore_next_refresh = True
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
            self._ignore_next_refresh = True
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
            self._ignore_next_refresh = True
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

    # ------------------------------------------------------------------ Filtrage
    def updateFilterOptions(self, _=None):
        """Reconstruit les cartes de filtres en fonction des dossiers."""
        dirs = sorted(self.sample_store.get_sample_directories())

        if not self.active_dirs:
            self.active_dirs = set(dirs)
        else:
            self.active_dirs &= set(dirs)
            self.active_dirs |= set(dirs) - self.active_dirs

        for card in list(self._filter_cards.values()):
            self.filter_layout.removeWidget(card)
            card.deleteLater()
        self._filter_cards.clear()

        for d in dirs:
            card = DirectoryFilterCard(d, d in self.active_dirs)
            card.toggled.connect(self.onDirectoryToggled)
            self.filter_layout.addWidget(card)
            self._filter_cards[d] = card


    @pyqtSlot(str, bool)
    def onDirectoryToggled(self, path: str, is_active: bool):
        if is_active:
            self.active_dirs.add(path)
        else:
            self.active_dirs.discard(path)
        self.refresh_samples()

    def refresh_samples(self):
        # Réinitialise l'affichage et charge la première page
        self.samples = []
        self.current_offset = 0
        self.more_available = True
        self.is_loading = False

        for card in list(self._card_widgets.values()):
            self.content_layout.removeWidget(card)
            card.deleteLater()
        self._card_widgets.clear()

        self.loading_label.show()
        self.load_next_page()
        self.updateSelectActions()

    def _path_matches_filter(self, path: str) -> bool:
        if not self.active_dirs:
            return True
        ap = os.path.abspath(path)
        return any(ap.startswith(os.path.abspath(d)) for d in self.active_dirs)

    # ---------------------- Chargement progressif ----------------------
    def onScrollValueChanged(self, value: int):
        bar = self.scroll_area.verticalScrollBar()
        if (not self.is_loading and self.more_available and value >= bar.maximum() - 200):
            self.load_next_page()

    def load_next_page(self):
        if self.is_loading or not self.more_available:
            return
        self.is_loading = True
        self.loading_label.show()
        self._loader_thread = SamplesPageLoader(
            self.sample_store,
            self.current_offset,
            self.page_size,
            list(self.active_dirs),
        )
        self._loader_thread.samplesReady.connect(self.onSamplesLoaded)
        self._loader_thread.start()

    @pyqtSlot(list)
    def onSamplesLoaded(self, samples: list):
        self.loading_label.hide()
        self.is_loading = False
        self._loader_thread = None
        if not samples:
            self.more_available = False
            return

        for samp in samples:
            self.samples.append(samp)
            card = SampleCard(samp, self.app_context)
            card.deleteSample.connect(self.delete_sample)
            card.removeFromHistory.connect(self.remove_from_history)
            card.renameSample.connect(self.rename_sample)
            card.sampleMoved.connect(self.move_sample)
            card.normalizeClicked.connect(self.onNormalizeClicked)
            card.selectionChanged.connect(self.onSelectionChanged)
            self.sample_store.sampleRenamed.connect(card.onRenameSuccess)
            self.sample_store.sampleMoved.connect(card.onMoveSuccess)

            self._card_widgets[samp.id] = card
            # Insérer avant l'indicateur de chargement
            idx = self.content_layout.indexOf(self.loading_label)
            self.content_layout.insertWidget(idx, card)

        self.current_offset += len(samples)
        if len(samples) < self.page_size:
            self.more_available = False
        self.updateSelectActions()


class SamplesPageLoader(QThread):
    """Thread pour charger une page de samples sans bloquer l'UI."""

    samplesReady = pyqtSignal(list)

    def __init__(self, service: SampleService, offset: int, limit: int, dirs: list[str]):
        super().__init__()
        self.service = service
        self.offset = offset
        self.limit = limit
        self.dirs = dirs

    def run(self):
        results = self.service.get_samples(self.offset, self.limit, self.dirs)
        self.samplesReady.emit(results)

