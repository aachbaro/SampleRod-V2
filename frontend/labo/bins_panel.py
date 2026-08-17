# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le panneau des BINS (bacs) : des chips representant chacun un DOSSIER du
#   disque, pour trier la matiere audio a la volee sans ouvrir ces dossiers.
#   Utilise en colonne de droite du Labo classique ET comme module de
#   l'atelier modulaire.
# - Usage : on glisse n'importe quoi d'audio (slice, carte de sample,
#   fichier, artefact) sur un chip -> le fichier est DEPLACE dans le dossier
#   du bin. Double-clic : ouvrir dans la Reserve. Clic droit : menu complet.
#   Deposer un DOSSIER sur le panneau cree directement un bin.
# - La liste des bins est memorisee en JSON dans QSettings : on retrouve
#   ses bacs d'une session a l'autre (les dossiers disparus sont ignores).
#
# MISE EN PAGE (charte UI_MODERNIZATION.md)
# - Les chips sont poses dans un FlowLayout (frontend/ui/flow_layout.py) :
#   colonne quand le panneau est etroit, lignes/grille des que la fenetre du
#   module s'elargit — comme un flex wrap CSS, sans code de bascule.
# - Un seul texte par chip (le nom du bin) : ni titre "BIN" repete, ni nom
#   duplique en legende. Le reste (chemin, geste) passe en tooltip.
#
# CLASSES ET FONCTIONS (sommaire)
# - LaboBin (dataclass)   : un bin = id + etiquette + chemin du dossier.
# - BinChip (QWidget)     : le chip visuel d'un bin
#   - signaux : openInReserveRequested, removeRequested, moveHereRequested.
#   - drag*/dropEvent     : accepte le survol/depot des contenus supportes,
#     avec mise en evidence (bordure accent) pendant le survol.
#   - contextMenuEvent    : le menu clic-droit.
#   - _set_drop_active()/_refresh() : etat visuel et texte elide.
# - LaboBinsPanel (QWidget) : le panneau complet
#   - signaux : openInReserveRequested, reserveRefreshRequested,
#     sourcePathsMoved (pour que la Reserve se rafraichisse).
#   - set_title_visible()  : masque le titre interne quand la fenetre du
#     module l'affiche deja (evite la repetition).
#   - _choose_bin_folder()/add_bin()/_remove_bin() : gestion des bins.
#   - _load_bins()/_save_bins() : persistance JSON dans QSettings.
#   - _rebuild()          : reconstruit tous les chips.
#   - _on_move_here_requested() : LE coeur — traite un depot selon sa
#     nature : slice (audio brut a ecrire en WAV), carte de sample (deplace
#     via SampleService), fichiers (deplaces, ou via SampleService s'ils
#     sont deja suivis en base).
#   - _unique_target_path() : evite d'ecraser un fichier existant.
# - _has_supported_bin_drop() : le depot est-il acceptable ?
# - _dropped_folders()    : dossiers presents dans un depot (creation de bin).
# - _compact_label()      : etiquette raccourcie pour tenir dans le chip.
#
# LIENS CLES
# - frontend/labo/labo_widget.py : heberge ce panneau et relaie ses signaux.
# - frontend/modular/modules_setup.py : meme panneau en module "Bins".
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
from PySide6.QtGui import QDesktopServices, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import is_audio_file, normalize_audio_path
from frontend.labo.artifact_store import ensure_lab_artifact_store
from frontend.ui import IconButton, make_flow_container
from frontend.right_panel.composer.composer_dnd import has_sample_card, parse_sample_card_mime
from frontend.styles import theme
from frontend.dragdrop import DropAcceptance, DropAction, describe_drop, drag_controller


_BINS_SETTINGS_KEY = "labo_bins_v1"


@dataclass(slots=True)
class LaboBin:
    """Un bac de tri : identifiant, etiquette affichee, dossier cible."""

    bin_id: str
    label: str
    path: str


class BinChip(QWidget):
    """Le chip d'un bin : zone de depot + un seul texte + menu clic-droit."""

    openInReserveRequested = Signal(str)
    removeRequested = Signal(str)
    moveHereRequested = Signal(str, object)

    #: Taille fixe : le FlowLayout s'appuie dessus pour calculer les colonnes.
    CHIP_SIZE = (128, 52)

    def __init__(self, bin_data: LaboBin, parent=None):
        super().__init__(parent)
        self.bin_data = bin_data
        self._drop_active = False
        self.setObjectName("BinChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(*self.CHIP_SIZE)
        self._build_ui()
        self._refresh()
        self._drop_target_id = f"bin:{self.bin_data.bin_id}:{id(self)}"
        drag_controller().register_target(
            self._drop_target_id,
            self,
            lambda payload: DropAcceptance.accept(
                DropAction.MOVE_TO_BIN,
                f"{describe_drop(DropAction.MOVE_TO_BIN, payload)} dans {self.bin_data.label}",
            ),
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)

        self.name_label = QLabel("")
        self.name_label.setObjectName("BinChipLabel")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Police posee en code (pas en QSS) : QFontMetrics doit mesurer la
        # vraie police au moment de l'elision, avant tout polish de style.
        font = self.name_label.font()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        self.name_label.setFont(font)

        layout.addWidget(self.name_label)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-clic = ouvrir le dossier du bin dans la Reserve."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.openInReserveRequested.emit(self.bin_data.path)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event) -> None:
        self._handle_drag_enter(event)

    def dragMoveEvent(self, event) -> None:
        self._handle_drag_enter(event)

    def dragLeaveEvent(self, event) -> None:
        drag_controller().leave_target(self._drop_target_id)
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event) -> None:
        drag_controller().finish_drag()
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
        open_in_reserve = menu.addAction("Ouvrir dans la Reserve\tdouble-clic")
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
        drag_controller().enter_target(self._drop_target_id, event.mimeData())
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
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _refresh(self) -> None:
        """Un seul texte : le nom du bin, sur deux lignes max puis elide."""
        available = max(24, self.width() - 16)
        metrics = QFontMetrics(self.name_label.font())
        text = metrics.elidedText(
            _compact_label(self.bin_data.label),
            Qt.TextElideMode.ElideRight,
            available * 2 - 8,  # budget de deux lignes (le label est en wrap)
        )
        self.name_label.setText(text)
        tooltip = f"{self.bin_data.label}\n{self.bin_data.path}\nDeposer ici = deplacer"
        self.setToolTip(tooltip)


class LaboBinsPanel(QWidget):
    """Le panneau des bins : en-tete minimal + chips en flux adaptatif."""

    openInReserveRequested = Signal(str)
    reserveRefreshRequested = Signal()
    sourcePathsMoved = Signal(object)

    def __init__(self, app_context, settings, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.sample_store = app_context.sample_store
        self._qs = settings
        self._bins: list[LaboBin] = []
        self._chip_widgets: dict[str, BinChip] = {}
        self._build_ui()
        self._load_bins()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    # -- API publique -------------------------------------------------------
    def set_title_visible(self, visible: bool) -> None:
        """Masque le titre interne quand la fenetre du module l'affiche deja."""
        self.title_label.setVisible(bool(visible))

    def _build_ui(self) -> None:
        self.setObjectName("LaboBinsRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Pas de largeur max ici : c'est l'hote (colonne du Labo ou fenetre du
        # module) qui decide, et le flux passe en lignes des qu'il y a la place.
        self.setMinimumWidth(136)
        self.setAcceptDrops(True)
        self.setToolTip("Bacs de tri. Deposer un fichier = deplacer, deposer un dossier = nouveau bin.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title_label = QLabel("BINS")
        self.title_label.setObjectName("LaboBinsTitle")

        self.add_button = IconButton("plus", tooltip="Ajouter un bin a partir d'un dossier", size="s")
        self.add_button.setObjectName("LaboBinsAddButton")
        self.add_button.clicked.connect(self._choose_bin_folder)

        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.add_button)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("LaboBinsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("LaboBinsContent")
        self.content_layout = make_flow_container(self.content, margin=0, h_spacing=8, v_spacing=8)
        self.scroll.setWidget(self.content)

        # Indice affiche seulement quand il n'y a aucun bin (zero texte sinon).
        self.empty_label = QLabel("Deposer un dossier ici")
        self.empty_label.setObjectName("LaboBinsEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)

        layout.addLayout(header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll, 1)

        self._apply_styles()

    # -- Depot d'un dossier sur le panneau ----------------------------------
    def dragEnterEvent(self, event) -> None:
        self._handle_folder_drag(event)

    def dragMoveEvent(self, event) -> None:
        self._handle_folder_drag(event)

    def dropEvent(self, event) -> None:
        folders = _dropped_folders(event.mimeData())
        if not folders:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        for folder in folders:
            self.add_bin(folder)

    def _handle_folder_drag(self, event) -> None:
        if not _dropped_folders(event.mimeData()):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

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
        """Detruit tous les chips et les recree depuis la liste des bins."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._chip_widgets.clear()
        for bin_data in self._bins:
            chip = BinChip(bin_data, self.content)
            chip.openInReserveRequested.connect(self.openInReserveRequested.emit)
            chip.removeRequested.connect(self._remove_bin)
            chip.moveHereRequested.connect(self._on_move_here_requested)
            self.content_layout.addWidget(chip)
            self._chip_widgets[bin_data.bin_id] = chip
        self.empty_label.setVisible(not self._bins)

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

        artifact_store = ensure_lab_artifact_store(self.app_context, self)
        artifact_paths = artifact_store.paths_from_mime(mime)
        if artifact_paths and not mime.hasUrls():
            for src in artifact_paths:
                src = normalize_audio_path(src)
                if not src or not os.path.isfile(src) or not is_audio_file(src):
                    continue
                dest = self._unique_target_path(bin_data.path, os.path.basename(src))
                try:
                    shutil.move(src, dest)
                    changed = True
                    moved_source_paths.append(src)
                except Exception:
                    continue

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
                background: transparent;
                border: none;
            }}
            QLabel#LaboBinsTitle {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#LaboBinsEmpty {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                padding: 10px 4px;
            }}
            QScrollArea#LaboBinsScroll,
            QWidget#LaboBinsContent {{
                background: transparent;
                border: none;
            }}
            QWidget#BinChip {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
            }}
            QWidget#BinChip:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QWidget#BinChip[dropActive="true"] {{
                background: {p.BG_HOVER};
                border-color: {p.ACCENT};
            }}
            QLabel#BinChipLabel {{
                color: {p.TEXT};
                background: transparent;
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


def _dropped_folders(mime: QMimeData) -> list[str]:
    """Dossiers presents dans un depot (deposer un dossier = creer un bin)."""
    if not mime.hasUrls():
        return []
    folders: list[str] = []
    for url in mime.urls():
        path = url.toLocalFile()
        if path and os.path.isdir(path):
            folders.append(os.path.normpath(path))
    return folders


def _compact_label(text: str) -> str:
    """Raccourcit l'etiquette pour tenir dans la bulle (max 18 caracteres)."""
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "Bin"
    if len(cleaned) <= 18:
        return cleaned
    return cleaned[:15].rstrip() + "..."
