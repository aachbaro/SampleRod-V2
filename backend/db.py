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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import logging
logger = logging.getLogger("db")

DATABASE_URL = "sqlite:///sample.db"

engine = create_engine(DATABASE_URL, echo=False)
logger.info(f"[DB] Initialisation engine {DATABASE_URL}")

Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)



