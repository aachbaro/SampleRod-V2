# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Facade du BreakWidget, suivant le pattern facade + controleurs.
# - Garde les signaux Qt et l'orchestration generale, tout en deleguant la
#   logique specialisee a des controleurs plus petits.
#
# LIENS CLES
# - break_ui.py          : build UI + styles + etat des actions.
# - break_loader.py      : chargement de waveform.
# - break_analysis.py    : analyse des hits.
# - break_hits_table.py  : tableau des slices.
# - break_quantize.py    : preview tempo + artefacts.
# - break_dnd.py         : drop entrant.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from frontend.styles import theme

from .break_analysis import BreakAnalysisController
from .break_dnd import BreakDndController
from .break_hits_table import BreakHitsTableController
from .break_loader import BreakLoaderController
from .break_markers import BreakMarkersController
from .break_playback import BreakPlaybackController
from .break_quantize import BreakQuantizeController
from .break_ui import BreakUIBuilder
from .hit_row import _HitRow


class BreakWidget(QWidget):
    """Standalone break analysis tab: drop -> decoupage -> analyse -> hits + quantize."""

    artifactCreated = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._break_service = app_context.drum_analysis
        self._current_path: str | None = None
        self._drop_replace_enabled = True
        self._pending_restored_markers: list[float] | None = None
        self._waveform_widget = None
        self._drop_active = False
        self._analysis_result = None
        self._hit_rows: list[_HitRow] = []
        self._selected_hit_index: int | None = None
        self._quantized_slices = ()
        self._quantize_request_mode: str | None = None
        self._quantized_preview_signature: tuple[object, ...] | None = None
        self._quantized_preview_path = ""
        self._quantized_preview_duration_s = 0.0
        self._tp_active_play_path: str = ""
        self._pending_cached_result = None
        self._internal_drag_active = False

        self.ui = BreakUIBuilder(self)
        self.loader = BreakLoaderController(self)
        self.analysis = BreakAnalysisController(self)
        self.markers = BreakMarkersController(self)
        self.hits_table = BreakHitsTableController(self)
        self.quantize = BreakQuantizeController(self)
        self.playback = BreakPlaybackController(self)
        self.dnd = BreakDndController(self)

        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.ui._build_ui()

    def _bind_signals(self) -> None:
        svc = self._break_service
        svc.analysisStarted.connect(self._on_analysis_started)
        svc.analysisFinished.connect(self._on_analysis_finished)
        svc.analysisFailed.connect(self._on_analysis_failed)
        svc.quantizeStarted.connect(self._on_quantize_started)
        svc.quantizeFinished.connect(self._on_quantize_finished)
        svc.quantizeFailed.connect(self._on_quantize_failed)
        self.generator_panel.artifactCreated.connect(self.artifactCreated.emit)
        self.generator_panel.statusChanged.connect(self.status_label.setText)
        self._play_btn.clicked.connect(
            lambda: self._waveform_widget and self._waveform_widget.play_from_start()
        )
        self._pause_btn.clicked.connect(
            lambda: self._waveform_widget and self._waveform_widget.pause_or_resume()
        )
        self._stop_btn.clicked.connect(
            lambda: self._waveform_widget and self._waveform_widget.stop_audio()
        )
        self._loop_btn.toggled.connect(
            lambda checked: self._waveform_widget and self._waveform_widget.toggle_loop(checked)
        )
        self._undo_btn.clicked.connect(
            lambda: self._waveform_widget and self._waveform_widget.undo()
        )
        self.split_button.clicked.connect(self._run_auto_split)
        self.analyze_button.clicked.connect(self._run_slice_analysis)
        self._fill_btn.clicked.connect(self._run_fill_markers)
        self._tp_play_btn.clicked.connect(self._preview_quantized_break)
        self._tp_stop_btn.clicked.connect(self._stop_tempo_preview)
        self._tp_mode_group.buttonClicked.connect(self._on_tp_mode_changed)

    def _on_tab_clicked(self, idx: int) -> None:
        self.ui._on_tab_clicked(idx)

    def _update_header_meta(self) -> None:
        self.ui._update_header_meta()

    def _update_slices_label(self) -> None:
        self.ui._update_slices_label()

    def _stop_tempo_preview(self) -> None:
        self.playback._stop_tempo_preview()

    def _on_tp_mode_changed(self, *_args) -> None:
        self.playback._stop_tempo_preview()

    def open_file(self, path: str) -> bool:
        return self.loader.open_file(path)

    def current_path(self) -> str | None:
        return self._current_path

    def set_drop_replace_enabled(self, enabled: bool) -> None:
        """Active/desactive le drop-remplacement interne du BreakWidget."""
        self._drop_replace_enabled = bool(enabled)
        self.setAcceptDrops(self._drop_replace_enabled)
        if hasattr(self, "waveform_host") and self.waveform_host is not None:
            self.waveform_host.setAcceptDrops(self._drop_replace_enabled)
        if self._waveform_widget is not None:
            self._waveform_widget.setAcceptDrops(self._drop_replace_enabled)

    def set_markers(self, markers: list[float]) -> None:
        """Restaure des marqueurs manuels sur le fichier courant."""
        normalized: list[float] = []
        seen: set[float] = set()
        for marker in markers or []:
            try:
                value = float(marker)
            except (TypeError, ValueError):
                continue
            if value < 0.0:
                continue
            key = round(value, 6)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(value)

        normalized.sort()
        self._pending_restored_markers = normalized
        self._apply_pending_markers()

    def _apply_pending_markers(self) -> None:
        if self._pending_restored_markers is None or not self._waveform_ready():
            return
        markers = list(self._pending_restored_markers)
        self._pending_restored_markers = None
        self.markers.set_markers(markers)
        self._clear_analysis()
        self.status_label.setText("Marqueurs restaures. Relance l'analyse pour reconstruire les slices.")
        self._refresh_actions()

    def cleanup(self) -> None:
        """Arrete les lectures en cours avant fermeture du widget."""
        try:
            self._stop_tempo_preview()
        except Exception:
            pass
        generator = getattr(self, "generator_panel", None)
        stopper = getattr(generator, "_stop_preview", None)
        if callable(stopper):
            try:
                stopper()
            except Exception:
                pass
        clear_cache = getattr(generator, "_clear_preview_cache", None)
        if callable(clear_cache):
            try:
                clear_cache(stop_if_playing=False)
            except Exception:
                pass
        waveform = self._waveform_widget
        if waveform is None:
            return
        try:
            waveform.stop_audio()
        except Exception:
            pass
        try:
            waveform.timer.stop()
        except Exception:
            pass

    def _replace_waveform(self, path: str) -> None:
        self.loader._replace_waveform(path)

    def _destroy_waveform(self) -> None:
        self.loader._destroy_waveform()

    def _on_waveform_loaded(self) -> None:
        self.loader._on_waveform_loaded()

    def _waveform_ready(self) -> bool:
        return self.loader._waveform_ready()

    def _run_auto_split(self) -> None:
        self.analysis._run_auto_split()

    def _run_slice_analysis(self) -> None:
        self.analysis._run_slice_analysis()

    def _get_current_markers(self) -> list[float]:
        return self.analysis._get_current_markers()

    def _has_valid_fill_interval(self) -> bool:
        return self.analysis._has_valid_fill_interval()

    def _run_fill_markers(self) -> None:
        self.analysis._run_fill_markers()

    def _on_analysis_started(self, path: str) -> None:
        self.analysis._on_analysis_started(path)

    def _apply_analysis_result(self, result, *, status_message: str | None = None, persist: bool):
        self.analysis._apply_analysis_result(
            result,
            status_message=status_message,
            persist=persist,
        )

    def _on_analysis_finished(self, result) -> None:
        self.analysis._on_analysis_finished(result)

    def _on_analysis_failed(self, path: str, message: str) -> None:
        self.analysis._on_analysis_failed(path, message)

    def _on_quantize_started(self, path: str) -> None:
        self.quantize._on_quantize_started(path)

    def _on_quantize_finished(self, preview) -> None:
        self.quantize._on_quantize_finished(preview)

    def _on_quantize_failed(self, path: str, message: str) -> None:
        self.quantize._on_quantize_failed(path, message)

    def _current_quantized_preview_signature(self):
        return self.quantize._current_quantized_preview_signature()

    def _toggle_audio_preview(self, path: str, duration_s: float) -> None:
        self.playback._toggle_audio_preview(path, duration_s)

    def _matches_path(self, path: str | None) -> bool:
        return self.playback._matches_path(path)

    def _apply_markers_to_waveform(self, result) -> None:
        self.markers._apply_markers_to_waveform(result)

    def _clear_waveform_markers(self) -> None:
        self.markers._clear_waveform_markers()

    def _on_hit_selected(self, hit_index: int) -> None:
        self.hits_table._on_hit_selected(hit_index)

    def _rebuild_hits_table(self, result) -> None:
        self.hits_table._rebuild_hits_table(result)

    def _clear_hits_table(self) -> None:
        self.hits_table._clear_hits_table()

    def _commit_manual_analysis_update(self, updated_slices, *, status_message: str | None = None):
        self.hits_table._commit_manual_analysis_update(
            updated_slices,
            status_message=status_message,
        )

    def _on_hit_label_changed(self, hit_index: int, new_label: str) -> None:
        self.hits_table._on_hit_label_changed(hit_index, new_label)

    def _on_hit_remove_requested(self, hit_index: int) -> None:
        self.hits_table._on_hit_remove_requested(hit_index)

    def _clear_analysis(self) -> None:
        self.hits_table._clear_analysis()

    def _on_strength_changed(self, value: int) -> None:
        self.quantize._on_strength_changed(value)

    def _refresh_quantized_projection(self, *_args) -> None:
        self.quantize._refresh_quantized_projection(*_args)

    def _create_quantized_preview(self) -> None:
        self.quantize._create_quantized_preview()

    def _preview_quantized_break(self) -> None:
        self.quantize._preview_quantized_break()

    def _refresh_actions(self) -> None:
        self.ui._refresh_actions()

    def eventFilter(self, watched, event):
        return self.dnd.eventFilter(watched, event)

    def dragEnterEvent(self, event):
        self.dnd.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self.dnd.dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.dnd.dragLeaveEvent(event)

    def dropEvent(self, event):
        self.dnd.dropEvent(event)

    def _handle_drag_enter(self, event) -> bool:
        return self.dnd._handle_drag_enter(event)

    def _handle_drag_move(self, event) -> bool:
        return self.dnd._handle_drag_move(event)

    def _handle_drag_leave(self, event) -> bool:
        return self.dnd._handle_drag_leave(event)

    def _handle_drop(self, event) -> bool:
        return self.dnd._handle_drop(event)

    def _paths_from_mime(self, mime) -> list[str]:
        return self.dnd._paths_from_mime(mime)

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        return self.dnd._path_for_sample_id(sample_id)

    def _set_drop_active(self, active: bool) -> None:
        self.dnd._set_drop_active(active)

    def _apply_styles(self) -> None:
        self.ui._apply_styles()
