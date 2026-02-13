"""
SampleList
==========
Widget principal qui affiche la liste des samples avec toolbar, pagination
et actions bulk. Le fichier sert de facade et delegue aux sous-modules.

Sous-modules utilises
---------------------
- SampleListUIBuilder     : creation UI (toolbar / scroll / pagination).
- SampleListPagination    : logique de pagination + navigation.
- SampleListSelection     : selection + actions bulk.
- SampleListDragDrop      : import par glisser-deposer.
- SampleListImport        : import manuel via QFileDialog.
- SampleListNormalize     : normalisation + workers.
- SampleListServiceActions: delete/rename/move via SampleService.
- SampleListCards         : gestion du cycle de vie des SampleCard.
"""

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import pyqtSlot, QSettings

from backend.models.AppContext import AppContext
from backend.services.sample_service import SampleService
from frontend.sample_gui.sample.sample_list_ui import SampleListUIBuilder
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination
from frontend.sample_gui.sample.sample_list_selection import SampleListSelection
from frontend.sample_gui.sample.sample_list_dragdrop import SampleListDragDrop
from frontend.sample_gui.sample.sample_list_import import SampleListImport
from frontend.sample_gui.sample.sample_list_normalize import SampleListNormalize
from frontend.sample_gui.sample.sample_list_service import SampleListServiceActions
from frontend.sample_gui.sample.sample_list_cards import SampleListCards


class SampleListWidget(QWidget):
    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # stocke le contexte et le service metier
        self.app_context  = app_context
        self.sample_store: SampleService = app_context.sample_store
        self.settings = self.app_context.settings
        self.samples = []  # liste des samples a afficher
        self.selected_ids  = set()        # ensemble des IDs coches
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
        self.sample_store.sampleConcatCandidateChanged.connect(
            self.onSampleConcatCandidateChanged
        )
        self.sample_store.sampleNormalizationLockChanged.connect(
            self.onSampleNormalizationLockChanged
        )
        # 2) stockage des cartes existantes
        self._card_widgets = {}
        self.pagination = SampleListPagination(self)
        self.selection = SampleListSelection(self)
        self.dragdrop = SampleListDragDrop(self)
        self.cards = SampleListCards(self)
        self.importer = SampleListImport(self)
        self.normalizer = SampleListNormalize(self)
        self.service_actions = SampleListServiceActions(self)

        # mise a jour en cas de changement de parametres
        self.settings.samplesPerPageChanged.connect(self.onSamplesPerPageChanged)

        # 3) creation de l'UI
        self.init_ui()

        # 4) initialisation de la liste avec le cache actuel
        self.onSamplesChanged(self.sample_store.get_cached())

    def init_ui(self):
        """Construit l'UI (toolbar, scroll, pagination)."""
        self.ui_builder = SampleListUIBuilder(self)
        self.ui_builder.build()

    # ---- Service slots (cache / cards)
    @pyqtSlot(list)
    def onSamplesChanged(self, samples: list):
        self.cards.on_samples_changed(samples)

    @pyqtSlot(int)
    def onSampleAdded(self, sample_id: int):
        self.cards.on_sample_added(sample_id)

    # ---- Service actions (delete / rename / move)
    @pyqtSlot(int)
    def delete_sample(self, sample_id: int):
        self.service_actions.delete_sample(sample_id)

    @pyqtSlot(int, str)
    def rename_sample(self, sample_id: int, new_name: str):
        self.service_actions.rename_sample(sample_id, new_name)

    @pyqtSlot(int, str)
    def move_sample(self, sample_id: int, target_folder: str):
        self.service_actions.move_sample(sample_id, target_folder)

    # ---- Normalisation
    @pyqtSlot(int)
    def onStartedNormalization(self, sample_id: int):
        self.normalizer.on_started(sample_id)

    @pyqtSlot(int)
    def onFinishedNormalization(self, sample_id: int):
        self.normalizer.on_finished(sample_id)

    @pyqtSlot(int)
    def onNormalizeClicked(self, sample_id: int):
        self.normalizer.on_clicked(sample_id)

    @pyqtSlot(int, str)
    def onNormalizationFailed(self, sample_id: int, message: str):
        self.normalizer.on_failed(sample_id, message)

    # ---- Selection / bulk
    @pyqtSlot(int, bool)
    def onSelectionChanged(self, sample_id: int, checked: bool):
        self.selection.on_selection_changed(sample_id, checked)

    # ---- Import manuel
    @pyqtSlot()
    def onAddFiles(self):
        self.importer.add_files()

    # ---- Cards (retours service)
    @pyqtSlot(int)
    def onSampleRemovedFromHistory(self, sample_id: int):
        self.cards.on_sample_removed_from_history(sample_id)

    @pyqtSlot()
    def bulkRemoveFromHistory(self):
        self.selection.bulk_remove_from_history()

    def refreshList(self):
        self.cards.refresh_list()

    @pyqtSlot(int)
    def onSampleDeleted(self, sample_id: int):
        self.cards.on_sample_deleted(sample_id)

    @pyqtSlot(int, str, str)
    def onSampleRenamed(self, sample_id: int, old_path: str, new_path: str):
        self.cards.on_sample_renamed(sample_id, old_path, new_path)

    @pyqtSlot(int, str)
    def onSampleMoved(self, sample_id: int, target_folder: str):
        self.cards.on_sample_moved(sample_id, target_folder)

    @pyqtSlot(int, float)
    def onSampleDurationChanged(self, sample_id: int, new_duration: float):
        self.cards.on_sample_duration_changed(sample_id, new_duration)

    @pyqtSlot(int, bool, object)
    def onSampleConcatCandidateChanged(self, sample_id: int, enabled: bool, prev_id):
        self.cards.on_sample_concat_candidate_changed(sample_id, enabled, prev_id)

    @pyqtSlot(int, bool)
    def onSampleNormalizationLockChanged(self, sample_id: int, locked: bool):
        self.cards.on_sample_normalization_lock_changed(sample_id, locked)

    @pyqtSlot(int)
    def concat_with_previous(self, sample_id: int):
        self.service_actions.concat_with_previous(sample_id)

    @pyqtSlot(int)
    def dismiss_concat(self, sample_id: int):
        self.service_actions.dismiss_concat(sample_id)

    @pyqtSlot(int, bool, object)
    def onConcatPreviewHoverChanged(self, sample_id: int, active: bool, prev_id):
        self.cards.on_concat_preview_hover_changed(sample_id, active, prev_id)

    def bulkDelete(self):
        self.selection.bulk_delete()

    def bulkMove(self):
        self.selection.bulk_move()

    def bulkNormalize(self):
        self.selection.bulk_normalize()

    def close_waveforms_for_path(self, path):
        self.cards.close_waveforms_for_path(path)

    def updateSelectActions(self):
        self.selection.update_select_actions()

    @pyqtSlot()
    def onSelectAll(self):
        self.selection.select_all()

    @pyqtSlot()
    def onDeselectAll(self):
        self.selection.deselect_all()

    # ---- Drag & drop
    def dragEnterEvent(self, event):
        self.dragdrop.drag_enter(event)

    def dragMoveEvent(self, event):
        self.dragdrop.drag_move(event)

    def dropEvent(self, event):
        self.dragdrop.drop(event)

    # ---- Pagination
    def updatePaginationLabel(self, start_idx: int, end_idx: int, total_samples: int):
        """Met a jour le label de pagination."""
        self.pagination.update_label(start_idx, end_idx, total_samples)

    @pyqtSlot(int)
    def onSamplesPerPageChanged(self, count: int):
        """Slot appele lorsque le parametre de pagination change."""
        self.pagination.on_samples_per_page_changed(count)

    def setCurrentPage(self, page: int):
        """Change la page actuelle et rafraichit la liste."""
        self.pagination.set_current_page(page)

    def change_page(self, page: int):
        """Gere le changement de page et arrete la lecture si necessaire."""
        self.pagination.change_page(page)

    def _prev_page(self):
        self.pagination.prev_page()

    def _next_page(self):
        self.pagination.next_page()

