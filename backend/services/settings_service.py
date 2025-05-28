# settings_service.py
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtCore import QSettings
from backend.models.SampleLibrary import SampleBank
from backend.db import SessionLocal

class SettingsService(QObject):
    retroToggled      = pyqtSignal(bool)
    preSecondsChanged = pyqtSignal(int)
    librariesChanged  = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._qs = QSettings("SampleRod", "Main")
        self.libraries = SampleBank.get_all_libraries()
        self.librariesChanged.emit(self.libraries)
        # self._init_retro_settings()

    # ——— Retro Recording —————————————————————————————

    # def _init_retro_settings(self):
    #     # Valeurs par défaut si jamais pas dans QSettings
    #     print("setting service: Initialisation des paramètres de rétro-enregistrement")
    #     retro   = self._qs.value("retroEnabled", False, type=bool)
    #     pre_sec = self._qs.value("preSeconds",    20,    type=int)
    #     # Émet l’état initial au démarrage
    #     # self.retroToggled.emit(retro)
    #     # self.preSecondsChanged.emit(pre_sec)

    def toggleRetro(self):
        """Inverse le flag et le persiste dans QSettings."""
        print("setting service: Basculement de l'état du rétro-enregistrement")
        retro = not self._qs.value("retroEnabled", False, type=bool)
        self._qs.setValue("retroEnabled", retro)
        self.retroToggled.emit(retro)
        print(f"Rétro-enregistrement {'activé' if retro else 'désactivé'}")

    def setPreSeconds(self, secs: int):
        """Change la durée du pré-enregistrement."""
        print(f"setting service: Modification des secondes de pré-enregistrement à {secs}")
        self._qs.setValue("preSeconds", secs)
        self.preSecondsChanged.emit(secs)

    def isRetroEnabled(self) -> bool:
        """Retourne l’état actuel du rétro-recording."""
        return self._qs.value("retroEnabled", False, type=bool)

    def getPreSeconds(self) -> int:
        """Retourne la valeur actuelle des secondes de pré-enregistrement."""
        return self._qs.value("preSeconds", 20, type=int)

# --------------------- Sample Libraries Settings -------------------------------

    def addSampleLibrary(self, path: str):
        """Ajoute une nouvelle librairie de samples à la base de données."""
        print(f"setting service: Ajout de la librairie de samples : {path}")
        SampleBank(path)
        self.libraries = SampleBank.get_all_libraries()
        self.librariesChanged.emit(self.libraries)

    def removeSampleLibrary(self, library_id: int):
        """Supprime une librairie de samples de la base de données."""
        print(f"setting service: Suppression de la librairie de samples avec ID : {library_id}")
        try:
            SampleBank.delete_library(library_id)
            # puis tu relaances get_all_libraries() et tu réaffiches la liste
            self.libraries = SampleBank.get_all_libraries()
            self.librariesChanged.emit(self.libraries)
        except ValueError as e:
            print("Erreur à la suppression :", e)

    def updateLibraryOrder(self, ordered_ids: list):
        """Met à jour l'ordre des librairies en base de données."""
        print(f"setting service: Mise à jour de l'ordre des librairies : {ordered_ids}")
        SampleBank.reorder_libraries(ordered_ids)
        self.libraries = SampleBank.get_all_libraries()
        self.librariesChanged.emit(self.libraries)

    # def getSampleLibraries(self):
    #     return SampleBank.get_all_libraries()