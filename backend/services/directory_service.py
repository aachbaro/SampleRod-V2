import os
import shutil
from PyQt6.QtCore import QMimeData


class DirectoryService:
    """Service utilitaire pour importer des fichiers dans un dossier."""

    def list_samples(self, folder: str) -> list[str]:
        """Return list of file names inside folder."""
        if not os.path.isdir(folder):
            return []
        return sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))

    def handle_drop(self, folder: str, mime: QMimeData) -> None:
        """Handle drop event with custom MIME data."""
        os.makedirs(folder, exist_ok=True)
        for fmt in ("application/x-sample-slice-data", "application/x-sample-card"):
            if mime.hasFormat(fmt):
                data = bytes(mime.data(fmt)).decode(errors="ignore")
                for line in filter(None, data.splitlines()):
                    src = line.strip()
                    if os.path.isfile(src):
                        dst = os.path.join(folder, os.path.basename(src))
                        try:
                            shutil.copy(src, dst)
                        except Exception:
                            pass

