# backend/models/Settings.py

from flask import current_app
from . import db


class Settings(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    retro_recording_enabled = db.Column(db.Boolean, default=False, nullable=False)
    pre_recording_seconds = db.Column(db.Integer, default=0, nullable=False)

    def __init__(self, retro_recording_enabled=False, pre_recording_seconds=0):
        """
        Initialise une instance de Settings. 
        Cette méthode n'interagit pas directement avec la base de données.
        """
        self.retro_recording_enabled = retro_recording_enabled
        self.pre_recording_seconds = pre_recording_seconds

    @classmethod
    def initialize_settings(cls):
        """
        Initialise les paramètres depuis la base de données ou les crée si aucun n'existe.
        """
        instance = cls.query.first()
        if not instance:
            instance = cls()  # Crée une nouvelle instance avec les valeurs par défaut
            db.session.add(instance)
            db.session.commit()
        return instance

    @classmethod
    def get_settings(cls):
        """
        Retourne l'instance unique des paramètres.
        """
        return cls.query.first()

    def toggle_retro_recording(self):
        """
        Active ou désactive le mode rétro-enregistrement et sauvegarde dans la base de données.
        """
        self.retro_recording_enabled = not self.retro_recording_enabled
        db.session.commit()
        print("retro rec enabled in settings: ", self.retro_recording_enabled)
        
    def set_retro_recording_state(self, state: bool):
        """
        Met à jour l'état de retro recording dans la base de données.
        """
        # Récupérer l'entrée des paramètres dans la base de données (id = 1 ici, à adapter si nécessaire)
        settings_entry = db.session.query(Settings).filter_by(id=1).first()
        
        if settings_entry:
            # Mettre à jour la valeur de retro_recording_enabled
            settings_entry.retro_recording_enabled = int(state)  # Assurez-vous que ce champ accepte des entiers (0/1)
            db.session.commit()  # Sauvegarde des modifications dans la base de données
            
            # Mettre à jour l'attribut local si nécessaire
            self.retro_recording_enabled = state
            print("Settings: set_recording_state:", self.retro_recording_enabled)
        else:
            print("Erreur : entrée 'settings' introuvable dans la base de données.")

    def set_pre_recording_seconds(self, seconds: int):
        """
        Définit le nombre de secondes pour le rétro-enregistrement et met à jour la base de données.
        """
        print("Class Settings: set pre-recording seconds")

        if seconds < 0:
            raise ValueError("Le nombre de secondes ne peut pas être négatif.")

        try:
            # Récupérer l'entrée des paramètres dans la base de données (id = 1 ici, à adapter si nécessaire)
            settings_entry = db.session.query(Settings).filter_by(id=1).first()

            if settings_entry:
                # Mettre à jour la valeur de prerecord_seconds
                settings_entry.pre_recording_seconds = seconds
                print("settings_entry.pre_recording_seconds", settings_entry.pre_recording_seconds)
                db.session.commit()  # Sauvegarder les modifications dans la base de données

                # Mettre à jour l'attribut local si nécessaire
                self.pre_recording_seconds = seconds
                print(f"Le nombre de secondes pour le rétro-enregistrement a été mis à jour : {seconds}s")
            else:
                print("Erreur : entrée 'settings' introuvable dans la base de données.")
        except Exception as e:
            print("Erreur lors de la mise à jour de la base de données :", str(e))


    def to_dict(self):
        """
        Retourne les paramètres sous forme d'un dictionnaire pour le frontend.
        """
        return {
            "retro_recording_enabled": self.retro_recording_enabled,
            "pre_recording_seconds": self.pre_recording_seconds,
        }
