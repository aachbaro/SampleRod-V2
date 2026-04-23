# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Configuration de la couche SQLAlchemy (engine, session, Base).
# - Expose SessionLocal pour les services/modeles backend.
#
# LIENS CLES
# - backend/models/sample.py
# - backend/models/SampleLibrary.py
# -----------------------------------------------------------------------------
# backend/db.py

# backend/db.py
import os
import sys

if sys.platform.startswith("win"):
    # Avoid SQLAlchemy's optional C-extension import path, which can stall on
    # some Windows/Python setups while probing platform details via WMI.
    os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import logging
logger = logging.getLogger("db")

DATABASE_URL = "sqlite:///sample.db"

engine = create_engine(DATABASE_URL, echo=False)
logger.info(f"[DB] Initialisation engine {DATABASE_URL}")

Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_sqlite_schema() -> None:
    """Ajoute les colonnes connues manquantes sans reconstruire la base."""
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    with engine.begin() as connection:
        table_exists = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='samples'"
        ).fetchone()
        if not table_exists:
            return

        columns = {
            str(row[1]).lower()
            for row in connection.exec_driver_sql("PRAGMA table_info(samples)").fetchall()
        }
        migrations = {
            "missing": "ALTER TABLE samples ADD COLUMN missing INTEGER NOT NULL DEFAULT 0",
            "rms_level": "ALTER TABLE samples ADD COLUMN rms_level FLOAT",
            "analyzed_at": "ALTER TABLE samples ADD COLUMN analyzed_at DATETIME",
            "dominant_note": "ALTER TABLE samples ADD COLUMN dominant_note VARCHAR(4)",
            "scale_confidence": "ALTER TABLE samples ADD COLUMN scale_confidence FLOAT",
            "compatible_scales": "ALTER TABLE samples ADD COLUMN compatible_scales TEXT",
        }
        for column_name, ddl in migrations.items():
            if column_name not in columns:
                connection.exec_driver_sql(ddl)



