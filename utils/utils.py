# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Utilitaires transverses simples reutilises dans l'application.
# - Fonctions helpers pour manipulation de chemins et valeurs UI.
#
# LIENS CLES
# - frontend/record_widget.py
# - backend/services/sample_service.py
# -----------------------------------------------------------------------------
# utils/utils.py

import os
import logging
logger = logging.getLogger("utils")

def get_folder_name(path):
    """Extrait le nom du dernier répertoire ou fichier d'un chemin."""
    name = os.path.basename(os.path.normpath(path))
    logger.info(f"[Utils] Nom de dossier extrait : {name}")
    return name
