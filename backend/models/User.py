# /backend/models/User.py

from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.models.sample import Sample
from backend.models.recorder import Recorder
from backend.models.SampleLibrary import SampleBank
from backend.models.Settings import Settings
from backend.db import SessionLocal

class User:
    def __init__(self):
        print("Initialisation du User")
        session = SessionLocal()
        self.settings = session.query(Settings).first()
        if not self.settings:
            self.settings = Settings(retro_recording_enabled=False, pre_recording_seconds=0)
            session.add(self.settings)
            session.commit()

        self.libraries = SampleBank.get_all_libraries()

        self.recorder = Recorder(self.settings)  # Maintenant, settings est bien lié à une session
        print("User: Settings:", self.settings.to_dict())
        
        if self.settings.retro_recording_enabled:
            self.recorder.bac_rec_activated()