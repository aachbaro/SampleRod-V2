# backend/models/__init__.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Création de la base SQLAlchemy
Base = declarative_base()

# Configuration de la base de données
engine = create_engine('sqlite:///samples.db', echo=True)
Session = sessionmaker(bind=engine)