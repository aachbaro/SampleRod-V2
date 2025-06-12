import os
import logging
logger = logging.getLogger("utils")

def get_folder_name(path):
    """Extrait le nom du dernier répertoire ou fichier d'un chemin."""
    name = os.path.basename(os.path.normpath(path))
    logger.info(f"[Utils] Nom de dossier extrait : {name}")
    return name
