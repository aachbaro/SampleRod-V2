import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

def _default_log_path() -> Path:
    # Priorite a un chemin explicite si fourni
    explicit = os.getenv("SAMPLEROD_LOG_PATH") or os.getenv("SAMPLE_ROD_LOG_PATH")
    if explicit:
        return Path(explicit)

    # En binaire: %LOCALAPPDATA%\SampleRod\logs\app.log
    if os.getenv("LOCALAPPDATA"):
        return Path(os.getenv("LOCALAPPDATA")) / "SampleRod" / "logs" / "app.log"

    # Fallback dev: ./logs/app.log
    return Path.cwd() / "logs" / "app.log"


def configure_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(name)s] %(message)s')

    # Console (utile en dev) - seulement si aucun handler stream existe déjà
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    # Fichier (utile en exe / debug) - toujours s'assurer qu'il existe
    log_path = _default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
