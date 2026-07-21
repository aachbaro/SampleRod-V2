# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - L'onglet "Waveform" du Labo : il heberge l'editeur de forme d'onde
#   (WaveformWidget) et permet d'en CAPTURER de la matiere :
#   * "Creer une slice" : extrait la selection courante (region ou
#     intervalle entre marqueurs) dans un nouvel artefact ;
#   * "Capturer le fichier courant" : photographie l'etat actuel de
#     l'audio (avec toutes les editions) dans un artefact.
#   Chaque capture est ecrite dans un WAV temporaire et part au plateau
#   d'artefacts via le signal artifactCreated.
# - On peut deposer ici un fichier audio ou une carte de sample : il est
#   ouvert dans l'editeur (le precedent est proprement detruit).
#
# FONCTIONS (sommaire)
# - WaveformToolWidget (QWidget)
#   - signaux : artifactCreated(LabArtifact), separationRequested(paths)
#     (relaye depuis l'editeur vers le separateur de stems).
#   - _build_ui()        : en-tete, boutons d'action, zone d'accueil.
#   - open_file()        : charge un fichier dans un nouvel editeur.
#   - current_path()     : fichier actuellement ouvert.
#   - create_selection_artifact()   : bouton "Creer une slice".
#   - create_current_file_artifact(): bouton "Capturer le fichier courant".
#   - _replace_waveform_widget()/_destroy_waveform_widget() : cycle de vie
#     de l'editeur (arret du son, du timer, destruction propre).
#   - _on_waveform_loaded()/_waveform_ready()/_refresh_actions() : etats.
#   - _selection_bounds(): determine la plage a decouper — la region si
#     elle existe, sinon l'intervalle [marqueur courant, marqueur suivant].
#   - _extract_segment() : decoupe les echantillons audio de la plage.
#   - _write_temp_snapshot() : ecrit l'audio capture dans un WAV temp.
#   - _show_warning()    : message + boite d'alerte.
#   - eventFilter()/drag*/dropEvent/_handle_* : glisser-deposer d'ouverture.
#   - _paths_from_mime()/_path_for_sample_id() : decodage des depots.
#   - _set_drop_active()/_refresh_info_message()/_apply_styles().
#
# LIENS CLES
# - frontend/sample_gui/wave_form.py : l'editeur de forme d'onde integre.
# - frontend/labo/labo_widget.py     : recoit les artefacts crees ici.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
import uuid

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend.sample_gui.wave_form import WaveformWidget
from frontend.styles import theme
from frontend.ui import IconButton

from .lab_artifact import LabArtifact
from .waveform_tool_dnd import (
    can_accept_waveform_drop,
    has_supported_waveform_drop,
    resolve_waveform_drop_paths,
)


class WaveformToolWidget(QWidget):
    artifactCreated = Signal(object)
    separationRequested = Signal(list)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._current_path: str | None = None
        self._waveform_widget: WaveformWidget | None = None
        self._drop_active = False
        # Drop qui REMPLACE le fichier courant : actif en mode classique, mais
        # desactive dans l'atelier modulaire (le module ouvre alors un nouvel
        # onglet plutot que d'ecraser l'onglet courant).
        self._drop_replace_enabled = True
        self._build_ui()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("WaveformToolRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.editor_shell = QFrame()
        self.editor_shell.setObjectName("WaveformToolShell")
        self.editor_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        shell_layout = QVBoxLayout(self.editor_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(2)

        # Ligne unique : [Waveform] [chemin tronqué]  stretch  [Créer slice] [Capturer]
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.title_label = QLabel("Waveform")
        self.title_label.setObjectName("WaveformToolTitle")

        self.current_file_label = QLabel("Aucun fichier chargé")
        self.current_file_label.setObjectName("WaveformToolCurrentFile")
        self.current_file_label.setSizePolicy(
            self.current_file_label.sizePolicy().horizontalPolicy(),
            self.current_file_label.sizePolicy().verticalPolicy(),
        )

        self.slice_button = IconButton(
            "scissors", tooltip="Créer une slice de la sélection", size="s"
        )
        self.slice_button.clicked.connect(self.create_selection_artifact)

        self.current_file_button = IconButton(
            "camera", tooltip="Capturer le fichier courant en artefact", size="s"
        )
        self.current_file_button.clicked.connect(self.create_current_file_artifact)

        header.addWidget(self.title_label)
        header.addWidget(self.current_file_label, 1)
        header.addWidget(self.slice_button)
        header.addWidget(self.current_file_button)

        # info_label : placeholder visible uniquement quand aucun fichier n'est chargé
        self.info_label = QLabel(
            "Glisse un fichier ou sélectionne un sample dans la Reserve."
        )
        self.info_label.setObjectName("WaveformToolInfo")
        self.info_label.setWordWrap(True)

        self.waveform_host = QWidget()
        self.waveform_host.setObjectName("WaveformToolHost")
        self.waveform_host.setAcceptDrops(True)
        self.waveform_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.waveform_host.setMaximumHeight(390)
        self.waveform_host.installEventFilter(self)
        self.waveform_layout = QVBoxLayout(self.waveform_host)
        self.waveform_layout.setContentsMargins(0, 0, 0, 0)
        self.waveform_layout.setSpacing(0)

        self.current_file_label.setVisible(False)

        shell_layout.addLayout(header)
        shell_layout.addWidget(self.info_label)
        shell_layout.addWidget(self.waveform_host, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(self.editor_shell, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

        self._apply_styles()
        self._refresh_actions()

    def open_file(self, path: str) -> bool:
        """Ouvre un fichier audio dans l'editeur (recree le widget).

        Si le fichier demande est deja ouvert, on se contente de reprendre
        le focus. Renvoie True si le fichier est (ou etait) ouvert.
        """
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False
        if self._current_path == normalized and self._waveform_widget is not None:
            self.setFocus()
            return True

        self._current_path = normalized
        self.current_file_label.setText(normalized)
        self._refresh_info_message()
        self._replace_waveform_widget(normalized)
        self._refresh_actions()
        return True

    def current_path(self) -> str | None:
        return self._current_path

    def save_state(self) -> dict:
        """Etat persistable pour la restauration de session (atelier modulaire)."""
        return {"path": self._current_path or ""}

    def restore_state(self, state: dict) -> None:
        """Recharge le fichier memorise lors de la restauration de session."""
        path = str((state or {}).get("path") or "")
        if path and os.path.isfile(path):
            self.open_file(path)

    def cleanup(self) -> None:
        """Arrete la lecture et detruit proprement l'editeur.

        A appeler AVANT de supprimer ce widget (fermeture d'onglet / de module)
        pour eviter que le callback audio sounddevice n'emette sur un widget
        deja detruit ("Signal source has been deleted").
        """
        self._destroy_waveform_widget()

    def create_selection_artifact(self) -> None:
        """Bouton "Creer une slice" : capture la selection en artefact.

        Etapes : trouver la plage selectionnee, extraire les echantillons,
        les ecrire dans un WAV temporaire, fabriquer la fiche LabArtifact
        et l'emettre vers le plateau. Chaque probleme (pas de selection,
        slice vide...) est explique a l'utilisateur.
        """
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            self._show_warning("Le waveform n'est pas encore pret.")
            return

        bounds = self._selection_bounds()
        if bounds is None:
            self._show_warning("Aucune selection exploitable. Cree une region ou utilise les markers.")
            return

        start_time, end_time = bounds
        audio = self._extract_segment(start_time, end_time)
        if audio.size == 0:
            self._show_warning("La slice est vide.")
            return

        base_name = os.path.splitext(os.path.basename(self._current_path or "slice"))[0]
        display_name = f"{base_name}_slice_{start_time:.2f}_{end_time:.2f}"
        temp_path = self._write_temp_snapshot(audio, int(waveform.sample_rate), display_name)
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="slice",
            display_name=display_name,
            source_path=self._current_path or "",
            temp_path=temp_path,
            start_time=float(start_time),
            end_time=float(end_time),
            duration=float(end_time - start_time),
            persisted=False,
            origin="waveform_selection",
            operation="slice_selection",
            sample_rate=int(waveform.sample_rate),
        )
        self.info_label.setText(f"Artefact cree: {display_name}")
        self.artifactCreated.emit(artifact)

    def create_current_file_artifact(self) -> None:
        """Bouton "Capturer le fichier courant" : photographie l'audio entier.

        Capture l'etat ACTUEL de l'editeur (editions comprises), pas le
        fichier d'origine sur le disque.
        """
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            self._show_warning("Le waveform n'est pas encore pret.")
            return

        audio = np.asarray(waveform.waveform_data, dtype="float32").copy()
        duration = float(waveform.duration or 0.0)
        base_name = os.path.splitext(os.path.basename(self._current_path or "current_file"))[0]
        display_name = f"{base_name}_current"
        temp_path = self._write_temp_snapshot(audio, int(waveform.sample_rate), display_name)
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="current_file",
            display_name=display_name,
            source_path=self._current_path or "",
            temp_path=temp_path,
            duration=duration,
            persisted=False,
            origin="waveform_current_file",
            operation="capture_current_file",
            sample_rate=int(waveform.sample_rate),
        )
        self.info_label.setText(f"Artefact cree: {display_name}")
        self.artifactCreated.emit(artifact)

    def _replace_waveform_widget(self, path: str) -> None:
        """Detruit l'editeur courant et en cree un neuf pour ce fichier."""
        self._destroy_waveform_widget()

        waveform = WaveformWidget(path, self.app_context)
        waveform.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        waveform.setMaximumHeight(380)
        waveform.setAcceptDrops(self._drop_replace_enabled)
        waveform.installEventFilter(self)
        waveform.separationRequested.connect(
            lambda p: self.separationRequested.emit([p])
        )
        self.waveform_layout.addWidget(waveform, 0, Qt.AlignmentFlag.AlignTop)
        self._waveform_widget = waveform

        loader = getattr(waveform, "loader", None)
        if loader is not None:
            loader.finished.connect(self._on_waveform_loaded)
        else:
            self._on_waveform_loaded()

    def _destroy_waveform_widget(self) -> None:
        """Demonte proprement l'editeur : son coupe, timer arrete, widget detruit."""
        if self._waveform_widget is None:
            return
        try:
            self._waveform_widget.removeEventFilter(self)
        except Exception:
            pass
        try:
            self._waveform_widget.stop_audio()
        except Exception:
            pass
        try:
            self._waveform_widget.timer.stop()
        except Exception:
            pass
        self.waveform_layout.removeWidget(self._waveform_widget)
        self._waveform_widget.deleteLater()
        self._waveform_widget = None

    def _on_waveform_loaded(self) -> None:
        self._refresh_info_message()
        self._refresh_actions()

    def _waveform_ready(self) -> bool:
        return bool(
            self._waveform_widget is not None
            and getattr(self._waveform_widget, "waveform_data", None) is not None
            and getattr(self._waveform_widget, "sample_rate", None)
        )

    def _refresh_actions(self) -> None:
        ready = self._waveform_ready()
        self.slice_button.setEnabled(bool(self._current_path) and ready)
        self.current_file_button.setEnabled(bool(self._current_path) and ready)

    def _selection_bounds(self) -> tuple[float, float] | None:
        """Determine la plage de temps a decouper (en secondes).

        Priorite a la REGION (la zone surlignee creee a la souris) ; a
        defaut, on prend l'intervalle entre le marqueur courant et le
        suivant (ou la fin du fichier). None si rien d'exploitable.
        """
        waveform = self._waveform_widget
        if waveform is None:
            return None
        region = getattr(waveform, "region", None)
        if region is not None:
            start, end = region.getRegion()
            if end > start:
                return float(start), float(end)

        markers = list(getattr(waveform, "markers", []) or [])
        if not markers:
            return None

        idx = int(getattr(waveform, "current_marker_idx", 0) or 0)
        idx = max(0, min(idx, len(markers) - 1))
        start = float(markers[idx])
        end = float(markers[idx + 1]) if idx + 1 < len(markers) else float(waveform.duration or 0.0)
        if end <= start:
            return None
        return start, end

    def _extract_segment(self, start_time: float, end_time: float):
        """Decoupe les echantillons audio entre deux instants (en secondes).

        Conversion temps -> index d'echantillon : seconde x frequence
        d'echantillonnage (ex : 2,5 s a 44100 Hz = echantillon 110250).
        """
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            return np.array([], dtype="float32")

        start_sample = int(float(start_time) * float(waveform.sample_rate))
        end_sample = int(float(end_time) * float(waveform.sample_rate))
        data = np.asarray(waveform.waveform_data)
        return data[start_sample:end_sample].astype("float32").copy()

    def _write_temp_snapshot(self, audio, sample_rate: int, display_name: str) -> str:
        """Ecrit l'audio capture dans un WAV temporaire au nom unique."""
        filename = f"samplerod_{display_name}_{uuid.uuid4().hex[:8]}.wav"
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        sf.write(temp_path, audio, int(sample_rate))
        return temp_path

    def _show_warning(self, message: str) -> None:
        self.info_label.setText(message)
        QMessageBox.warning(self, "Waveform", message)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if event_type == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if event_type == QEvent.Type.DragLeave:
            return self._handle_drag_leave(event)
        if event_type == QEvent.Type.Drop:
            return self._handle_drop(event)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if self._handle_drag_enter(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._handle_drag_move(event):
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if self._handle_drag_leave(event):
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._handle_drop(event):
            return
        super().dropEvent(event)

    def set_drop_replace_enabled(self, enabled: bool) -> None:
        """Active/desactive le drop qui remplace le fichier courant.

        Desactive dans l'atelier modulaire : les drops remontent alors au
        WaveformModule (qui ouvre un nouvel onglet), au lieu d'ecraser l'onglet.
        """
        self._drop_replace_enabled = bool(enabled)
        self.setAcceptDrops(self._drop_replace_enabled)
        if getattr(self, "waveform_host", None) is not None:
            self.waveform_host.setAcceptDrops(self._drop_replace_enabled)
        if self._waveform_widget is not None:
            self._waveform_widget.setAcceptDrops(self._drop_replace_enabled)

    def _handle_drag_enter(self, event) -> bool:
        if not self._drop_replace_enabled:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime):
            self._set_drop_active(False)
            return False
        if not can_accept_waveform_drop(
            mime,
            sample_path_lookup=self._path_for_sample_id,
            artifact_path_lookup=self._path_for_artifact_id,
        ):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_move(self, event) -> bool:
        if not self._drop_replace_enabled:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime):
            self._set_drop_active(False)
            return False
        if not can_accept_waveform_drop(
            mime,
            sample_path_lookup=self._path_for_sample_id,
            artifact_path_lookup=self._path_for_artifact_id,
        ):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_leave(self, event) -> bool:
        self._set_drop_active(False)
        event.accept()
        return True

    def _handle_drop(self, event) -> bool:
        if not self._drop_replace_enabled:
            return False
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        opened = any(self.open_file(path) for path in paths)
        if not opened:
            return False
        event.acceptProposedAction()
        self.setFocus()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_waveform_drop_paths(
            mime,
            sample_path_lookup=self._path_for_sample_id,
            artifact_path_lookup=self._path_for_artifact_id,
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        samples = self.app_context.sample_store.get_cached()
        sample = next((item for item in samples if int(getattr(item, "id", -1)) == int(sample_id)), None)
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    def _path_for_artifact_id(self, artifact_id: str) -> str | None:
        store = getattr(self.app_context, "lab_artifact_store", None)
        resolver = getattr(store, "resolve_path", None)
        if callable(resolver):
            return resolver(artifact_id)
        return None

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.waveform_host.setProperty("dropActive", active)
        self.waveform_host.style().unpolish(self.waveform_host)
        self.waveform_host.style().polish(self.waveform_host)
        self._refresh_info_message()

    def _refresh_info_message(self) -> None:
        if self._drop_active:
            self.info_label.setText("Dépose un fichier ou un sample de la Reserve.")
            self.info_label.setVisible(True)
            self.current_file_label.setVisible(False)
            return
        if self._current_path is None:
            self.info_label.setText("Glisse un fichier ou sélectionne un sample dans la Reserve.")
            self.info_label.setVisible(True)
            self.current_file_label.setVisible(False)
        else:
            self.info_label.setVisible(False)
            name = os.path.basename(self._current_path)
            self.current_file_label.setText(name)
            self.current_file_label.setToolTip(self._current_path)
            self.current_file_label.setVisible(True)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#WaveformToolRoot {{
                background: transparent;
                border: none;
            }}
            QWidget#WaveformToolHost {{
                background: transparent;
                border: 1px dashed transparent;
                border-radius: 10px;
            }}
            QFrame#WaveformToolShell {{
                background: transparent;
                border: none;
            }}
            QWidget#WaveformToolHost[dropActive="true"] {{
                background: {p.BG_CARD};
                border-color: {p.INFO};
            }}
            QLabel#WaveformToolTitle {{
                color: {p.TEXT};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#WaveformToolCurrentFile {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#WaveformToolInfo {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
                padding: 4px 0;
            }}
            """
        )
