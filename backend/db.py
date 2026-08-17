# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Porte d'entree vers la base de donnees de l'application (fichier sample.db,
#   au format SQLite : une base de donnees contenue dans un simple fichier).
# - Configure SQLAlchemy, la bibliotheque qui traduit les objets Python
#   (Sample, SampleLibrary...) en lignes de tables, et inversement.
# - Tout le reste du backend passe par ici pour lire/ecrire des donnees.
#
# OBJETS / FONCTIONS (sommaire)
# - engine                 : la connexion physique au fichier sample.db.
# - Base                   : la classe mere dont heritent tous les modeles
#                            (un modele = la description d'une table).
# - SessionLocal           : fabrique de "sessions", c'est-a-dire de
#                            conversations temporaires avec la base
#                            (lire, modifier, valider ou annuler).
# - ensure_sqlite_schema() : mini systeme de migration qui ajoute les
#                            colonnes manquantes apres une mise a jour.
#
# LIENS CLES
# - backend/models/sample.py        : table des samples.
# - backend/models/SampleLibrary.py : table des librairies.
# - backend/models/screenshot.py    : table des captures d'ecran.
# -----------------------------------------------------------------------------
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

# Adresse de la base : un fichier "sample.db" dans le dossier de lancement.
DATABASE_URL = "sqlite:///sample.db"

# L'engine est l'objet qui sait ouvrir et parler au fichier SQLite.
# echo=False : ne pas afficher chaque requete SQL dans la console.
engine = create_engine(DATABASE_URL, echo=False)
logger.info(f"[DB] Initialisation engine {DATABASE_URL}")

# Base sert de point d'ancrage : chaque modele qui en herite declare
# automatiquement sa table aupres de SQLAlchemy.
Base = declarative_base()

# SessionLocal() ouvre une nouvelle session de travail avec la base.
# autoflush/autocommit desactives : rien n'est ecrit tant qu'on ne fait
# pas explicitement session.commit() — ce qui permet d'annuler en cas d'erreur.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_sqlite_schema() -> None:
    """Ajoute les colonnes connues manquantes sans reconstruire la base.

    Quand une nouvelle version de l'application introduit une colonne
    (ex : la note dominante detectee), les bases creees avant ne l'ont pas.
    Cette fonction compare les colonnes reelles de la table "samples" avec
    la liste des colonnes attendues, et execute un "ALTER TABLE" (ajout de
    colonne) pour chaque manquante. Les donnees existantes sont preservees.
    """
    # Securite : cette technique n'est valable que pour SQLite.
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    with engine.begin() as connection:
        # Si la table "samples" n'existe pas encore (toute premiere
        # ouverture), il n'y a rien a migrer : create_all la creera complete.
        table_exists = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='samples'"
        ).fetchone()
        if not table_exists:
            return

        # Liste des colonnes actuellement presentes dans la table.
        columns = {
            str(row[1]).lower()
            for row in connection.exec_driver_sql("PRAGMA table_info(samples)").fetchall()
        }
        # Catalogue des colonnes ajoutees au fil des versions, avec la
        # commande SQL qui permet de les creer.
        migrations = {
            "missing": "ALTER TABLE samples ADD COLUMN missing INTEGER NOT NULL DEFAULT 0",
            "rms_level": "ALTER TABLE samples ADD COLUMN rms_level FLOAT",
            "analyzed_at": "ALTER TABLE samples ADD COLUMN analyzed_at DATETIME",
            "dominant_note": "ALTER TABLE samples ADD COLUMN dominant_note VARCHAR(4)",
            "detected_scale_label": "ALTER TABLE samples ADD COLUMN detected_scale_label VARCHAR(64)",
            "detected_scale_kind": "ALTER TABLE samples ADD COLUMN detected_scale_kind VARCHAR(16)",
            "scale_confidence": "ALTER TABLE samples ADD COLUMN scale_confidence FLOAT",
            "compatible_scales": "ALTER TABLE samples ADD COLUMN compatible_scales TEXT",
            "material_metadata": "ALTER TABLE samples ADD COLUMN material_metadata TEXT",
        }
        # On n'ajoute que ce qui manque : relancer la fonction est sans danger.
        for column_name, ddl in migrations.items():
            if column_name not in columns:
                connection.exec_driver_sql(ddl)

