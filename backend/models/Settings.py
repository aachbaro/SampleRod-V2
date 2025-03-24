from backend.db import Base, SessionLocal
from sqlalchemy import Column, Integer, Boolean
from sqlalchemy.exc import NoResultFound

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    retro_recording_enabled = Column(Boolean, default=False, nullable=False)
    pre_recording_seconds = Column(Integer, default=0, nullable=False)

    def __init__(self, retro_recording_enabled=False, pre_recording_seconds=0):
        """
        Initialise une instance de Settings.
        Cette méthode ne sauvegarde pas directement dans la base de données.
        """
        self.retro_recording_enabled = retro_recording_enabled
        self.pre_recording_seconds = pre_recording_seconds

    @classmethod
    def initialize_settings(cls):
        session = SessionLocal()
        try:
            settings = session.query(cls).first()
            if not settings:
                settings = cls(retro_recording_enabled=False, pre_recording_seconds=0)
                session.add(settings)
                session.commit()
            return settings  # Reste lié à la session
        except NoResultFound:
            settings = cls(retro_recording_enabled=False, pre_recording_seconds=0)
            session.add(settings)
            session.commit()
            return settings
        finally:
            session.close()  # Ferme la session proprement

    @classmethod
    def get_settings(cls):
        """
        Retourne l'instance unique des paramètres.
        """
        with SessionLocal() as session:
            return session.query(cls).first()

    def toggle_retro_recording(self):
        """
        Active ou désactive le mode rétro-enregistrement et sauvegarde dans la base de données.
        """
        with SessionLocal() as session:
            settings_entry = session.query(Settings).first()
            if settings_entry:
                settings_entry.retro_recording_enabled = not settings_entry.retro_recording_enabled
                session.commit()
                print("retro rec enabled in settings:", settings_entry.retro_recording_enabled)

    def set_retro_recording_state(self, state: bool):
        """
        Met à jour l'état du rétro-enregistrement dans la base de données.
        """
        with SessionLocal() as session:
            settings_entry = session.query(Settings).first()
            if settings_entry:
                settings_entry.retro_recording_enabled = state
                session.commit()
                print("Settings: set_recording_state:", settings_entry.retro_recording_enabled)
            else:
                print("Erreur : entrée 'settings' introuvable dans la base de données.")

    def set_pre_recording_seconds(self, seconds: int):
        """
        Définit le nombre de secondes pour le rétro-enregistrement et met à jour la base de données.
        """
        if seconds < 0:
            raise ValueError("Le nombre de secondes ne peut pas être négatif.")

        with SessionLocal() as session:
            settings_entry = session.query(Settings).first()
            if settings_entry:
                settings_entry.pre_recording_seconds = seconds
                session.commit()
                print(f"Le nombre de secondes pour le rétro-enregistrement a été mis à jour : {seconds}s")
            else:
                print("Erreur : entrée 'settings' introuvable dans la base de données.")

    def to_dict(self):
        """
        Retourne les paramètres sous forme d'un dictionnaire pour le frontend.
        """
        return {
            "retro_recording_enabled": self.retro_recording_enabled,
            "pre_recording_seconds": self.pre_recording_seconds,
        }