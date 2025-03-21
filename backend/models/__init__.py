# /backend/models/__init__.py

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Importez tous les modèles ici
from .sample import Sample
from .recorder import Recorder