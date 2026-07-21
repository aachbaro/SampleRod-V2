# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Definit "l'artefact de labo" : tout resultat produit dans l'onglet Labo
#   (un morceau decoupe, un stem separe, un break genere...) avant qu'il ne
#   soit eventuellement sauvegarde pour de bon.
# - Un artefact est souvent TEMPORAIRE : son audio vit dans un fichier temp
#   (temp_path) ; "persiste" signifie qu'il a ete enregistre dans une vraie
#   destination. Le plateau d'artefacts (artifact_tray) affiche ces fiches.
#
# CLASSE ET FONCTIONS (sommaire)
# - LabArtifactKind : les types possibles (slice, fichier courant, stem,
#   preview quantizee, break genere).
# - LabArtifact     : la fiche (id, type, nom, fichier source, fichier temp,
#   bornes de decoupe, duree, persiste?, origine, metadonnees libres).
# - artifact_kind_label()    : type -> texte affichable ("Slice", "Stem"...).
# - artifact_status_label()  : "Persiste" ou "Temporaire".
# - artifact_duration_label(): duree -> "1.25s".
# - build_artifact_filename(): fabrique un nom de fichier sur et propre
#   a partir du nom affiche (caracteres interdits remplaces par _).
# - artifact_source_name()   : nom du fichier source d'origine.
# - artifact_file_path()     : chemin du fichier audio a utiliser
#   (le temporaire s'il existe, sinon la source).
#
# LIENS CLES
# - frontend/labo/artifact_tray.py : le plateau qui affiche ces artefacts.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

LabArtifactKind = Literal["slice", "current_file", "stem", "break_preview", "break_pattern"]


@dataclass(slots=True)
class LabArtifact:
    """Fiche d'un resultat du Labo (souvent temporaire, voir en-tete)."""

    artifact_id: str
    kind: LabArtifactKind
    display_name: str
    source_path: str
    temp_path: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    duration: float = 0.0
    persisted: bool = False
    origin: str = ""
    parent_ids: list[str] = field(default_factory=list)
    operation: str = ""
    sample_rate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def artifact_kind_label(kind: LabArtifactKind) -> str:
    """Traduit le type d'artefact en texte affichable."""
    if kind == "slice":
        return "Slice"
    if kind == "stem":
        return "Stem"
    if kind == "break_preview":
        return "Preview quantizee"
    if kind == "break_pattern":
        return "Break genere"
    return "Fichier courant"


def artifact_status_label(artifact: LabArtifact) -> str:
    """Texte de statut : l'artefact a-t-il ete sauvegarde quelque part ?"""
    return "Persiste" if artifact.persisted else "Temporaire"


def artifact_duration_label(duration: float) -> str:
    """Duree formatee pour l'affichage, ex : "1.25s"."""
    return f"{float(duration or 0.0):.2f}s"


def build_artifact_filename(artifact: LabArtifact, extension: str = ".wav") -> str:
    """Fabrique un nom de fichier valide a partir du nom affiche.

    Les caracteres interdits dans un nom de fichier sont remplaces par _,
    les espaces multiples sont reduits, et l'extension est ajoutee si
    absente. Si tout est vide, on retombe sur le type ("slice.wav").
    """
    base = artifact.display_name.strip() or artifact_kind_label(artifact.kind)
    sanitized = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else "_" for ch in base)
    sanitized = "_".join(sanitized.split())
    if not sanitized:
        sanitized = artifact_kind_label(artifact.kind).lower().replace(" ", "_")

    if not sanitized.lower().endswith(extension.lower()):
        sanitized = f"{sanitized}{extension}"

    return sanitized


def artifact_source_name(artifact: LabArtifact) -> str:
    """Nom du fichier d'origine (sans le dossier)."""
    return os.path.basename(artifact.source_path) or artifact.source_path


def artifact_file_path(artifact: LabArtifact) -> str:
    """Chemin du fichier audio a lire : le temporaire d'abord, sinon la source."""
    candidate = artifact.temp_path or artifact.source_path
    return os.path.normpath(os.path.abspath(candidate)) if candidate else ""
