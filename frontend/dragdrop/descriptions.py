from __future__ import annotations

from .acceptance import DropAction
from .payload import DragPayload, MaterialStatus


def describe_drop(action: DropAction, payload: DragPayload) -> str:
    """Libellé UX contextuel, sans influence sur action ni compatibilité."""
    status = payload.status
    if action is DropAction.OPEN:
        return {
            MaterialStatus.DERIVED: "Ouvrir le dérivé",
            MaterialStatus.ARTIFACT: "Ouvrir l’artefact",
        }.get(status, "Ouvrir dans Waveform")
    if action is DropAction.LOAD_BREAK:
        return "Charger le break"
    if action is DropAction.IMPORT_AS_SOURCE:
        return {
            MaterialStatus.DERIVED: "Ajouter comme nouvelle source",
            MaterialStatus.ARTIFACT: "Ajouter l’artefact comme source",
        }.get(status, "Ajouter à la Réserve")
    if action is DropAction.CREATE_ARTIFACT:
        return {
            MaterialStatus.DERIVED: "Conserver cette transformation",
            MaterialStatus.ARTIFACT: "Importer l’artefact",
        }.get(status, "Créer un artefact depuis la source")
    if action is DropAction.SEPARATE_STEMS:
        return "Séparer cette sélection" if payload.selection else "Séparer les stems"
    if action is DropAction.ADD_TO_COMPOSITION:
        return "Ajouter à la composition"
    if action is DropAction.MOVE_TO_BIN:
        return "Ranger"
    if action is DropAction.ADD_TO_MIX:
        return "Ajouter au mix"
    if action is DropAction.COPY_TO_DIRECTORY:
        return "Ajouter au dossier"
    return "Déposer"
