# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Definit le type central ReserveEntry et toutes les fonctions utilitaires
#   qui lui sont liees : creation, filtrage, formatage du statut.
# - ReserveEntry est le "langage commun" entre les trois onglets de la Reserve
#   (Dossiers, Historique, Indexe) : chacun produit des ReserveEntry, et les
#   widgets UI n'ont besoin de connaitre que ce type.
#
# Statuts possibles (ordre de gravite croissant) :
#   normal          -> sample indexe, fichier present, analyse OK
#   non_indexed     -> fichier present mais pas encore indexe
#   needs_analysis  -> indexe mais la detection de gamme n'a pas encore tourne
#   missing         -> chemin enregistre mais fichier introuvable sur disque
#
# FONCTIONS (sommaire)
# - ReserveEntry                    : dataclass avec 18 champs
# - resolve_reserve_status()        : deduit le statut depuis 3 booleens
# - reserve_status_label/tone()     : label lisible et "ton" (neutral/info/warning/error)
# - reserve_status_badge_stylesheet() : QSS inline pour un badge de statut
# - apply_status_badge()            : applique texte + style sur un QLabel
# - reserve_entry_matches_query()   : filtre textuel multi-champs
# - reserve_entry_matches_status()  : filtre par statut
# - reserve_entry_from_sample()     : cree un ReserveEntry depuis un sample ORM
# - reserve_entry_from_directory()  : cree un ReserveEntry depuis DirectoryAudioEntry
# - _normalize_compatible_scales()  : normalise les gammes compat (str/list/JSON)
#
# LIENS CLES
# - backend/models/sample.py              : modele ORM source
# - backend/services/directory_service.py : DirectoryAudioEntry source
# - frontend/reserve/__init__.py          : re-exporte tout vers l'exterieur
# -----------------------------------------------------------------------------

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.services.directory_service import DirectoryAudioEntry
from frontend.styles import theme
from .reserve_capabilities import ReserveCapabilities, reserve_capabilities_for
from .reserve_status import (
    ReserveTechnicalStatus,
    STATUS_LABELS,
    STATUS_TONES,
    reserve_technical_status_label,
    reserve_technical_status_tone,
)

ReserveSourceKind = Literal["filesystem", "history", "indexed"]

# Alias chaîne historiques : leur type et leur valeur restent inchangés.
STATUS_NORMAL = ReserveTechnicalStatus.NORMAL.value
STATUS_NON_INDEXED = ReserveTechnicalStatus.NON_INDEXED.value
STATUS_NEEDS_ANALYSIS = ReserveTechnicalStatus.NEEDS_ANALYSIS.value
STATUS_MISSING = ReserveTechnicalStatus.MISSING.value
STATUS_ALL = "all"

STATUS_ORDER = [
    STATUS_NORMAL,
    STATUS_NON_INDEXED,
    STATUS_NEEDS_ANALYSIS,
    STATUS_MISSING,
]

SOURCE_LABELS = {
    "filesystem": "Dossiers",
    "history": "Récents",
    "indexed": "Indexe",
}


@dataclass(slots=True)
class ReserveEntry:
    """Representation unifiee d'un sample dans la Reserve, quelle que soit sa source.

    Champs principaux :
        source_kind     : d'ou vient l'entree ("filesystem", "history", "indexed").
        path            : chemin absolu sur disque (peut ne plus exister si missing=True).
        sample_id       : ID en base SQLite si le sample est indexe, sinon None.
        status          : etat du sample (STATUS_NORMAL / NON_INDEXED / NEEDS_ANALYSIS / MISSING).
        missing         : True si le fichier est introuvable sur disque.
        indexed         : True si le sample est enregistre dans la base.
        compatible_scales : tuple des gammes musicalement compatibles avec ce sample.
    """
    source_kind: ReserveSourceKind
    path: str
    sample_id: int | None = None
    display_name: str = ""
    root_path: str | None = None
    folder_path: str | None = None
    created_at: dt.datetime | None = None
    duration: float | None = None
    rms_level: float | None = None
    status: ReserveTechnicalStatus | str = ReserveTechnicalStatus.NORMAL
    needs_analysis: bool = False
    missing: bool = False
    indexed: bool = False
    dominant_note: str | None = None
    detected_scale_label: str | None = None
    detected_scale_kind: str | None = None
    scale_confidence: float | None = None
    compatible_scales: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def status_label(self) -> str:
        return reserve_status_label(self.status)

    @property
    def capabilities(self) -> ReserveCapabilities:
        return reserve_capabilities_for(self)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source_kind, self.source_kind)

    @property
    def folder_name(self) -> str:
        folder = self.folder_path or os.path.dirname(self.path)
        return os.path.basename(folder) or folder

    @property
    def root_name(self) -> str:
        if self.root_path:
            return os.path.basename(self.root_path) or self.root_path
        return self.source_label


def resolve_reserve_status(
    *, indexed: bool, missing: bool, needs_analysis: bool
) -> ReserveTechnicalStatus:
    """Deduit le statut a partir de trois booleens (ordre de priorite : missing > not indexed > needs_analysis)."""
    if missing:
        return ReserveTechnicalStatus.MISSING
    if not indexed:
        return ReserveTechnicalStatus.NON_INDEXED
    if needs_analysis:
        return ReserveTechnicalStatus.NEEDS_ANALYSIS
    return ReserveTechnicalStatus.NORMAL


def reserve_status_label(status: ReserveTechnicalStatus | str) -> str:
    """Alias historique vers le formateur du statut technique."""
    return reserve_technical_status_label(status)


def reserve_status_tone(status: ReserveTechnicalStatus | str) -> str:
    """Alias historique vers le ton du statut technique."""
    return reserve_technical_status_tone(status)


def reserve_status_badge_stylesheet(status: str) -> str:
    """Retourne une chaine QSS inline pour colorer un QLabel badge selon le statut."""
    p = theme.manager.p
    tone = reserve_status_tone(status)
    fg = p.TEXT
    border = p.BORDER_LIGHT
    bg = p.BG_CARD
    if tone == "warning":
        fg = p.WARNING
        border = p.WARNING
    elif tone == "error":
        fg = p.ERROR
        border = p.ERROR
    elif tone == "info":
        fg = p.INFO
        border = p.INFO
    elif tone == "neutral":
        fg = p.TEXT_MUTED
        border = p.BORDER_LIGHT

    return (
        "QLabel {"
        f"color: {fg};"
        "font-size: 11px;"
        "font-weight: 600;"
        f"background: {bg};"
        f"border: 1px solid {border};"
        "border-radius: 10px;"
        "padding: 3px 8px;"
        "}"
    )


def apply_status_badge(label_widget, status: str) -> None:
    """Applique le texte et le style de badge de statut sur un QLabel."""
    label_widget.setText(reserve_status_label(status))
    label_widget.setStyleSheet(reserve_status_badge_stylesheet(status))
    status_value = str(getattr(status, "value", status)).strip().lower()
    label_widget.setVisible(status_value != "normal")


def reserve_entry_matches_query(entry: ReserveEntry, query: str) -> bool:
    """Retourne True si l'entree correspond a la recherche textuelle.

    Cherche chaque mot de la requete (en minuscules) dans un "haystack" qui
    combine nom, chemin, dossier, racine, source, statut, note et gamme detectee.
    Une requete vide retourne toujours True.
    """
    needle = " ".join((query or "").strip().lower().split())
    if not needle:
        return True

    haystack = " ".join(
        part.lower()
        for part in [
            entry.display_name,
            entry.path,
            entry.folder_path or "",
            entry.root_path or "",
            entry.source_label,
            entry.status_label,
            entry.dominant_note or "",
            entry.detected_scale_label or "",
            " ".join(entry.compatible_scales),
        ]
        if part
    )
    return all(token in haystack for token in needle.split(" "))


def reserve_entry_matches_status(entry: ReserveEntry, status_filter: str) -> bool:
    """Retourne True si le statut de l'entree correspond au filtre (ou si filtre = 'all')."""
    if not status_filter or status_filter == STATUS_ALL:
        return True
    return entry.status == status_filter


def reserve_entry_from_sample(
    sample,
    *,
    source_kind: ReserveSourceKind,
    root_path: str | None = None,
    folder_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReserveEntry:
    """Cree un ReserveEntry a partir d'un objet Sample ORM.

    source_kind vaut "indexed" pour les samples de la bibliotheque ou
    "history" pour ceux de l'historique recents.
    """
    path = getattr(sample, "path", "")
    missing = bool(getattr(sample, "missing", False))
    needs_analysis = bool(getattr(sample, "needs_analysis", False))
    sample_metadata = getattr(sample, "material_metadata_dict", {})
    if callable(sample_metadata):
        sample_metadata = sample_metadata()
    merged_metadata = dict(sample_metadata or {})
    merged_metadata.update(metadata or {})
    return ReserveEntry(
        source_kind=source_kind,
        path=path,
        sample_id=int(getattr(sample, "id", 0)) if getattr(sample, "id", None) is not None else None,
        display_name=str(getattr(sample, "name", os.path.splitext(os.path.basename(path))[0])),
        root_path=root_path,
        folder_path=folder_path or os.path.dirname(path),
        created_at=getattr(sample, "created_at", None),
        duration=float(getattr(sample, "duration", 0.0) or 0.0),
        rms_level=(
            float(getattr(sample, "rms_level", 0.0))
            if getattr(sample, "rms_level", None) is not None
            else None
        ),
        status=resolve_reserve_status(indexed=True, missing=missing, needs_analysis=needs_analysis),
        needs_analysis=needs_analysis,
        missing=missing,
        indexed=True,
        dominant_note=str(getattr(sample, "dominant_note", "") or "").strip() or None,
        detected_scale_label=str(getattr(sample, "detected_scale_label", "") or "").strip() or None,
        detected_scale_kind=str(getattr(sample, "detected_scale_kind", "") or "").strip() or None,
        scale_confidence=(
            float(getattr(sample, "scale_confidence", 0.0))
            if getattr(sample, "scale_confidence", None) is not None
            else None
        ),
        compatible_scales=_normalize_compatible_scales(getattr(sample, "compatible_scales", None)),
        metadata=merged_metadata,
    )


def reserve_entry_from_directory(entry: DirectoryAudioEntry) -> ReserveEntry:
    """Cree un ReserveEntry a partir d'une entree du service de navigation de dossiers."""
    return ReserveEntry(
        source_kind="filesystem",
        path=entry.path,
        sample_id=entry.sample_id,
        display_name=entry.name,
        folder_path=os.path.dirname(entry.path),
        created_at=entry.created_at,
        duration=entry.duration,
        rms_level=entry.rms_level,
        status=resolve_reserve_status(
            indexed=entry.indexed,
            missing=entry.missing,
            needs_analysis=entry.needs_analysis,
        ),
        needs_analysis=bool(entry.needs_analysis),
        missing=bool(entry.missing),
        indexed=bool(entry.indexed),
        dominant_note=entry.dominant_note,
        detected_scale_label=entry.detected_scale_label,
        detected_scale_kind=entry.detected_scale_kind,
        scale_confidence=entry.scale_confidence,
        compatible_scales=_normalize_compatible_scales(entry.compatible_scales),
        metadata={"directory_entry": entry},
    )


def _normalize_compatible_scales(raw_value) -> tuple[str, ...]:
    """Normalise les gammes compatibles en tuple de chaines, quelle que soit la forme d'entree.

    Accepte : None, liste/tuple/set, chaine brute, ou chaine JSON.
    Retourne toujours un tuple de chaines non vides.
    """
    if raw_value is None:
        return ()
    if isinstance(raw_value, (list, tuple, set)):
        return tuple(
            text
            for text in (str(value or "").strip() for value in raw_value)
            if text
        )
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return (text,)
        return tuple(
            value
            for value in (str(item or "").strip() for item in parsed if item is not None)
            if value
        )
    return ()
