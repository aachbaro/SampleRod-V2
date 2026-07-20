# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Briques visuelles du separateur de stems (nouvelle UI ergonomique) :
#   * StemTile      : tuile draggable representant un stem (ou un mix) ;
#                     drag = URL du fichier (vers Waveform, autres outils, ou
#                     un logiciel externe type Renoise) ; bouton d'ecoute.
#   * StemMixerZone : zone ou l'on glisse des stems pour les remixer ensemble
#                     (preview du mix, tuile de resultat draggable + artefact).
#   * StemSessionWidget : un onglet = un fichier source. Separation -> 4 stems
#                     -> mixer.
#
# LIENS CLES
# - frontend/ui/                       : IconButton (boutons icone + tooltip).
# - frontend/labo/audio_drop.py        : acceptation / resolution des depots.
# - backend/services/stem_separator_service.py : mix_stem_files().
# - frontend/labo/lab_artifact.py      : sortie vers le plateau d'artefacts.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import (
    collect_audio_file_metadata,
    get_audio_duration,
    normalize_audio_path,
)
from backend.services.stem_separator_service import mix_stem_files
from frontend.custom_widgets import CustomSlider
from frontend.styles import theme
from frontend.ui import IconButton

from .audio_drop import (
    can_accept_audio_drop,
    has_supported_audio_drop,
    resolve_audio_drop_paths,
)
from .lab_artifact import LabArtifact


def _fmt_ms(ms: float) -> str:
    total = max(0, int(ms)) // 1000
    return f"{total // 60}:{total % 60:02d}"

STEM_COLORS: dict[str, str] = {
    "drums": "#d46666",
    "bass": "#7a6fd4",
    "vocals": "#4bb6b7",
    "other": "#d8a747",
    "guitar": "#c77dbb",
    "piano": "#6fa8d4",
}
_DEFAULT_STEM_COLOR = "#8a8f98"


def stem_color(name: str) -> str:
    return STEM_COLORS.get(str(name).lower(), _DEFAULT_STEM_COLOR)


class StemTile(QFrame):
    """Tuile draggable d'un stem (ou d'un mix) avec mini-lecteur (slider + temps).

    Drag = URL du fichier (vers le mixer, un autre outil ou l'exterieur).
    """

    playRequested = Signal(str)        # path (toggle play/pause)
    removeRequested = Signal(object)   # self
    artifactRequested = Signal(str)    # path -> envoyer aux artefacts
    seekRequested = Signal(str, float)  # path, pos_ms

    def __init__(
        self,
        name: str,
        path: str,
        *,
        removable: bool = False,
        artifactable: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._path = path
        self._press = None
        self._playing = False
        self.setObjectName("StemTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedHeight(40)
        self.setToolTip("Glisse cette piste vers le mixer, un autre outil ou l'exterieur")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 6, 4)
        row.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setObjectName("StemTileDot")
        self._label = QLabel(name)
        self._label.setObjectName("StemTileName")
        self._label.setMinimumWidth(52)
        self._label.setMaximumWidth(120)

        self._play = IconButton("player-play", tooltip="Ecouter", size="s")
        self._play.clicked.connect(lambda: self.playRequested.emit(self._path))

        self._slider = CustomSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("StemTileSlider")
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.sliderMoved.connect(self._on_slider_moved)

        self._time = QLabel("—")
        self._time.setObjectName("StemTileTime")
        self._time.setFixedWidth(38)
        self._time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(self._dot, 0)
        row.addWidget(self._label, 0)
        row.addWidget(self._play, 0)
        row.addWidget(self._slider, 1)
        row.addWidget(self._time, 0)
        if artifactable:
            self._art_btn = IconButton("file", tooltip="Envoyer aux artefacts", size="s")
            self._art_btn.clicked.connect(lambda: self.artifactRequested.emit(self._path))
            row.addWidget(self._art_btn, 0)
        if removable:
            self._rm_btn = IconButton("x", tooltip="Retirer", size="s")
            self._rm_btn.clicked.connect(lambda: self.removeRequested.emit(self))
            row.addWidget(self._rm_btn, 0)

        # Duree pour les bornes du slider + affichage.
        try:
            self._duration_ms = int(max(0.0, get_audio_duration(path)) * 1000) if path else 0
        except Exception:
            self._duration_ms = 0
        self._slider.setRange(0, max(1, self._duration_ms))
        self._slider.setValue(0)
        self._slider.setEnabled(self._duration_ms > 0)
        self._time.setText(_fmt_ms(self._duration_ms) if self._duration_ms > 0 else "—")

        self._apply_style()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_style())

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return self._name

    # -- Lecture (piloté par le timer de la session) ------------------------
    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if self._playing == playing:
            return
        self._playing = playing
        self._play.set_icon_name("player-pause" if playing else "player-play")
        if not playing:
            self._reset_position()

    def update_position(self, pos_ms: float) -> None:
        if self._duration_ms <= 0:
            return
        self._slider.blockSignals(True)
        self._slider.setValue(int(min(max(0.0, pos_ms), self._duration_ms)))
        self._slider.blockSignals(False)
        self._time.setText(_fmt_ms(pos_ms))

    def _reset_position(self) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._time.setText(_fmt_ms(self._duration_ms) if self._duration_ms > 0 else "—")

    def _on_slider_moved(self, value: int) -> None:
        self.seekRequested.emit(self._path, float(value))

    # -- Glisser la tuile ---------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        moved = (event.position().toPoint() - self._press).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press = None
        if not (self._path and os.path.isfile(self._path)):
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.DropAction.CopyAction)

    def _apply_style(self) -> None:
        p = theme.manager.p
        self._dot.setStyleSheet(f"color:{stem_color(self._name)}; font-size:12px;")
        self.setStyleSheet(
            f"""
            QFrame#StemTile {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QFrame#StemTile:hover {{ border-color: {p.BORDER_LIGHT}; }}
            QLabel#StemTileName {{ color: {p.TEXT}; font-size: 12px; font-weight: 600; }}
            QLabel#StemTileTime {{ color: {p.TEXT_MUTED}; font-size: 10px; }}
            QSlider#StemTileSlider {{ background: transparent; min-height: 16px; }}
            QSlider#StemTileSlider::groove:horizontal {{
                height: 3px; background: {p.BORDER}; border-radius: 1px;
            }}
            QSlider#StemTileSlider::sub-page:horizontal {{
                background: {p.ACCENT}; border-radius: 1px;
            }}
            QSlider#StemTileSlider::add-page:horizontal {{
                background: {p.BORDER}; border-radius: 1px;
            }}
            QSlider#StemTileSlider::handle:horizontal {{
                width: 9px; height: 9px; margin: -3px 0; border-radius: 4px;
                background: {p.TEXT};
            }}
            """
        )


class StemMixerZone(QFrame):
    """Zone de remix : on y glisse des stems, on preview, on obtient un mix."""

    mixRequested = Signal(list)      # paths a mixer
    playRequested = Signal(str)      # path a ecouter
    artifactRequested = Signal(str)  # path du mix -> artefacts
    seekRequested = Signal(str, float)  # path, pos_ms (mini-lecteur du mix)

    def __init__(self, sample_path_lookup=None, parent=None):
        super().__init__(parent)
        self._lookup = sample_path_lookup or (lambda _sid: None)
        self._paths: list[str] = []
        self._result: str | None = None
        self.setObjectName("StemMixer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Mixer")
        title.setObjectName("StemMixerTitle")
        self._preview_btn = IconButton("player-play", tooltip="Preview du mix", size="s")
        self._preview_btn.clicked.connect(lambda: self.mixRequested.emit(list(self._paths)))
        head.addWidget(title, 1)
        head.addWidget(self._preview_btn, 0)
        layout.addLayout(head)

        self._hint = QLabel("Glisse des stems ici pour les remixer ensemble.")
        self._hint.setObjectName("StemMixerHint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._chips_box = QVBoxLayout()
        self._chips_box.setContentsMargins(0, 0, 0, 0)
        self._chips_box.setSpacing(4)
        layout.addLayout(self._chips_box)

        self._result_box = QVBoxLayout()
        self._result_box.setContentsMargins(0, 0, 0, 0)
        self._result_box.setSpacing(4)
        layout.addLayout(self._result_box)

        self._apply_style()
        self._refresh_chips()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_style())

    def add_path(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        if not normalized or normalized in self._paths or not os.path.isfile(normalized):
            return
        self._paths.append(normalized)
        self._refresh_chips()

    def paths(self) -> list[str]:
        return list(self._paths)

    def set_result(self, path: str | None) -> None:
        self._result = path
        self._refresh_result()

    def _remove(self, path: str) -> None:
        if path in self._paths:
            self._paths.remove(path)
            self._refresh_chips()

    def _refresh_chips(self) -> None:
        while self._chips_box.count():
            item = self._chips_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for path in self._paths:
            self._chips_box.addWidget(self._make_chip(path))
        self._hint.setVisible(not self._paths)
        self._preview_btn.setEnabled(len(self._paths) >= 1)

    def _make_chip(self, path: str) -> "StemTile":
        # Meme card que les pistes separees (avec mini-lecteur), + bouton retirer.
        tile = StemTile(Path(path).stem, path, removable=True)
        tile.playRequested.connect(self.playRequested.emit)
        tile.seekRequested.connect(self.seekRequested.emit)
        tile.removeRequested.connect(lambda t: self._remove(t.path))
        return tile

    def _refresh_result(self) -> None:
        while self._result_box.count():
            item = self._result_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._result and os.path.isfile(self._result):
            tile = StemTile("mix", self._result, artifactable=True)
            tile.playRequested.connect(self.playRequested.emit)
            tile.artifactRequested.connect(self.artifactRequested.emit)
            tile.seekRequested.connect(self.seekRequested.emit)
            self._result_box.addWidget(tile)

    # -- Depots -------------------------------------------------------------
    def dragEnterEvent(self, event):  # noqa: N802
        mime = event.mimeData()
        if has_supported_audio_drop(mime) and can_accept_audio_drop(
            mime, sample_path_lookup=self._lookup
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802
        paths = resolve_audio_drop_paths(event.mimeData(), sample_path_lookup=self._lookup)
        if not paths:
            event.ignore()
            return
        for path in paths:
            self.add_path(path)
        event.acceptProposedAction()

    def _apply_style(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QFrame#StemMixer {{
                background: {p.BG_DARK};
                border: 1px dashed {p.BORDER};
                border-radius: 10px;
            }}
            QLabel#StemMixerTitle {{ color: {p.TEXT}; font-size: 12px; font-weight: 700; }}
            QLabel#StemMixerHint {{ color: {p.TEXT_MUTED}; font-size: 11px; }}
            QFrame#StemMixChip {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QLabel#StemMixChipName {{ color: {p.TEXT}; font-size: 11px; }}
            """
        )


class StemSessionWidget(QWidget):
    """Un onglet du separateur : un fichier source, ses 4 stems et le mixer."""

    artifactRequested = Signal(object)  # LabArtifact

    def __init__(self, app_context, source_path: str, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.source_path = normalize_audio_path(source_path)
        self._stem_dir = ""
        self.setObjectName("StemSession")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        self._status = QLabel("Separation en cours...")
        self._status.setObjectName("StemSessionStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        stems_title = QLabel("Pistes separees")
        stems_title.setObjectName("StemSessionSection")
        layout.addWidget(stems_title)
        self._stems_box = QVBoxLayout()
        self._stems_box.setContentsMargins(0, 0, 0, 0)
        self._stems_box.setSpacing(4)
        layout.addLayout(self._stems_box)

        self._mixer = StemMixerZone(sample_path_lookup=self._path_for_sample_id)
        self._mixer.mixRequested.connect(self._preview_mix)
        self._mixer.playRequested.connect(self._play)
        self._mixer.artifactRequested.connect(self._emit_mix_artifact)
        self._mixer.seekRequested.connect(self._seek)
        layout.addWidget(self._mixer, 0)
        # Absorbe l'espace vertical restant pour garder des elements compacts.
        layout.addStretch(1)

        self._apply_style()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_style())

        # Timer de synchro des mini-lecteurs (position / play-pause).
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(100)
        self._sync_timer.timeout.connect(self._sync_playback)
        self._sync_timer.start()

    # -- Etats de separation ------------------------------------------------
    def set_separating(self) -> None:
        self._status.setText("Separation en cours...")

    def set_failed(self, message: str) -> None:
        self._status.setText(f"Echec de la separation : {message}")

    def populate_stems(self, stem_dir: str) -> None:
        self._stem_dir = normalize_audio_path(stem_dir)
        while self._stems_box.count():
            item = self._stems_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        stem_files = [
            f for f in sorted(Path(self._stem_dir).glob("*.wav"))
            if not f.stem.startswith("mix_")
        ]
        for stem_file in stem_files:
            tile = StemTile(stem_file.stem, normalize_audio_path(str(stem_file)))
            tile.playRequested.connect(self._play)
            tile.seekRequested.connect(self._seek)
            self._stems_box.addWidget(tile)
        if stem_files:
            self._status.setText(
                "Pistes pretes. Glisse-les vers le mixer, un autre outil ou l'exterieur."
            )
        else:
            self._status.setText("Aucune piste produite.")

    # -- Lecture / mix ------------------------------------------------------
    @staticmethod
    def _sid(path: str) -> int:
        return hash(("stem-preview", path)) & 0x7FFFFFFF

    def _play(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            duration = float(get_audio_duration(path))
        except Exception:
            duration = 0.0
        self.app_context.audio_player.toggle_play(self._sid(path), path, duration)

    def _seek(self, path: str, pos_ms: float) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            duration = float(get_audio_duration(path))
        except Exception:
            duration = 0.0
        if duration <= 0:
            return
        try:
            self.app_context.audio_player.seek_position(
                self._sid(path), path, duration, pos_ms
            )
        except Exception:
            pass

    def _sync_playback(self) -> None:
        player = self.app_context.audio_player
        pos_ms = -1.0
        try:
            if player.is_playing and not getattr(player, "is_paused", False):
                raw = player.get_position()
                if raw >= 0:
                    pos_ms = float(raw)
        except Exception:
            pass
        current = os.path.normcase(
            os.path.normpath(getattr(player, "current_sample_path", "") or "")
        )
        for tile in self.findChildren(StemTile):
            is_this = bool(
                getattr(player, "is_playing", False)
                and current
                and current == os.path.normcase(os.path.normpath(tile.path))
            )
            tile.set_playing(is_this)
            if is_this and pos_ms >= 0:
                tile.update_position(pos_ms)

    def _preview_mix(self, paths: list[str]) -> None:
        valid = [p for p in (paths or []) if p and os.path.isfile(p)]
        if not valid:
            self._status.setText("Ajoute au moins une piste au mixer.")
            return
        temp_dir = Path(tempfile.gettempdir()) / "SampleRod" / "stem_mix"
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(temp_dir / f"mix_{Path(self.source_path).stem}_{uuid.uuid4().hex[:8]}.wav")
        try:
            mix_stem_files(valid, out_path)
        except Exception as exc:
            self._status.setText(f"Mix impossible : {exc}")
            return
        self._mixer.set_result(out_path)
        self._play(out_path)

    def _emit_mix_artifact(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            metadata = collect_audio_file_metadata(path, include_rms=False)
            duration = float(metadata.duration or 0.0)
        except Exception:
            duration = 0.0
        artifact = LabArtifact(
            artifact_id=f"stemmix::{path}",
            kind="stem",
            display_name=f"mix ({Path(self.source_path).stem})",
            source_path=self.source_path,
            temp_path=path,
            duration=duration,
            persisted=False,
            origin="stem_mixer",
            metadata={"workspace_dir": self._stem_dir},
        )
        self.artifactRequested.emit(artifact)

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

    def _apply_style(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#StemSession {{ background: {p.BG_MEDIUM}; }}
            QLabel#StemSessionStatus {{ color: {p.TEXT_MUTED}; font-size: 11px; }}
            QLabel#StemSessionSection {{ color: {p.TEXT}; font-size: 11px; font-weight: 700; }}
            """
        )
