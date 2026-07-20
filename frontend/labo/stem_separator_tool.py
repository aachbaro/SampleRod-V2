# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - L'onglet "Stems" du Labo : interface ergonomique de separation de pistes
#   (voix / batterie / basse / autres) assuree par StemSeparatorService.
# - Flux utilisateur :
#   1. choisir un modele IA et un dossier de travail (memorises en QSettings) ;
#   2. glisser un sample (ou un bout de sample) dans la zone de depot : la
#      separation demarre et un ONGLET est cree pour ce fichier ;
#   3. quand c'est pret, l'onglet montre les pistes separees (tuiles
#      draggables) + un MIXER pour les remixer ensemble ;
#   4. on glisse les pistes / le mix vers un autre outil ou l'exterieur ; le
#      mix peut aussi partir vers le plateau d'ARTEFACTS (artifactCreated).
#
# FONCTIONS (sommaire)
# - StemSeparatorToolWidget (QWidget)
#   - signal artifactCreated(LabArtifact) : un mix est envoye aux artefacts.
#   - _build_ui()      : header (modele + dossier en icones), zone de depot,
#                        onglets de sessions.
#   - enqueue_paths()  : cree les onglets + lance la separation (point d'entree
#                        commun au drop, au Labo et au routage Waveform->Stems).
#   - _ensure_session()/_on_file_started/_finished/_failed : mapping
#                        fichier source -> onglet de session.
#   - eventFilter()/drag*/dropEvent : glisser-deposer entrant.
#
# LIENS CLES
# - backend/services/stem_separator_service.py : le service pilote ici.
# - frontend/labo/stem_widgets.py : StemSessionWidget / StemTile / mixer.
# - frontend/ui/ : IconButton (boutons icone + tooltips).
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import is_audio_file, normalize_audio_path
from frontend.styles import theme
from frontend.ui import IconButton, add_tab_close_button

from .audio_drop import (
    can_accept_audio_drop,
    has_supported_audio_drop,
    resolve_audio_drop_paths,
)
from .stem_widgets import StemSessionWidget


class StemSeparatorToolWidget(QWidget):
    artifactCreated = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.service = self.app_context.stem_separator
        self._qs = QSettings("SampleRod", "Main")
        self._drop_active = False
        self._sessions: dict[str, StemSessionWidget] = {}
        self._service_status_text = ""
        self._build_ui()
        self._restore_settings()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    # -- Construction -------------------------------------------------------
    def _build_ui(self) -> None:
        self.setObjectName("StemToolRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Le drop qui lance une separation n'est accepte QUE dans la zone du
        # haut (drop_zone), pas sur tout le module : on peut ainsi annuler un
        # drag ailleurs sans declencher une separation par megarde.
        self.setAcceptDrops(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header leger : modele + dossier de travail + annuler (icones/tooltips)
        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 0)
        header.setSpacing(6)

        self.title_label = QLabel("Stems")
        self.title_label.setObjectName("StemToolTitle")

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("StemToolCombo")
        self.model_combo.setToolTip("Modele de separation IA")
        for model in self.service.available_models:
            self.model_combo.addItem(model, model)

        self.output_button = IconButton(
            "folder", tooltip="Dossier de travail des stems", size="s"
        )
        self.output_button.clicked.connect(self._choose_workspace_dir)

        self.cancel_button = IconButton(
            "x", tooltip="Annuler la separation en cours", size="s"
        )
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.service.cancel_current)

        header.addWidget(self.title_label, 0)
        header.addStretch(1)
        header.addWidget(self.model_combo, 0)
        header.addWidget(self.output_button, 0)
        header.addWidget(self.cancel_button, 0)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StemToolStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setContentsMargins(10, 0, 10, 0)

        # Zone de depot compacte
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("StemToolDropZone")
        self.drop_zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.drop_zone.setAcceptDrops(True)
        drop_l = QHBoxLayout(self.drop_zone)
        drop_l.setContentsMargins(12, 10, 12, 10)
        drop_l.setSpacing(8)
        self.drop_hint_icon = QLabel("+")
        self.drop_hint_icon.setObjectName("StemDropPlus")
        self.drop_help = QLabel(
            "Depose un sample (ou un bout de sample) pour lancer la separation."
        )
        self.drop_help.setObjectName("StemToolDropHelp")
        self.drop_help.setWordWrap(True)
        drop_l.addWidget(self.drop_hint_icon, 0)
        drop_l.addWidget(self.drop_help, 1)

        # Onglets : un par fichier source
        self.tabs = QTabWidget()
        self.tabs.setObjectName("StemTabs")
        # Croix custom (IconButton) au lieu du bouton de fermeture par defaut.
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)

        self.empty_label = QLabel(
            "Aucune separation en cours. Depose de la matiere pour commencer."
        )
        self.empty_label.setObjectName("StemToolEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        header_wrap = QWidget()
        header_wrap.setLayout(header)

        layout.addWidget(header_wrap)
        layout.addWidget(self.status_label)
        layout.addWidget(self.drop_zone)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(self.tabs, 1)

        self.drop_zone.installEventFilter(self)
        self._refresh_tabs_visibility()
        self._apply_styles()

    def _bind_signals(self) -> None:
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.service.statusChanged.connect(self._set_status)
        self.service.initialized.connect(self._on_initialized)
        self.service.fileStarted.connect(self._on_file_started)
        self.service.fileFinished.connect(self._on_file_finished)
        self.service.fileFailed.connect(self._on_file_failed)
        self.service.queueIdle.connect(self._on_queue_idle)

    # -- Point d'entree separation -----------------------------------------
    def enqueue_paths(self, paths: list[str]) -> int:
        """Cree les onglets et lance la separation. Renvoie le nombre lance."""
        valid: list[str] = []
        seen: set[str] = set()
        for path in paths or []:
            normalized = normalize_audio_path(path)
            if (
                not normalized
                or normalized in seen
                or not os.path.isfile(normalized)
                or not is_audio_file(normalized)
            ):
                continue
            seen.add(normalized)
            valid.append(normalized)
        if not valid:
            return 0
        if not self.service.is_available():
            self._set_status(self.service.availability_error() or "Separateur indisponible.")
            return 0
        if not self.service.output_dir:
            self._set_status("Choisis un dossier de travail pour les stems.")
            return 0
        for path in valid:
            self._ensure_session(path)
        return self.service.enqueue_paths(valid)

    def _ensure_session(self, path: str) -> StemSessionWidget:
        normalized = normalize_audio_path(path)
        existing = self._sessions.get(normalized)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return existing
        session = StemSessionWidget(self.app_context, normalized)
        session.artifactRequested.connect(self.artifactCreated.emit)
        self._sessions[normalized] = session
        index = self.tabs.addTab(session, Path(normalized).stem)
        self.tabs.setTabToolTip(index, normalized)
        add_tab_close_button(self.tabs, index, lambda: self._close_session(session))
        self.tabs.setCurrentIndex(index)
        self._refresh_tabs_visibility()
        return session

    def _close_session(self, session) -> None:
        index = self.tabs.indexOf(session)
        if index >= 0:
            self._close_tab(index)

    def _close_tab(self, index: int) -> None:
        session = self.tabs.widget(index)
        self.tabs.removeTab(index)
        for key, value in list(self._sessions.items()):
            if value is session:
                self._sessions.pop(key, None)
                self.service.remove_pending_path(key)
                break
        if session is not None:
            session.deleteLater()
        self._refresh_tabs_visibility()

    def _refresh_tabs_visibility(self) -> None:
        has_tabs = self.tabs.count() > 0
        self.tabs.setVisible(has_tabs)
        self.empty_label.setVisible(not has_tabs)

    # -- Reactions du service ----------------------------------------------
    def _on_initialized(self, ok: bool, message: str) -> None:
        if not ok:
            self.cancel_button.setEnabled(False)
        self._set_status(message)

    def _on_file_started(self, path: str) -> None:
        session = self._sessions.get(normalize_audio_path(path))
        if session is not None:
            session.set_separating()
        self.cancel_button.setEnabled(True)

    def _on_file_finished(self, source_path: str, stem_dir: str) -> None:
        session = self._sessions.get(normalize_audio_path(source_path))
        if session is not None:
            session.populate_stems(stem_dir)

    def _on_file_failed(self, source_path: str, message: str) -> None:
        session = self._sessions.get(normalize_audio_path(source_path))
        if session is not None:
            session.set_failed(message)

    def _on_queue_idle(self) -> None:
        self.cancel_button.setEnabled(bool(self.service.current_path()))

    # -- Reglages -----------------------------------------------------------
    def _restore_settings(self) -> None:
        saved_model = self._qs.value("labo_stem_model", self.service.model_name, type=str)
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) == saved_model:
                self.model_combo.setCurrentIndex(index)
                break
        workspace_dir = self._qs.value("labo_stem_workspace_dir", "", type=str)
        if not workspace_dir or not os.path.isdir(workspace_dir):
            workspace_dir = os.path.join(tempfile.gettempdir(), "SampleRod", "stem_workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        self._set_workspace_dir(workspace_dir)
        self._refresh_status()

    def _choose_workspace_dir(self) -> None:
        start_dir = self.service.output_dir or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de travail des stems", start_dir
        )
        if folder:
            self._set_workspace_dir(folder)
            self._set_status("Dossier de travail mis a jour.")

    def _set_workspace_dir(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        os.makedirs(normalized, exist_ok=True)
        self.service.set_output_dir(normalized)
        self._qs.setValue("labo_stem_workspace_dir", normalized)
        self.output_button.setToolTip(f"Dossier de travail :\n{normalized}")

    def _on_model_changed(self, _index: int) -> None:
        model = self.model_combo.currentData()
        if not model:
            return
        self.service.set_model(str(model))
        self._qs.setValue("labo_stem_model", str(model))
        self._refresh_status()

    # -- Glisser-deposer entrant -------------------------------------------
    def eventFilter(self, watched, event):
        if watched is getattr(self, "drop_zone", None):
            etype = event.type()
            if etype == QEvent.Type.DragEnter:
                return self._handle_drag_enter(event)
            if etype == QEvent.Type.DragMove:
                return self._handle_drag_enter(event)
            if etype == QEvent.Type.DragLeave:
                self._set_drop_active(False)
                return True
            if etype == QEvent.Type.Drop:
                return self._handle_drop(event)
        return super().eventFilter(watched, event)

    def _handle_drag_enter(self, event) -> bool:
        mime = event.mimeData()
        if not has_supported_audio_drop(mime):
            self._set_drop_active(False)
            return False
        if not can_accept_audio_drop(mime, sample_path_lookup=self._path_for_sample_id):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drop(self, event) -> bool:
        paths = resolve_audio_drop_paths(
            event.mimeData(), sample_path_lookup=self._path_for_sample_id
        )
        self._set_drop_active(False)
        if not paths:
            return False
        count = self.enqueue_paths(paths)
        if count <= 0:
            return False
        event.acceptProposedAction()
        return True

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        store = getattr(self.app_context, "sample_store", None)
        if store is None:
            return None
        samples = store.get_cached()
        sample = next(
            (s for s in samples if int(getattr(s, "id", -1)) == int(sample_id)), None
        )
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    # -- Etats visuels ------------------------------------------------------
    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.drop_zone.setProperty("dropActive", active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def _refresh_status(self, *, extra: str = "") -> None:
        if extra:
            self.status_label.setText(extra)
            return
        if not self.service.is_available():
            self.status_label.setText(
                self.service.availability_error() or "Stem separator indisponible."
            )
            return
        if self._service_status_text:
            self.status_label.setText(self._service_status_text)
            return
        self.status_label.setText("Pret. Depose un sample pour separer.")

    def _set_status(self, text: str) -> None:
        self._service_status_text = text or ""
        self._refresh_status()

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#StemToolRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#StemToolTitle {{ color: {p.TEXT}; font-size: 15px; font-weight: 700; }}
            QLabel#StemToolStatus, QLabel#StemToolDropHelp, QLabel#StemToolEmpty {{
                color: {p.TEXT_MUTED}; font-size: 11px;
            }}
            QFrame#StemToolDropZone {{
                background: {p.BG_CARD};
                border: 1px dashed {p.BORDER_LIGHT};
                border-radius: 12px;
            }}
            QFrame#StemToolDropZone[dropActive="true"] {{
                border-color: {p.INFO};
                background: {p.BG_HOVER};
            }}
            QLabel#StemDropPlus {{
                color: {p.INFO}; font-size: 20px; font-weight: 700;
            }}
            QComboBox#StemToolCombo {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 4px 8px;
            }}
            QComboBox#StemToolCombo:hover {{ border-color: {p.BORDER_LIGHT}; }}
            """
        )
