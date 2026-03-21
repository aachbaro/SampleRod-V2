"""
SampleCard
==========
Composant UI qui represente un sample dans la liste. Le fichier sert de
"facade" legere et delegue la logique a des controleurs specialises.

Role dans l'architecture
------------------------
- Affiche une carte de sample (metadonnees, actions, playback, waveform).
- Centralise les signaux Qt consommes par SampleList/SampleService.
- Delegue la logique aux sous-modules pour garder le fichier simple.

Controleurs utilises
--------------------
- SampleCardUIBuilder     : construction des widgets + styles.
- SampleCardHeaderActions : rename / delete / archive / normalize.
- SampleCardPlayback      : play/pause + slider + temps.
- SampleCardWaveform      : bascule et cycle de vie du waveform editor.
- SampleCardMove          : deplacement vers une librairie/dossier.
- SampleCardInteractions  : focus + drag & drop.
- SampleCardSelection     : checkbox + etat visuel.
- SampleCardStatus        : updates simples (nom/duree).
"""

from PySide6.QtCore import Signal, Qt, QEvent
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QAbstractButton, QLineEdit, QComboBox, QSlider
import logging
import os

from backend.models.sample import Sample
from backend.models.AppContext import AppContext
from frontend.sample_gui.sample.sample_card_actions import SampleCardHeaderActions
from frontend.sample_gui.sample.sample_card_interactions import SampleCardInteractions
from frontend.sample_gui.sample.sample_card_move import SampleCardMove
from frontend.sample_gui.sample.sample_card_playback import SampleCardPlayback
from frontend.sample_gui.sample.sample_card_selection import SampleCardSelection
from frontend.sample_gui.sample.sample_card_status import SampleCardStatus
from frontend.sample_gui.sample.sample_card_ui import SampleCardUIBuilder
from frontend.sample_gui.sample.sample_card_waveform import SampleCardWaveform

logger = logging.getLogger("sample_card")

class SampleCard(QWidget):
    """Carte UI d'un sample, avec sous-controleurs pour chaque domaine."""

    # ---- Signaux
    deleteSample       = Signal(int)          # emet l'ID du sample a supprimer
    renameSample       = Signal(int, str)     # emet (ID, nouveau nom)
    playSample         = Signal(object)       # emet l'objet Sample a jouer
    sampleMoved        = Signal(int, str)     # emet (ID, nouveau dossier)
    newSampleSaved     = Signal(str)          # emet le path quand on sauvegarde
    normalizeClicked   = Signal(int)          # emet l'ID pour normaliser manuellement
    selectionChanged   = Signal(int, bool)    # nouveau signal : emet (ID du sample, etat coche)
    removeFromHistory  = Signal(int)          # emet l'ID du sample a retirer de l'historique
    concatWithPrevious = Signal(int)          # emet l'ID (sample courant) a concatener avec precedent
    dismissConcat      = Signal(int)          # emet l'ID (sample courant) pour ignorer la concat
    concatPreviewHoverChanged = Signal(
        int, bool, object
    )  # (sample_id, hover_active, prev_id|None)

    def __init__(self, sample: Sample, app_context: AppContext, parent=None):
        """
        sample : objet Sample, avec au moins les attributs :
            - id, name (ou filename), created_at, duration.
        """
        super().__init__(parent)

        # ---- Data
        self.app_context = app_context
        self.settings = self.app_context.settings
        self.sample = sample
        self.isRenaming = False
        self.showWaveform = False
        self.wave_edition_widget = None

        self.isChecked = False
        self.concat_prev_id = None

        # self.app_context.audio_player.signals.positionChanged.connect(self.updateSlider)
        self.settings.librariesChanged.connect(self.updateLibraryCombo)

        # ---- UI + Controllers
        self.init_ui()
        self.playback = SampleCardPlayback(self)
        self.playback.bind()
        self.playback.update_slider()
        self.header_actions = SampleCardHeaderActions(self)
        self.waveform = SampleCardWaveform(self)
        self.mover = SampleCardMove(self)
        self.interactions = SampleCardInteractions(self)
        self.selection = SampleCardSelection(self)
        self.status = SampleCardStatus(self)
        self._build_shortcuts()

    def init_ui(self):
        """Construit l'UI (widgets + layout) via SampleCardUIBuilder."""
        self.ui_builder = SampleCardUIBuilder(self)
        self.ui_builder.build()

    def _build_shortcuts(self):
        """Raccourcis actifs seulement quand la carte (ou un enfant) a le focus."""
        for seq, handler in [
            ("Ctrl+R", lambda: self.startRename()),
            ("Ctrl+X", lambda: self._with_wave(lambda w: w._on_cut_shortcut())),
            ("Ctrl+Z", lambda: self._with_wave(lambda w: w.undo())),
            ("Ctrl+Shift+Z", lambda: self._with_wave(lambda w: w.redo())),
            ("Ctrl+S", lambda: self._with_wave(lambda w: w.onSaveClicked())),
            ("Ctrl+L", lambda: self._with_wave(lambda w: w.loop_button.toggle())),
            ("Ctrl+G", lambda: self._with_wave(lambda w: w.toggle_marker_mode(not w.marker_mode))),
            ("Space", lambda: self._with_wave(lambda w: w.pause_or_resume())),
            ("Ctrl+Space", lambda: self._with_wave(lambda w: w.play_from_start())),
            ("Ctrl+E", lambda: self._with_wave(lambda w: w._on_export_shortcut())),
            ("Ctrl+Shift+G", lambda: self._with_wave(lambda w: w.add_markers_to_region())),
            # ajoute ici d'autres raccourcis si besoin...
        ]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def _with_wave(self, fn):
        """Helper : si le waveform est ouvert, appelle fn(wave_edition_widget)."""
        if hasattr(self, "wave_edition_widget") and self.wave_edition_widget:
            fn(self.wave_edition_widget)

    # ---- Interactions (focus / drag)
    def mousePressEvent(self, event):
        self.interactions.mouse_press(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.interactions.mouse_move(event):
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Double-clic uniquement si la cible n'est pas interactive
        # (boutons, slider, selecteurs, inputs).
        child = self.childAt(event.position().toPoint())
        excluded_types = (QAbstractButton, QLineEdit, QComboBox, QSlider)

        # Ne jamais toggler la waveform si le double-clic vient du waveform editor lui-meme,
        # sinon on ferme l'editor pendant des interactions internes.
        if self.showWaveform and child is not None:
            wc = getattr(self, "waveform_container", None)
            if wc is not None and (child is wc or wc.isAncestorOf(child)):
                super().mouseDoubleClickEvent(event)
                return

        # Remonte la hierarchy pour detecter si on est dans un widget interactif.
        w = child
        while w is not None and w is not self:
            if isinstance(w, excluded_types):
                super().mouseDoubleClickEvent(event)
                return
            w = w.parent()

        self.toggleWaveform()
        event.accept()

    def keyPressEvent(self, event):
        # Echappement pour annuler un renommage en cours
        if self.isRenaming and event.key() == Qt.Key.Key_Escape:
            self.cancelRename()
            return

    # ---- Utils
    def get_sample_name(self):
        """Retourne le nom du sample a partir du chemin."""
        return os.path.basename(self.sample.name)
    
    @staticmethod
    def get_folder_name(path):
        """Retourne le nom du dernier dossier dans le chemin."""
        return os.path.basename(os.path.dirname(path))

    # ---- Header actions
    def name_label_double_click(self, event):
        self.startRename()

    def startRename(self):
        self.header_actions.start_rename()

    def cancelRename(self):
        self.header_actions.cancel_rename()

    def submitRename(self):
        self.header_actions.submit_rename()

    def toggleWaveform(self):
        self.waveform.toggle()

    def confirmDelete(self):
        self.header_actions.confirm_delete()

    def onArchiveClicked(self):
        self.header_actions.archive()

    def onConcatWithPreviousClicked(self):
        self.concatWithPrevious.emit(self.sample.id)

    def onDismissConcatClicked(self):
        self.dismissConcat.emit(self.sample.id)

    def setConcatCandidate(self, enabled: bool, prev_sample_id=None):
        old_prev = self.concat_prev_id
        self.concat_prev_id = prev_sample_id if enabled else None
        self.concat_button.setVisible(enabled)
        self.concat_cancel_button.setVisible(enabled)
        if not enabled and old_prev is not None:
            self.concatPreviewHoverChanged.emit(self.sample.id, False, old_prev)
        if enabled and prev_sample_id is not None:
            self.concat_button.setToolTip(
                f"Concatener ce sample apres le sample #{prev_sample_id}"
            )
        else:
            self.concat_button.setToolTip("Concatener avec le sample precedent")

    def setNormalizationLocked(self, locked: bool):
        self.normalize_button.setEnabled(not locked)

    def setConcatPreviewActive(self, active: bool):
        self.setProperty("concatPreview", active)
        self.style().unpolish(self)
        self.style().polish(self)

    # ---- Playback
    def togglePlay(self):
        self.playback.toggle_play()

    def seekAudio(self, value):
        self.playback.seek_audio(value)

    def updateSlider(self):
        self.playback.update_slider()

    def onRenameSuccess(self, sample_id, old_path, new_path):
        self.header_actions.on_rename_success(sample_id, old_path, new_path)

    def onRenameError(self, sample_id, error_msg):
        self.header_actions.on_rename_error(sample_id, error_msg)

    # ---- Status / metadata
    def refresh_display(self):
        self.status.refresh_display()

    # ---- Move / combobox
    def move_sample(self, index: int):
        self.mover.move_sample(index)

    def onMoveSuccess(self, sample_id, new_dir):
        self.mover.on_move_success(sample_id, new_dir)

    def onDurationChanged(self, sample_id, new_duration):
        self.status.on_duration_changed(sample_id, new_duration)

    # ---- Focus hooks
    def focusInEvent(self, event):
        self.interactions.focus_in(event)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.interactions.focus_out(event)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "concat_button", None):
            if event.type() == QEvent.Type.Enter and self.concat_prev_id is not None:
                self.concatPreviewHoverChanged.emit(
                    self.sample.id, True, self.concat_prev_id
                )
            elif event.type() == QEvent.Type.Leave and self.concat_prev_id is not None:
                self.concatPreviewHoverChanged.emit(
                    self.sample.id, False, self.concat_prev_id
                )
        if self.interactions.event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    # ---- Normalize
    def onNormalizeButtonClicked(self):
        self.header_actions.normalize_clicked()

    def indicateNormalizationStarted(self):
        self.header_actions.indicate_normalization_started()

    def indicateNormalizationFinished(self):
        self.header_actions.indicate_normalization_finished()

    def indicateNormalizationError(self, message: str):
        self.header_actions.indicate_normalization_error(message)

    # ---- Selection
    def onCheckboxToggled(self, checked: bool):
        self.selection.on_checkbox_toggled(checked)

    # ---- Libraries
    def updateLibraryCombo(self, libs: list):
        self.mover.update_library_combo(libs)

