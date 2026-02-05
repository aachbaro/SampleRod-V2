# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal d'edition/lecture de waveform pour un sample.
# - Sert de "mini DAW" pour couper, marquer, lire et exporter des segments.
# - Fait l'orchestration: instancie les controllers UI/lecture/edition.
#
# CE QUI EST EN PLACE
# - Chargement async de la waveform + rendu du read head.
# - Selection par region + gestion des markers.
# - Curseur de depart (ligne bleue) distinct des markers.
# - Playback (loop, pause, stop, play from start).
# - Drag & drop de segments.
# - Historique undo/redo.
#
# ARCHITECTURE DES CONTROLLERS
# - Playback: waveform_playback.py
# - Interactions: waveform_interactions.py
# - Region/selection: waveform_region.py
# - Markers: waveform_markers.py
# - Rendu: waveform_renderer.py
# - UI builder: waveform_ui.py
# - History: waveform_history.py
# - Save/export: waveform_save.py
# - Shortcuts: waveform_shortcuts.py
# - Navigation/zoom: waveform_navigation.py
# - Helpers plot: waveform_plot_helpers.py
#
# GESTES / INTERACTIONS IMPORTANTES
# - Clic gauche: creer/ajuster une region.
# - Maj + glisse: deplacer la region.
# - Ctrl + double-clic: creer region rapide.
# - Mode marker: clic gauche -> poser un marker.
# - Clic molette: placer la tete + jouer depuis ce point.
# - Raccourcis: play/pause/stop, undo/redo, export, etc.
#
# CE QUI RESTE A FAIRE (IDEES)
# - Refonte UI (barre d'outils, densite, meilleure hierarchie).
# - Gestes coherents avec le reste de l'app.
# - Edition non destructive / versions.
# - Metriques (RMS, peak, LUFS) et overlays.
# -----------------------------------------------------------------------------
# frontend/sample_gui/wave_form.py

import os
import pickle

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QDrag
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
import pyqtgraph as pg
import qtawesome as qta

from backend.models.AppContext import AppContext

from .marker_manager import MarkerManager
from .waveform.waveform_loader import WaveformLoaderThread
from .waveform.history_stack import HistoryStack
from .waveform.waveform_interactions import WaveformInteractionsController
from .waveform.waveform_playback import WaveformPlaybackController
from .waveform.waveform_region import WaveformRegionController
from .waveform.waveform_markers import WaveformMarkersController
from .waveform.waveform_renderer import WaveformRenderer
from .waveform.waveform_ui import WaveformUIBuilder
from .waveform.waveform_history import WaveformHistoryController
from .waveform.waveform_save import WaveformSaveController
from .waveform.waveform_shortcuts import WaveformShortcutsController
from .waveform.waveform_navigation import WaveformNavigationController
from .waveform.waveform_plot_helpers import ContextMenuLinearRegionItem, NoLeftDragViewBox

class WaveformWidget(QWidget):
    stop_timer_signal = pyqtSignal()
    waveformSaved    = pyqtSignal(str)
    positionUpdated = pyqtSignal(float)

# -- Construction & état (core)
# ———————————————————————————————————————————————————— Initialisation ————————————————————————————————————————————————————

    def __init__(self, audio_file_path, app_context: AppContext):
        super().__init__()

        self.app_context = app_context
        self.audio_file_path = audio_file_path
        # → playback
        self.stream = None
        self.current_time = 0.0
        self.is_playing = False
        self.loop_enabled = False


        # → sélection de région (clic‐drag)
        self.play_start = 0.0
        self.play_end   = 0.0 
        self.region = None
        # curseur visuel de depart (ligne bleue) distinct des "markers"
        self.play_start_cursor = None
        self._dragging = False
        self._creating = False
        self._press_x  = 0.0
        self._shifting = False            # mode “déplacement” activé
        self._shift_press_x = 0.0         # position d’appui en secondes
        self._orig_region = (0.0, 0.0)    # bornes initiales de la région

        # → marqueurs (clic en mode marker)
        self.marker_mode = False

        # → données
        self.waveform_data = None
        self.sample_rate = None
        self.duration = 0.0
        self.is_stereo = False

        # historique des actions
        self.history = HistoryStack()
        self._record_history = True

        # renderer instancié tôt (les callbacks peuvent se déclencher pendant l'UI build)
        self.renderer = WaveformRenderer(self)
        # UI builder dédié
        self.ui_builder = WaveformUIBuilder(self, NoLeftDragViewBox)
        # historique (undo/redo)
        self.history_controller = WaveformHistoryController(self)
        # save / export
        self.save_controller = WaveformSaveController(self)
        # shortcuts
        self.shortcuts_controller = WaveformShortcutsController(self)
        # navigation / zoom
        self.navigation_controller = WaveformNavigationController(self)
        # construction de l'UI (définit notamment self.plot)
        self._build_ui()
        self.region_controller = WaveformRegionController(self, ContextMenuLinearRegionItem)
        self.playback = WaveformPlaybackController(self)
        self.interactions = WaveformInteractionsController(self, ContextMenuLinearRegionItem)
        # gestion des marqueurs via un composant dédié, APRES avoir défini self.plot
        self.marker_manager = MarkerManager(self)
        self.marker_controller = WaveformMarkersController(self, ContextMenuLinearRegionItem)
        # UI: la liste de markers est une colonne a droite du plot, toujours presente.
        # S'il n'y a pas de markers, elle est simplement vide.
        self._load_audio(audio_file_path)
        self.positionUpdated.connect(lambda t: self.read_head.setPos(t))

    # -- Proxies MarkerManager (marker_manager.py)
    @property
    def markers(self):
        return self.marker_manager.markers

    @markers.setter
    def markers(self, value):
        self.marker_manager.markers = value

    @property
    def marker_lines(self):
        return self.marker_manager.marker_lines

    @marker_lines.setter
    def marker_lines(self, value):
        self.marker_manager.marker_lines = value

    @property
    def current_marker_idx(self):
        return self.marker_manager.current_marker_idx

    @current_marker_idx.setter
    def current_marker_idx(self, value):
        self.marker_manager.current_marker_idx = value

    # -- UI (waveform_ui.py)
    def _build_ui(self):
        self.ui_builder.build()

    # -- Loader (waveform_loader.py)
    def _load_audio(self, path):
        self.loader = WaveformLoaderThread(path)
        self.loader.waveformReady.connect(self.set_waveform_data)
        self.loader.start()

    # -- Données + limites (waveform_navigation.py)
    def set_waveform_data(self, y, sr, dur):
        # y.shape == (n_samples,) en mono ou (n_channels, n_samples) en stéréo
        if y.ndim == 2:
            # Transposer pour obtenir (n_samples, 2)
            y = y.T
            self.is_stereo = True
        else:
            self.is_stereo = False

        self.waveform_data = y.astype('float32', order='C')
        self.sample_rate   = sr
        self.duration      = dur

    # **Verrouille désormais les limites X/Y du ViewBox** sur la durée réelle
        self.navigation_controller.configure_viewbox()

        # calcul initial de l'enveloppe sur toute la durée
        self.plot.setXRange(0, self.duration, padding=0)
        self._draw_waveform()

    # -- Rendu (waveform_renderer.py)
    def _draw_waveform(self):
        self.renderer.draw_waveform()

    def _on_view_range_changed(self, view_box, range):
        self.renderer.on_view_range_changed(view_box, range)

    def _redraw_all(self):
        self.renderer.redraw_all()

    # -- Navigation / zoom (waveform_navigation.py)

    def _zoom_or_pan(self, ev, **_):
        self.navigation_controller.zoom_or_pan(ev, **_)

    # -- Markers (waveform_markers.py)

    def add_marker(self, t: float):
        self.marker_controller.add_marker(t)

    def toggle_marker_mode(self, checked: bool):
        self.marker_controller.toggle_marker_mode(checked)

    def on_marker_moved(self, line: pg.InfiniteLine):
        self.marker_controller.on_marker_moved(line)

    def _on_marker_move_finished(self, line):
        self.marker_controller._on_marker_move_finished(line)

    def remove_marker(self, t: float):
        self.marker_controller.remove_marker(t)

    def on_marker_list_clicked(self, item):
        self.marker_controller.on_marker_list_clicked(item)

    def on_marker_list_double_clicked(self, item):
        self.marker_controller.on_marker_list_double_clicked(item)

    def _refresh_marker_list(self):
        self.marker_controller._refresh_marker_list()

    # -- Interactions (waveform_interactions.py)

    def eventFilter(self, source, event):
        return self.interactions.eventFilter(source, event)

    # -- Region / selection (waveform_region.py)

    def _set_play_start_cursor(self, x):
        self.region_controller._set_play_start_cursor(x)

    def on_region_changed(self):
        self.region_controller.on_region_changed()

    def _handle_ctrl_double_click(self, view_box, event):
        self.region_controller._handle_ctrl_double_click(view_box, event)


    def _cut_region(self, start, end):
        self.region_controller._cut_region(start, end)

    def _do_cut(self, start, end):
        return self.region_controller._do_cut(start, end)

    def _undo_cut(self, cmd):
        self.region_controller._undo_cut(cmd)

    def _create_marker_line(self, t):
        self.marker_controller._create_marker_line(t)

    def _export_region(self, start, end):
        self.region_controller._export_region(start, end)

    # -- Drag & drop (local)
    def start_slice_drag(self, start: float, end: float):
        """Initie un glisser-déposer pour la portion [start,end]."""
        s0 = int(start * self.sample_rate)
        s1 = int(end * self.sample_rate)
        if s1 <= s0:
            return
        array = self.waveform_data[s0:s1].astype("float32")
        name = os.path.basename(self.audio_file_path)
        mime = QMimeData()
        payload = {
            "audio_data": array,
            "sample_rate": self.sample_rate,
            "name": name,
        }
        mime.setData(
            "application/x-sample-slice-data",
            pickle.dumps(payload),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    # -- Playback (waveform_playback.py)
    def play_from_start(self):
        self.playback.play_from_start()

    def pause_or_resume(self):
        self.playback.pause_or_resume()

    def play_audio(self, start_time: float = 0.0):
        self.playback.play_audio(start_time)

    def pause_audio(self):
        self.playback.pause_audio()

    def stop_and_reset(self):
        self.playback.stop_and_reset()

    def stop_audio(self):
        self.playback.stop_audio()

    def update_read_head(self):
        self.playback.update_read_head()

    def toggle_loop(self, checked: bool):
        self.playback.toggle_loop(checked)

    # -- History (waveform_history.py)
    def _push_history(self, cmd: dict):
        self.history_controller.push_history(cmd)

    def undo(self):
        self.history_controller.undo()

    def redo(self):
        self.history_controller.redo()

    def _debug_history(self):
        self.history_controller._debug_history()

    # -- Save / export (waveform_save.py)

    def onSaveClicked(self):
        self.save_controller.on_save_clicked()

    # -- Shortcuts (waveform_shortcuts.py)

    def _on_cut_shortcut(self):
        self.shortcuts_controller.on_cut_shortcut()

    def _on_export_shortcut(self):
        self.shortcuts_controller.on_export_shortcut()

    def add_markers_to_region(self):
        self.shortcuts_controller.add_markers_to_region()


