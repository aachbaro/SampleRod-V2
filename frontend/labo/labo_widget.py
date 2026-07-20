# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - L'onglet LABO : la "table de travail" ou l'on transforme la matiere audio.
# - Organisation visuelle :
#   * en haut : quatre outils en onglets - Waveform (editeur de forme
#     d'onde), Break (analyse/decoupage de boucles de batterie), Stems
#     (separation voix/batterie/basse...), Compositeur (assemblage) ;
#   * en bas : le plateau des ARTEFACTS, ou atterrissent tous les resultats
#     produits par ces outils (slices, stems, breaks generes...) ;
#   * a droite : les BACS (bins) lies a la Reserve.
# - Ce widget est surtout un CHEF DE GARE : il cree les outils, relie leurs
#   signaux entre eux (un outil produit un artefact -> le plateau l'affiche ;
#   le plateau demande "sauvegarder" -> on copie le fichier et on l'ajoute
#   au catalogue ; "ouvrir" -> l'editeur Waveform charge le fichier...).
#
# FONCTIONS (sommaire)
# - LaboWidget (QWidget)
#   - signaux : openReserveDirectoryRequested, reserveRefreshRequested,
#     reservePathsMoved (relayes depuis les bacs vers la Reserve).
#   - _build_ui()        : assemble outils, plateau, bacs ; restaure la
#                          position du separateur depuis QSettings.
#   - _on_splitter_moved(): memorise la position du separateur.
#   - _apply_default_splitter_sizes() : repartition initiale 40/60.
#   - _bind_signals()    : tous les cablages decrits ci-dessus.
#   - _send_to_stem_separator() : envoie des fichiers au separateur.
#   - open_paths()       : ouvre un fichier dans l'editeur Waveform
#                          (utilise par le double-clic ailleurs dans l'app).
#   - _upsert_artifact() : enregistre/actualise un artefact + plateau.
#   - _save_artifact()   : dialogue de dossier, copie du fichier, ajout au
#                          catalogue des samples, marque "persiste".
#   - _open_artifact_in_waveform() : recharge un artefact dans l'editeur.
#   - _default_export_dir(): meilleur dossier propose (dernier utilise >
#                          dossier source > premiere librairie > home).
#   - _unique_target_path(): evite d'ecraser un fichier (suffixe _2, _3...).
#   - _apply_styles()    : styles dependant du theme.
#
# LIENS CLES
# - frontend/labo/waveform_tool.py / break_widget.py / stem_separator_tool.py
# - frontend/right_panel/composer/composer_widget.py
# - frontend/labo/artifact_tray.py / bins_panel.py
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.right_panel.composer.composer_widget import SampleComposerWidget
from frontend.styles import theme

from .artifact_tray import ArtifactTrayWidget
from .bins_panel import LaboBinsPanel
from .break_widget import BreakWidget
from .lab_artifact import LabArtifact, artifact_file_path, build_artifact_filename
from .stem_separator_tool import StemSeparatorToolWidget
from .waveform_tool import WaveformToolWidget


class LaboWidget(QWidget):
    """Atelier labo: waveform editor + composer + first reusable artifacts."""

    openReserveDirectoryRequested = Signal(str)
    reserveRefreshRequested = Signal()
    reservePathsMoved = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._qs = QSettings("SampleRod", "Main")
        self._artifacts: dict[str, LabArtifact] = {}
        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("LaboRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self.title_label = QLabel("Labo")
        self.title_label.setObjectName("LaboTitle")

        self.tools_tabs = QTabWidget()
        self.tools_tabs.setObjectName("LaboTabs")

        self.waveform_tool = WaveformToolWidget(self.app_context)
        self.stem_separator_tool = StemSeparatorToolWidget(self.app_context)
        self.composer_widget = SampleComposerWidget(self.app_context)
        self.break_widget = BreakWidget(self.app_context)

        self.tools_tabs.addTab(self.waveform_tool, "Waveform")
        self.tools_tabs.addTab(self.break_widget, "Break")
        self.tools_tabs.addTab(self.stem_separator_tool, "Stems")
        self.tools_tabs.addTab(self.composer_widget, "Compositeur")
        self.tools_tabs.setCurrentIndex(0)
        self.tools_tabs.setMinimumHeight(250)

        self.artifact_tray = ArtifactTrayWidget(self.app_context)
        self.artifact_tray.setMinimumHeight(220)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("LaboSplitter")
        self.splitter.addWidget(self.tools_tabs)
        self.splitter.addWidget(self.artifact_tray)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setChildrenCollapsible(False)

        saved_state = self._qs.value("labo_splitter_state_v5")
        if saved_state:
            try:
                self.splitter.restoreState(saved_state)
            except Exception:
                QTimer.singleShot(0, self._apply_default_splitter_sizes)
        else:
            QTimer.singleShot(0, self._apply_default_splitter_sizes)

        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        self.bins_panel = LaboBinsPanel(self.app_context, self._qs)
        self.bins_panel.setObjectName("LaboBinsPanel")

        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(8)
        body_row.addWidget(self.splitter, 1)
        body_row.addWidget(self.bins_panel, 0)

        layout.addWidget(self.title_label)
        layout.addLayout(body_row, 1)

        self._apply_styles()

    def _on_splitter_moved(self, *_) -> None:
        self._qs.setValue("labo_splitter_state_v5", self.splitter.saveState())

    def _apply_default_splitter_sizes(self) -> None:
        total = self.splitter.height() or self.height() or 900
        top = max(self.tools_tabs.minimumHeight(), int(total * 0.40))
        bottom = max(self.artifact_tray.minimumHeight(), total - top)
        if top + bottom > total:
            overflow = top + bottom - total
            reducible_top = max(0, top - self.tools_tabs.minimumHeight())
            reduce_by = min(reducible_top, overflow)
            top -= reduce_by
            overflow -= reduce_by
            if overflow > 0:
                bottom = max(self.artifact_tray.minimumHeight(), bottom - overflow)
        self.splitter.setSizes([top, bottom])

    def _bind_signals(self) -> None:
        self.waveform_tool.artifactCreated.connect(self._upsert_artifact)
        self.stem_separator_tool.artifactCreated.connect(self._upsert_artifact)
        self.break_widget.artifactCreated.connect(self._upsert_artifact)
        self.artifact_tray.saveArtifactRequested.connect(self._save_artifact)
        self.artifact_tray.openArtifactRequested.connect(self._open_artifact_in_waveform)
        self.waveform_tool.separationRequested.connect(self._send_to_stem_separator)
        self.bins_panel.openInReserveRequested.connect(self.openReserveDirectoryRequested.emit)
        self.bins_panel.reserveRefreshRequested.connect(self.reserveRefreshRequested.emit)
        self.bins_panel.sourcePathsMoved.connect(self.reservePathsMoved.emit)

    def _send_to_stem_separator(self, paths: list) -> None:
        """Envoie les chemins au separateur de stems (sans changer d'onglet)."""
        if not paths:
            return
        count = self.stem_separator_tool.enqueue_paths(paths)
        if count > 0:
            info = getattr(self.waveform_tool, "info_label", None)
            if info is not None:
                info.setText(
                    "Envoye au separateur de stems - les stems arriveront dans les artefacts."
                )

    def open_paths(self, paths: list[str]) -> None:
        """Ouvre le premier fichier valide dans l'editeur Waveform et y bascule."""
        if not paths:
            return
        target_path = next((path for path in paths if path and os.path.isfile(path)), None)
        if target_path is None:
            return
        if self.waveform_tool.open_file(target_path):
            self.tools_tabs.setCurrentWidget(self.waveform_tool)
            self.waveform_tool.setFocus()

    def _upsert_artifact(self, artifact: LabArtifact) -> None:
        """Ajoute ou met a jour un artefact dans le registre et le plateau."""
        self._artifacts[artifact.artifact_id] = artifact
        self.artifact_tray.upsert_artifact(artifact)

    def _save_artifact(self, artifact_id: str) -> None:
        """Sauvegarde definitive d'un artefact choisi dans le plateau."""
        artifact = self._artifacts.get(artifact_id)
        source_path = artifact_file_path(artifact) if artifact is not None else ""
        if artifact is None or not source_path or not os.path.isfile(source_path):
            return

        default_dir = self._default_export_dir(artifact)
        target_dir = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier pour l'artefact",
            default_dir,
        )
        if not target_dir:
            return

        self._qs.setValue("labo_last_artifact_dir", target_dir)

        target_path = self._unique_target_path(
            target_dir,
            build_artifact_filename(artifact),
        )
        shutil.copy2(source_path, target_path)
        self.app_context.sample_store.add(target_path)

        artifact.persisted = True
        artifact.metadata["saved_path"] = target_path
        self.artifact_tray.upsert_artifact(artifact)

    def _open_artifact_in_waveform(self, artifact_id: str) -> None:
        """Recharge le fichier d'un artefact dans l'editeur Waveform."""
        artifact = self._artifacts.get(artifact_id)
        path = artifact_file_path(artifact) if artifact is not None else ""
        if not path or not os.path.isfile(path):
            return
        if self.waveform_tool.open_file(path):
            self.tools_tabs.setCurrentWidget(self.waveform_tool)
            self.waveform_tool.setFocus()

    def _default_export_dir(self, artifact: LabArtifact) -> str:
        """Meilleur dossier a proposer dans le dialogue de sauvegarde."""
        last_dir = self._qs.value("labo_last_artifact_dir", "")
        if isinstance(last_dir, str) and last_dir and os.path.isdir(last_dir):
            return last_dir
        source_folder = os.path.dirname(artifact.source_path or "")
        if source_folder and os.path.isdir(source_folder):
            return source_folder
        libraries = getattr(self.app_context.settings, "libraries", []) or []
        if libraries:
            path = getattr(sorted(libraries, key=lambda lib: lib.position)[0], "path", "")
            if path and os.path.isdir(path):
                return path
        return os.path.expanduser("~")

    @staticmethod
    def _unique_target_path(folder: str, filename: str) -> str:
        """Trouve un chemin libre dans le dossier (suffixe _2, _3... si pris)."""
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(folder, filename)
        if not os.path.exists(candidate):
            return candidate
        index = 2
        while True:
            candidate = os.path.join(folder, f"{base}_{index}{ext}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#LaboRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#LaboTitle {{
                color: {p.TEXT};
                font-size: 14px;
                font-weight: 600;
            }}
            QTabWidget#LaboTabs::pane {{
                border: none;
                background: transparent;
                padding-top: 8px;
            }}
            QTabWidget#LaboTabs QTabBar::tab {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 4px 10px;
                margin-right: 6px;
            }}
            QTabWidget#LaboTabs QTabBar::tab:selected {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QTabWidget#LaboTabs QTabBar::tab:hover {{
                background: {p.BG_MEDIUM};
                border-color: {p.BORDER_LIGHT};
            }}
            QSplitter#LaboSplitter::handle:vertical {{
                height: 5px;
                background: transparent;
                margin: 0;
            }}
            QSplitter#LaboSplitter::handle:vertical:hover {{
                background: {p.BORDER_LIGHT};
            }}
            """
        )
