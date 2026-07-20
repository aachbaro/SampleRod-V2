# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le panneau des BINS (bacs), colonne de droite de l'onglet Labo : des
#   bulles rondes representant chacune un DOSSIER du disque, pour trier la
#   matiere audio a la volee sans ouvrir ces dossiers.
# - Usage : on glisse n'importe quoi d'audio (slice, carte de sample,
#   fichier, artefact) sur une bulle -> le fichier est DEPLACE dans le
#   dossier du bin. Clic droit sur une bulle : ouvrir dans la Reserve,
#   ouvrir dans l'explorateur, retirer le bin.
# - La liste des bins est memorisee en JSON dans QSettings : on retrouve
#   ses bacs d'une session a l'autre (les dossiers disparus sont ignores).
#
# CLASSES ET FONCTIONS (sommaire)
# - LaboBin (dataclass)   : un bin = id + etiquette + chemin du dossier.
# - BinBubble (QWidget)   : la bulle visuelle d'un bin
#   - signaux : openInReserveRequested, removeRequested, moveHereRequested.
#   - drag*/dropEvent     : accepte le survol/depot des contenus supportes,
#     avec mise en evidence (bordure bleue) pendant le survol.
#   - contextMenuEvent    : le menu clic-droit.
#   - _set_drop_active()/_refresh() : etat visuel et textes.
# - LaboBinsPanel (QWidget) : la colonne complete
#   - signaux : openInReserveRequested, reserveRefreshRequested,
#     sourcePathsMoved (pour que la Reserve se rafraichisse).
#   - _choose_bin_folder()/add_bin()/_remove_bin() : gestion des bins.
#   - _load_bins()/_save_bins() : persistance JSON dans QSettings.
#   - _rebuild()          : reconstruit toutes les bulles.
#   - _on_move_here_requested() : LE coeur — traite un depot selon sa
#     nature : slice (audio brut a ecrire en WAV), carte de sample (deplace
#     via SampleService), fichiers (deplaces, ou via SampleService s'ils
#     sont deja suivis en base).
#   - _unique_target_path() : evite d'ecraser un fichier existant.
# - _has_supported_bin_drop() : le depot est-il acceptable ?
# - _compact_label()      : etiquette raccourcie pour tenir dans la bulle.
#
# LIENS CLES
# - frontend/labo/labo_widget.py : heberge ce panneau et relaie ses signaux.
# - backend/services/sample_service.py : deplacements de samples suivis.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import pickle
import shutil
import uuid
from dataclasses import asdict, dataclass

import numpy as np
import soundfile as sf

from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import is_audio_file, normalize_audio_path
from frontend.right_panel.composer.composer_dnd import has_sample_card, parse_sample_card_mime
from frontend.styles import theme


_BINS_SETTINGS_KEY = "labo_bins_v1"


@dataclass(slots=True)
class LaboBin:
    """Un bac de tri : identifiant, etiquette affichee, dossier cible."""

    bin_id: str
    label: str
    path: str


class BinBubble(QWidget):
    """La bulle ronde d'un bin : zone de depot + menu clic-droit."""

    openInReserveRequested = Signal(str)
    removeRequested = Signal(str)
    moveHereRequested = Signal(str, object)

    def __init__(self, bin_data: LaboBin, parent=None):
        super().__init__(parent)
        self.bin_data = bin_data
        self._drop_active = False
        self.setObjectName("BinBubbleRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.circle = QWidget()
        self.circle.setObjectName("BinBubbleCircle")
        self.circle.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.circle.setMinimumSize(94, 94)
        self.circle.setMaximumSize(94, 94)

        circle_layout = QVBoxLayout(self.circle)
        circle_layout.setContentsMargins(10, 10, 10, 10)
        circle_layout.setSpacing(4)

        self.circle_title = QLabel("BIN")
        self.circle_title.setObjectName("BinBubbleTitle")
        self.circle_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.circle_label = QLabel("")
        self.circle_label.setObjectName("BinBubbleLabel")
        self.circle_label.setWordWrap(True)
        self.circle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        circle_layout.addStretch(1)
        circle_layout.addWidget(self.circle_title)
        circle_layout.addWidget(self.circle_label)
        circle_layout.addStretch(1)

        self.footer_label = QLabel("")
        self.footer_label.setObjectName("BinBubbleFooter")
        self.footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer_label.setWordWrap(True)

        layout.addWidget(self.circle, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.footer_label)

    def dragEnterEvent(self, event) -> None:
        self._handle_drag_enter(event)

    def dragMoveEvent(self, event) -> None:
        self._handle_drag_enter(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event) -> None:
        if not _has_supported_bin_drop(event.mimeData()):
            self._set_drop_active(False)
            event.ignore()
            return
        self._set_drop_active(False)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.moveHereRequested.emit(self.bin_data.bin_id, event.mimeData())

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        open_in_reserve = menu.addAction("Ouvrir dans la Reserve")
        open_in_explorer = menu.addAction("Ouvrir le dossier")
        menu.addSeparator()
        remove_bin = menu.addAction("Retirer ce bin")
        action = menu.exec(event.globalPos())
        if action is open_in_reserve:
            self.openInReserveRequested.emit(self.bin_data.path)
        elif action is open_in_explorer:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.bin_data.path))
        elif action is remove_bin:
            self.removeRequested.emit(self.bin_data.bin_id)

    def _handle_drag_enter(self, event) -> None:
        if not _has_supported_bin_drop(event.mimeData()):
            self._set_drop_active(False)
            event.ignore()
            return
        self._set_drop_active(True)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def _set_drop_active(self, active: bool) -> None:
        """Allume/eteint la mise en evidence pendant le survol d'un drag.

        La propriete Qt "dropActive" est lue par la feuille de style ;
        unpolish/polish force Qt a reappliquer le style apres changement.
        """
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.circle.setProperty("dropActive", active)
        self.circle.style().unpolish(self.circle)
        self.circle.style().polish(self.circle)

    def _refresh(self) -> None:
        self.circle_label.setText(_compact_label(self.bin_data.label))
        self.footer_label.setText(self.bin_data.label)
        tooltip = f"{self.bin_data.label}\n{self.bin_data.path}\nDrop = move"
        self.setToolTip(tooltip)
        self.circle.setToolTip(tooltip)
        self.footer_label.setToolTip(tooltip)


class LaboBinsPanel(QWidget):
    """La colonne des bins : en-tete, bouton +, et pile de bulles."""

    openInReserveRequested = Signal(str)
    reserveRefreshRequested = Signal()
    sourcePathsMoved = Signal(object)

    def __init__(self, app_context, settings, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.sample_store = app_context.sample_store
        self._qs = settings
        self._bins: list[LaboBin] = []
        self._bubble_widgets: dict[str, BinBubble] = {}
        self._build_ui()
        self._load_bins()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("LaboBinsRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(152)
        self.setMaximumWidth(188)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title_label = QLabel("Bins")
        self.title_label.setObjectName("LaboBinsTitle")
        self.title_label.setToolTip("Repartiteur rapide de matiere. Drop = move.")

        self.add_button = QPushButton("+")
        self.add_button.setObjectName("LaboBinsAddButton")
        self.add_button.setFixedSize(24, 24)
        self.add_button.setToolTip("Ajouter un bin a partir d'un dossier")
        self.add_button.clicked.connect(self._choose_bin_folder)

        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.add_button)

        self.subtitle_label = QLabel("Tri rapide sans afficher le contenu.")
        self.subtitle_label.setObjectName("LaboBinsSubtitle")
        self.subtitle_label.setWordWrap(True)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("LaboBinsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.content = QWidget()
        self.content.setObjectName("LaboBinsContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.addStretch(1)
        self.scroll.setWidget(self.content)

        layout.addLayout(header)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.scroll, 1)

        self._apply_styles()

    def _choose_bin_folder(self) -> None:
        """Bouton + : choisir un dossier du disque pour creer un bin."""
        start_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier pour le bin", start_dir)
        if folder:
            self.add_bin(folder)

    def add_bin(self, folder: str) -> None:
        """Cree un bin pour ce dossier (refuse les doublons et dossiers absents)."""
        normalized = normalize_audio_path(folder)
        if not os.path.isdir(normalized):
            return
        for bin_data in self._bins:
            if os.path.normcase(bin_data.path) == os.path.normcase(normalized):
                return
        bin_data = LaboBin(
            bin_id=uuid.uuid4().hex,
            label=os.path.basename(normalized) or normalized,
            path=normalized,
        )
        self._bins.append(bin_data)
        self._save_bins()
        self._rebuild()

    def _remove_bin(self, bin_id: str) -> None:
        """Retire un bin de la liste (le dossier lui-meme n'est pas touche)."""
        self._bins = [bin_data for bin_data in self._bins if bin_data.bin_id != bin_id]
        self._save_bins()
        self._rebuild()

    def _load_bins(self) -> None:
        """Recharge les bins memorises (JSON dans QSettings), en filtrant
        ceux dont le dossier n'existe plus."""
        raw = self._qs.value(_BINS_SETTINGS_KEY, "", type=str)
        bins: list[LaboBin] = []
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                payload = []
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    path = normalize_audio_path(str(item.get("path", "") or ""))
                    if not path or not os.path.isdir(path):
                        continue
                    bins.append(
                        LaboBin(
                            bin_id=str(item.get("bin_id") or uuid.uuid4().hex),
                            label=str(item.get("label") or os.path.basename(path) or path),
                            path=path,
                        )
                    )
        self._bins = bins
        self._rebuild()

    def _save_bins(self) -> None:
        """Sauvegarde la liste des bins en JSON dans QSettings."""
        self._qs.setValue(_BINS_SETTINGS_KEY, json.dumps([asdict(bin_data) for bin_data in self._bins]))

    def _rebuild(self) -> None:
        """Detruit toutes les bulles et les recree depuis la liste des bins."""
        while self.content_layout.count() > 1:
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._bubble_widgets.clear()
        for bin_data in self._bins:
            bubble = BinBubble(bin_data, self.content)
            bubble.openInReserveRequested.connect(self.openInReserveRequested.emit)
            bubble.removeRequested.connect(self._remove_bin)
            bubble.moveHereRequested.connect(self._on_move_here_requested)
            self.content_layout.insertWidget(self.content_layout.count() - 1, bubble)
            self._bubble_widgets[bin_data.bin_id] = bubble

    def _on_move_here_requested(self, bin_id: str, mime: QMimeData) -> None:
        """Traite un depot sur un bin, selon la nature du contenu.

        Trois cas, dans l'ordre :
        1. une SLICE (audio brut decoupe dans l'editeur) : ecrite en WAV
           dans le dossier du bin et ajoutee au catalogue ;
        2. une CARTE de sample suivi en base : deplacement via SampleService
           (qui met la base a jour en meme temps que le fichier) ;
        3. des FICHIERS (urls) : ceux deja suivis en base passent par
           SampleService, les autres sont simplement deplaces sur le disque
           (et la Reserve est prevenue via sourcePathsMoved).
        """
        bin_data = next((item for item in self._bins if item.bin_id == bin_id), None)
        if bin_data is None:
            return
        changed = False
        moved_source_paths: list[str] = []

        # ── Slice depuis la marker list (audio numpy brut) ─────────────────
        if mime.hasFormat(_MIME_SLICE):
            try:
                payload = pickle.loads(bytes(mime.data(_MIME_SLICE)))
                audio = np.asarray(payload["audio_data"], dtype="float32")
                sr = int(payload.get("sample_rate") or 44100)
                base = os.path.splitext(os.path.basename(payload.get("name") or "slice"))[0]
                target = self._unique_target_path(bin_data.path, f"{base}_slice.wav")
                sf.write(target, audio, sr)
                self.sample_store.add(target)
                changed = True
            except Exception:
                pass
            if changed:
                self.reserveRefreshRequested.emit()
            return

        # ── Sample card trackée en DB ──────────────────────────────────────
        if has_sample_card(mime):
            try:
                payload = parse_sample_card_mime(mime)
                self.sample_store.move(int(payload["sample_id"]), bin_data.path)
                changed = True
            except Exception:
                pass
            if changed:
                return

        if mime.hasUrls():
            for url in mime.urls():
                src = normalize_audio_path(url.toLocalFile())
                if not src or not os.path.isfile(src) or not is_audio_file(src):
                    continue
                tracked = next(
                    (
                        sample for sample in self.sample_store.get_cached()
                        if os.path.normcase(getattr(sample, "path", "") or "") == os.path.normcase(src)
                    ),
                    None,
                )
                if tracked is not None:
                    self.sample_store.move(int(tracked.id), bin_data.path)
                    changed = True
                    continue

                dest = self._unique_target_path(bin_data.path, os.path.basename(src))
                try:
                    shutil.move(src, dest)
                    changed = True
                    moved_source_paths.append(src)
                except Exception:
                    continue

        if moved_source_paths:
            self.sourcePathsMoved.emit(list(moved_source_paths))

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
            QWidget#LaboBinsRoot {{
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#LaboBinsTitle {{
                color: {p.TEXT};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#LaboBinsSubtitle,
            QLabel#BinBubbleFooter {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QPushButton#LaboBinsAddButton {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 12px;
                font-size: 14px;
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#LaboBinsAddButton:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QScrollArea#LaboBinsScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#BinBubbleCircle {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 47px;
            }}
      QWidget#BinBubbleCircle[dropActive="true"] {{
                background: {p.BG_HOVER};
                border-color: {p.INFO};
            }}
            QLabel#BinBubbleTitle {{
                color: {p.TEXT_MUTED};
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#BinBubbleLabel {{
                color: {p.TEXT};
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )



# Format MIME "maison" d'une slice (audio brut transporte dans le drag).
_MIME_SLICE = "application/x-sample-slice-data"


def _has_supported_bin_drop(mime: QMimeData) -> bool:
    """Le contenu glisse est-il acceptable par un bin ? (carte/slice/audio)."""
    if has_sample_card(mime):
        return True
    if mime.hasFormat(_MIME_SLICE):
        return True
    if not mime.hasUrls():
        return False
    for url in mime.urls():
        path = url.toLocalFile()
        if path and is_audio_file(path):
            return True
    return False


def _compact_label(text: str) -> str:
    """Raccourcit l'etiquette pour tenir dans la bulle (max 18 caracteres)."""
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "Bin"
    if len(cleaned) <= 18:
        return cleaned
    return cleaned[:15].rstrip() + "..."
