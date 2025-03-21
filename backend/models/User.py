# /backend/models/User.py

from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from models.sample import Sample
from models.recorder import Recorder
from models.SampleLibrary import SampleBank
from models.Settings import Settings
from flask import current_app
from . import db

class User:
    def __init__(self):
        print("Initialisation du User")
        self.settings = Settings.initialize_settings()
        self.recorder = Recorder(self.settings)
        print("User: Settings:", self.settings.to_dict())
        if self.settings.retro_recording_enabled:
            self.recorder.bac_rec_activated()

    def to_dict(self):
        return {
            "user.to_dict"
        }

    def __repr__(self):
        return f"user(__repr__)"