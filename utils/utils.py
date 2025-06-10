import os

def get_folder_name(path):
    """Extrait le nom du dernier répertoire ou fichier d'un chemin."""
    return os.path.basename(os.path.normpath(path))
