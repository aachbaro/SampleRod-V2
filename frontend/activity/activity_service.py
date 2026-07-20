# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le "registre" des taches de fond visibles par l'utilisateur : analyses de
#   gamme, normalisations, separations de stems, analyses de batterie...
# - Il ne lance AUCUNE tache lui-meme : il ECOUTE les signaux des services
#   backend et tient a jour une liste d'ActivityItem (en attente / en cours /
#   terminee / echouee) que le plateau (ActivityTrayWidget) affiche en bas
#   de la fenetre.
# - Les taches terminees restent visibles ~4 secondes puis sont purgees par
#   un petit timer. Un message "echo" (ex : "Gamme analysee : ...") est emis
#   a chaque fin de tache pour affichage furtif.
#
# CLASSES ET FONCTIONS (sommaire)
# - ActivityStatus (Enum) : PENDING / RUNNING / DONE / FAILED.
# - ActivityItem : une tache (uid unique, type, titre, fichier concerne,
#   statut, progression, detail, horodatages).
# - ActivityService (QObject)
#   - signaux : activityChanged (la liste a change), activityEcho (message).
#   - get_active()/get_recent()/active_count() : lectures pour le plateau.
#   - session_progress() : avancement global de la session (terminees/total).
#   - last_echo()        : dernier message furtif et sa date.
#   - _connect_signals()/_maybe_connect() : abonnements (tolerants) aux
#     signaux des services backend.
#   - _prune_recent_items() : purge les taches finies depuis > 4,4 s.
#   - _queue_item()/_start_item()/_update_progress()/_finish_item() :
#     cycle de vie d'une tache dans le registre.
#   - _sample_by_id()/_sample_filename()/_sample_scale_label()/_basename() :
#     fabrication des textes affiches.
#   - _on_scale_* / _on_normalization_* / _on_stem_* / _on_drum_* :
#     un trio queued/started/finished(+failed) par type de tache.
#
# LIENS CLES
# - frontend/activity/activity_tray.py : le widget qui affiche ce registre.
# - backend/services/* : les services dont on ecoute les signaux.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal


class ActivityStatus(Enum):
    """Les quatre etats possibles d'une tache de fond."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(slots=True)
class ActivityItem:
    """Une tache de fond telle qu'affichee dans le plateau d'activite.

    uid identifie la tache de maniere unique (ex : "scale::42") : si le meme
    travail est relance, il remplace l'ancienne entree au lieu d'en creer
    une nouvelle. kind sert a choisir l'icone, title/label les textes.
    """

    uid: str
    kind: str
    label: str
    title: str = ""
    status: ActivityStatus = ActivityStatus.PENDING
    progress: float = 0.0
    detail: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None


class ActivityService(QObject):
    activityChanged = Signal()
    activityEcho = Signal(str)

    # Duree d'affichage d'une tache terminee, et duree de retention avant
    # purge (legerement superieure pour laisser finir l'animation).
    RECENT_VISIBLE_SECONDS = 4.0
    RECENT_RETENTION_SECONDS = 4.4

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._items: dict[str, ActivityItem] = {}
        self._connections: list[tuple[object, object]] = []
        self._session_total = 0
        self._session_terminal = 0
        self._last_echo_message = ""
        self._last_echo_at: float | None = None

        self._prune_timer = QTimer(self)
        self._prune_timer.setInterval(400)
        self._prune_timer.timeout.connect(self._prune_recent_items)
        self._prune_timer.start()

        self._connect_signals()

    def shutdown(self) -> None:
        """Arrete le timer de purge et debranche tous les abonnements."""
        self._prune_timer.stop()
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._connections.clear()

    def get_active(self) -> list[ActivityItem]:
        """Taches en attente ou en cours (les "en cours" d'abord)."""
        return sorted(
            (
                item
                for item in self._items.values()
                if item.status in (ActivityStatus.PENDING, ActivityStatus.RUNNING)
            ),
            key=lambda item: (0 if item.status is ActivityStatus.RUNNING else 1, item.started_at),
        )

    def get_recent(self, n=5) -> list[ActivityItem]:
        """Les n dernieres taches terminees ou echouees (plus recentes d'abord)."""
        return sorted(
            (
                item
                for item in self._items.values()
                if item.status in (ActivityStatus.DONE, ActivityStatus.FAILED)
            ),
            key=lambda item: item.ended_at or 0.0,
            reverse=True,
        )[: max(0, int(n))]

    def active_count(self) -> int:
        """Nombre de taches actuellement actives."""
        return len(self.get_active())

    def session_progress(self) -> float:
        """Avancement global de la session : taches finies / taches lancees (0..1)."""
        if self._session_total <= 0:
            return 0.0
        return min(1.0, max(0.0, self._session_terminal / float(self._session_total)))

    def last_echo(self) -> tuple[str, float | None]:
        """Dernier message furtif emis et l'heure de son emission."""
        return self._last_echo_message, self._last_echo_at

    def _connect_signals(self) -> None:
        """S'abonne aux signaux de tous les services produisant des taches.

        Chaque abonnement passe par _maybe_connect : si un service ou un
        signal n'existe pas (version differente, service desactive), on
        l'ignore sans planter.
        """
        store = getattr(self.app_context, "sample_store", None)
        if store is not None:
            self._maybe_connect(store, "sampleStartedNormalization", self._on_normalization_started)
            self._maybe_connect(store, "sampleFinishedNormalization", self._on_normalization_done)
            self._maybe_connect(store, "sampleNormalizationFailed", self._on_normalization_failed)
            self._maybe_connect(store, "sampleScaleAnalyzed", self._on_scale_done)

            scale_service = getattr(store, "_scale_analysis", None)
            if scale_service is not None:
                self._maybe_connect(scale_service, "scaleAnalysisQueued", self._on_scale_queued)
                self._maybe_connect(scale_service, "scaleAnalysisStarted", self._on_scale_started)
                self._maybe_connect(scale_service, "scaleAnalysisFailed", self._on_scale_failed)

        stem = getattr(self.app_context, "stem_separator", None)
        if stem is not None:
            self._maybe_connect(stem, "fileQueued", self._on_stem_queued)
            self._maybe_connect(stem, "fileStarted", self._on_stem_started)
            self._maybe_connect(stem, "fileFinished", self._on_stem_finished)
            self._maybe_connect(stem, "fileFailed", self._on_stem_failed)

        drum = getattr(self.app_context, "drum_analysis", None)
        if drum is not None:
            self._maybe_connect(drum, "analysisStarted", self._on_drum_started)
            self._maybe_connect(drum, "analysisFinished", self._on_drum_finished)
            self._maybe_connect(drum, "analysisFailed", self._on_drum_failed)
            self._maybe_connect(drum, "reanalysisStarted", self._on_drum_reanalysis_started)
            self._maybe_connect(drum, "reanalysisFailed", self._on_drum_reanalysis_failed)
            self._maybe_connect(drum, "quantizeStarted", self._on_drum_quantize_started)
            self._maybe_connect(drum, "quantizeFinished", self._on_drum_quantize_finished)
            self._maybe_connect(drum, "quantizeFailed", self._on_drum_quantize_failed)

    def _maybe_connect(self, obj, signal_name: str, slot) -> None:
        """Connecte un signal s'il existe, et memorise la connexion.

        La liste _connections permet de tout debrancher au shutdown.
        """
        signal = getattr(obj, signal_name, None)
        if signal is None:
            return
        signal.connect(slot)
        self._connections.append((signal, slot))

    def _prune_recent_items(self) -> None:
        """Purge les taches terminees depuis plus de RECENT_RETENTION_SECONDS."""
        now = time.time()
        removed = False
        for uid, item in list(self._items.items()):
            if item.status not in (ActivityStatus.DONE, ActivityStatus.FAILED):
                continue
            ended_at = item.ended_at or item.started_at
            if now - ended_at < self.RECENT_RETENTION_SECONDS:
                continue
            self._items.pop(uid, None)
            removed = True
        if removed:
            self.activityChanged.emit()

    def _queue_item(self, uid: str, *, kind: str, title: str, label: str, detail: str = "") -> None:
        """Enregistre une tache "en attente" (ou reinitialise une ancienne).

        Si l'uid correspond a une tache deja finie, on la recycle : la meme
        operation relancee repart de zero au lieu de creer un doublon.
        """
        item = self._items.get(uid)
        now = time.time()
        if item is None or item.status in (ActivityStatus.DONE, ActivityStatus.FAILED):
            item = ActivityItem(
                uid=uid,
                kind=kind,
                title=title,
                label=label,
                status=ActivityStatus.PENDING,
                progress=0.0,
                detail=detail,
                started_at=now,
                ended_at=None,
            )
            self._items[uid] = item
            self._session_total += 1
        else:
            item.kind = kind
            item.title = title
            item.label = label
            item.status = ActivityStatus.PENDING
            item.progress = 0.0
            item.detail = detail
            item.started_at = now
            item.ended_at = None
        self.activityChanged.emit()

    def _start_item(self, uid: str, *, kind: str, title: str, label: str, detail: str = "") -> None:
        """Passe une tache a l'etat "en cours" (la cree si necessaire)."""
        item = self._items.get(uid)
        now = time.time()
        if item is None or item.status in (ActivityStatus.DONE, ActivityStatus.FAILED):
            item = ActivityItem(
                uid=uid,
                kind=kind,
                title=title,
                label=label,
                status=ActivityStatus.RUNNING,
                progress=0.0,
                detail=detail,
                started_at=now,
                ended_at=None,
            )
            self._items[uid] = item
            self._session_total += 1
        else:
            item.kind = kind
            item.title = title
            item.label = label
            item.status = ActivityStatus.RUNNING
            item.progress = 0.0
            item.detail = detail
            item.ended_at = None
        self.activityChanged.emit()

    def _update_progress(self, uid: str, progress: float) -> None:
        """Met a jour la progression (0..1) d'une tache en cours.

        Les variations infimes (< 0,1%) sont ignorees pour ne pas redessiner
        le plateau inutilement.
        """
        item = self._items.get(uid)
        if item is None or item.status in (ActivityStatus.DONE, ActivityStatus.FAILED):
            return
        value = min(1.0, max(0.0, float(progress)))
        if abs(item.progress - value) < 0.001:
            return
        item.progress = value
        self.activityChanged.emit()

    def _finish_item(
        self,
        uid: str,
        *,
        kind: str,
        title: str,
        label: str,
        detail: str = "",
        failed: bool = False,
        echo: str = "",
    ) -> None:
        """Termine une tache (succes ou echec) et emet l'echo eventuel.

        Le compteur de session (_session_terminal) n'est incremente que si
        la tache n'etait pas deja finie, pour que session_progress() reste
        exact meme si un service emet deux fois le meme signal de fin.
        """
        item = self._items.get(uid)
        now = time.time()
        if item is None:
            item = ActivityItem(
                uid=uid,
                kind=kind,
                title=title,
                label=label,
                status=ActivityStatus.RUNNING,
                progress=0.0,
                started_at=now,
            )
            self._items[uid] = item
            self._session_total += 1

        if item.status not in (ActivityStatus.DONE, ActivityStatus.FAILED):
            self._session_terminal += 1

        item.kind = kind
        item.title = title
        item.label = label
        item.status = ActivityStatus.FAILED if failed else ActivityStatus.DONE
        item.progress = 1.0
        item.detail = detail
        item.ended_at = now

        if echo:
            self._last_echo_message = echo
            self._last_echo_at = now
            self.activityEcho.emit(echo)

        self.activityChanged.emit()

    def _sample_by_id(self, sample_id: int):
        """Retrouve un sample dans le cache du SampleService (None si absent)."""
        store = getattr(self.app_context, "sample_store", None)
        if store is None:
            return None
        try:
            cached = store.get_cached()
        except Exception:
            return None
        for sample in cached:
            if int(getattr(sample, "id", -1)) == int(sample_id):
                return sample
        return None

    def _sample_filename(self, sample_id: int, fallback: str = "") -> str:
        """Nom de fichier affichable pour un sample (avec valeurs de repli)."""
        sample = self._sample_by_id(sample_id)
        if sample is not None:
            path = str(getattr(sample, "path", "") or "")
            if path:
                return os.path.basename(path)
            name = str(getattr(sample, "name", "") or "").strip()
            if name:
                return name
        return fallback or f"sample_{sample_id}"

    def _sample_scale_label(self, sample_id: int) -> str:
        """Texte de gamme a afficher pour l'echo de fin d'analyse.

        Ordre de preference : gamme principale detectee, sinon premiere
        gamme compatible (decodage du JSON), sinon note dominante.
        """
        sample = self._sample_by_id(sample_id)
        if sample is None:
            return ""

        detected = str(getattr(sample, "detected_scale_label", "") or "").strip()
        if detected:
            return detected

        compatible = getattr(sample, "compatible_scales", None)
        if isinstance(compatible, str) and compatible.strip():
            try:
                values = json.loads(compatible)
                if isinstance(values, list):
                    for value in values:
                        text = str(value or "").strip()
                        if text:
                            return text
            except Exception:
                pass

        dominant = str(getattr(sample, "dominant_note", "") or "").strip()
        return dominant

    @staticmethod
    def _basename(path: str, fallback: str = "") -> str:
        """Nom de fichier seul (sans dossier), ou fallback si chemin vide."""
        normalized = str(path or "").strip()
        if normalized:
            return os.path.basename(normalized)
        return fallback

    # ------------------------------------------------------------------
    # Relais des signaux backend -> registre.
    # Chaque type de tache suit le meme schema : queued (en attente),
    # started (en cours), done/finished (succes + echo), failed (echec + echo).
    # ------------------------------------------------------------------
    def _on_scale_queued(self, sample_id: int, path: str) -> None:
        label = self._basename(path, self._sample_filename(sample_id))
        self._queue_item(
            f"scale::{sample_id}",
            kind="scale",
            title="Analyse gamme",
            label=label,
        )

    def _on_scale_started(self, sample_id: int, path: str) -> None:
        label = self._basename(path, self._sample_filename(sample_id))
        self._start_item(
            f"scale::{sample_id}",
            kind="scale",
            title="Analyse gamme",
            label=label,
        )

    def _on_scale_done(self, sample_id: int) -> None:
        label = self._sample_filename(sample_id)
        scale_name = self._sample_scale_label(sample_id)
        echo = f"Gamme analysee : {scale_name} - {label}" if scale_name else f"Gamme analysee : {label}"
        self._finish_item(
            f"scale::{sample_id}",
            kind="scale",
            title="Analyse gamme",
            label=label,
            detail=scale_name,
            echo=echo,
        )

    def _on_scale_failed(self, sample_id: int, reason: str) -> None:
        label = self._sample_filename(sample_id)
        self._finish_item(
            f"scale::{sample_id}",
            kind="scale",
            title="Analyse gamme",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec analyse gamme : {label}",
        )

    def _on_normalization_started(self, sample_id: int) -> None:
        self._start_item(
            f"normalize::{sample_id}",
            kind="normalize",
            title="Normalisation",
            label=self._sample_filename(sample_id),
        )

    def _on_normalization_done(self, sample_id: int) -> None:
        label = self._sample_filename(sample_id)
        self._finish_item(
            f"normalize::{sample_id}",
            kind="normalize",
            title="Normalisation",
            label=label,
            echo=f"Normalisation terminee : {label}",
        )

    def _on_normalization_failed(self, sample_id: int, reason: str) -> None:
        label = self._sample_filename(sample_id)
        self._finish_item(
            f"normalize::{sample_id}",
            kind="normalize",
            title="Normalisation",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec normalisation : {label}",
        )

    def _on_stem_queued(self, path: str) -> None:
        label = self._basename(path, "stem.wav")
        self._queue_item(
            f"stem::{path}",
            kind="stem",
            title="Separation stems",
            label=label,
        )

    def _on_stem_started(self, path: str) -> None:
        label = self._basename(path, "stem.wav")
        self._start_item(
            f"stem::{path}",
            kind="stem",
            title="Separation stems",
            label=label,
        )

    def _on_stem_finished(self, path: str, stem_dir: str) -> None:
        label = self._basename(path, "stem.wav")
        self._finish_item(
            f"stem::{path}",
            kind="stem",
            title="Separation stems",
            label=label,
            detail=stem_dir,
            echo=f"Stems prets : {label}",
        )

    def _on_stem_failed(self, path: str, reason: str) -> None:
        label = self._basename(path, "stem.wav")
        self._finish_item(
            f"stem::{path}",
            kind="stem",
            title="Separation stems",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec separation stems : {label}",
        )

    def _on_drum_started(self, path: str) -> None:
        label = self._basename(path, "break.wav")
        self._start_item(
            f"drum::{path}",
            kind="drum",
            title="Analyse batterie",
            label=label,
        )

    def _on_drum_finished(self, result) -> None:
        path = str(getattr(result, "source_path", "") or "")
        uid = f"drum::{path}"
        item = self._items.get(uid)
        title = item.title if item is not None and item.title else "Analyse batterie"
        label = self._basename(path, "break.wav")
        self._finish_item(
            uid,
            kind="drum",
            title=title,
            label=label,
            echo=f"{title} terminee : {label}",
        )

    def _on_drum_failed(self, path: str, reason: str) -> None:
        label = self._basename(path, "break.wav")
        self._finish_item(
            f"drum::{path}",
            kind="drum",
            title="Analyse batterie",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec analyse batterie : {label}",
        )

    def _on_drum_reanalysis_started(self, path: str) -> None:
        label = self._basename(path, "break.wav")
        self._start_item(
            f"drum::{path}",
            kind="drum",
            title="Re-analyse batterie",
            label=label,
        )

    def _on_drum_reanalysis_failed(self, path: str, reason: str) -> None:
        label = self._basename(path, "break.wav")
        self._finish_item(
            f"drum::{path}",
            kind="drum",
            title="Re-analyse batterie",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec re-analyse batterie : {label}",
        )

    def _on_drum_quantize_started(self, path: str) -> None:
        label = self._basename(path, "break.wav")
        self._start_item(
            f"drum-quantize::{path}",
            kind="drum",
            title="Preview quantizee",
            label=label,
        )

    def _on_drum_quantize_finished(self, preview) -> None:
        path = str(getattr(preview, "source_path", "") or "")
        label = self._basename(path, "break.wav")
        self._finish_item(
            f"drum-quantize::{path}",
            kind="drum",
            title="Preview quantizee",
            label=label,
            echo=f"Preview quantizee prete : {label}",
        )

    def _on_drum_quantize_failed(self, path: str, reason: str) -> None:
        label = self._basename(path, "break.wav")
        self._finish_item(
            f"drum-quantize::{path}",
            kind="drum",
            title="Preview quantizee",
            label=label,
            detail=str(reason or ""),
            failed=True,
            echo=f"Echec preview quantizee : {label}",
        )
