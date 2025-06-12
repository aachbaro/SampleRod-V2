# settings_service.py
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtCore import QSettings
from backend.models.SampleLibrary import SampleBank
from backend.db import SessionLocal
import soundcard as sc
from backend.services.notification_service import NotificationType
import logging
logger = logging.getLogger("settings_service")

class SettingsService(QObject):
    retroToggled      = pyqtSignal(bool)
    preSecondsChanged = pyqtSignal(int)
    librariesChanged  = pyqtSignal(list)
    sampleRateChanged = pyqtSignal(int)
    loopbackDeviceChanged = pyqtSignal(object)
    autoNormalizeToggled   = pyqtSignal(bool)
    normalizationLevelChanged = pyqtSignal(int)

    def __init__(self, app_context):
        super().__init__()
        self._qs = QSettings("SampleRod", "Main")

        self.app_context = app_context
        
        self.libraries = SampleBank.get_all_libraries()

        self.loopback_device = None
        self.sample_rate = 44100  # valeur récupérée du QSettings
        self._sample_rate = self.sample_rate

        auto_norm = self._qs.value("autoNormalizeEnabled", False, type=bool)
        self.normalization_level = self._qs.value("normalizationLevel", -14, type=int)  # ex : -14 LUFS
        self.autoNormalizeToggled.emit(auto_norm)
        self.normalizationLevelChanged.emit(self.normalization_level)

        self.librariesChanged.emit(self.libraries)

        self._init_audio_settings()


        logger.info("[SettingsService] Initialisation des paramètres de l'application")
        logger.info(
            "[SettingsService] loopback_device : %s",
            self.loopback_device
        )

    # ——— Retro Recording —————————————————————————————

    def toggleRetro(self):
        """Inverse le flag et le persiste dans QSettings."""
        logger.info("setting service: Basculement de l'état du rétro-enregistrement")
        retro = not self._qs.value("retroEnabled", False, type=bool)
        self._qs.setValue("retroEnabled", retro)
        self.retroToggled.emit(retro)
        logger.info(f"[SettingsService] Rétro-enregistrement {'activé' if retro else 'désactivé'}")

    def setPreSeconds(self, secs: int):
        """Change la durée du pré-enregistrement."""
        logger.info(f"[SettingsService] Modification des secondes de pré-enregistrement à {secs}")
        self._qs.setValue("preSeconds", secs)
        self.preSecondsChanged.emit(secs)

    def isRetroEnabled(self) -> bool:
        """Retourne l’état actuel du rétro-recording."""
        return self._qs.value("retroEnabled", False, type=bool)

    def getPreSeconds(self) -> int:
        """Retourne la valeur actuelle des secondes de pré-enregistrement."""
        return self._qs.value("preSeconds", 20, type=int)

# ————————————————————————————— Sample Libraries Settings —————————————————————————————

    def addSampleLibrary(self, path: str):
        """Ajoute une nouvelle librairie de samples à la base de données."""
        logger.info(f"[SettingsService] Ajout de la librairie de samples : {path}")
        SampleBank(path)
        self.libraries = SampleBank.get_all_libraries()
        self.librariesChanged.emit(self.libraries)

    def removeSampleLibrary(self, library_id: int):
        """Supprime une librairie de samples de la base de données."""
        logger.info(f"[SettingsService] Suppression de la librairie de samples avec ID : {library_id}")
        try:
            SampleBank.delete_library(library_id)
            # puis tu relaances get_all_libraries() et tu réaffiches la liste
            self.libraries = SampleBank.get_all_libraries()
            self.librariesChanged.emit(self.libraries)
        except ValueError as e:
            logger.info("Erreur à la suppression :", e)

    def updateLibraryOrder(self, ordered_ids: list):
        """Met à jour l'ordre des librairies en base de données."""
        logger.info(f"[SettingsService] Mise à jour de l'ordre des librairies : {ordered_ids}")
        SampleBank.reorder_libraries(ordered_ids)
        self.libraries = SampleBank.get_all_libraries()
        self.librariesChanged.emit(self.libraries)

    # ———————————————————————————————— Audio Settings —————————————————————————————

    def _init_audio_settings(self):
        # → Sample rate
        rate = self._qs.value("sampleRate", 44100, type=int)
        self.sample_rate = rate
        self.sampleRateChanged.emit(rate)
        self._qs.setValue("sampleRate", rate)

        # → Loopback device
        mics = sc.all_microphones(include_loopback=True)
        saved_name = self._qs.value("loopbackDeviceName", "", type=str)

        # Si on a déjà un choix, on cherche l’objet qui correspond
        device = next((m for m in mics if m.name == saved_name), None)

        # Sinon fallback sur la même logique que dans recorder_worker
        if device is None and mics:
            speaker = sc.default_speaker()
            device = next((m for m in mics if speaker.name in m.name), mics[0])

        self.loopback_device = device
        if device:
            # on persiste son nom pour la prochaine ouverture
            self._qs.setValue("loopbackDeviceName", device.name)
        self.loopbackDeviceChanged.emit(device)

    def setSampleRate(self, new_rate: int):
        if new_rate != self._sample_rate:
            self._sample_rate = new_rate
            self.sample_rate = new_rate
            self._qs.setValue("sampleRate", new_rate)
            self.sampleRateChanged.emit(new_rate)
            self.app_context.notifications.notify(
                title="ℹ️ Sample rate modifié",
                message=f"{new_rate} Hz",
                type=NotificationType.INFO
            )

    def setLoopbackDevice(self, device):
        """Appelé par AudioSettingsWidget."""
        self.loopback_device = device
        name = device.name if device else ""
        self._qs.setValue("loopbackDeviceName", name)
        self.loopbackDeviceChanged.emit(device)
        self.app_context.notifications.notify(
            title="ℹ️ Périphérique audio changé",
            message=f"{device.name}",
            type=NotificationType.INFO
        )

    #   ——————————————————————— Normalization Settings —————————————————————————————

    def toggleAutoNormalize(self):
        """Inverse l'état de l'auto-normalisation et le persiste dans QSettings."""
        logger.info("[SettingsService] Basculement de l'état de l'auto-normalisation")
        enabled = not self._qs.value("autoNormalizeEnabled", False, type=bool)
        self._qs.setValue("autoNormalizeEnabled", enabled)
        self.autoNormalizeToggled.emit(enabled)
        # ▶ Info auto-norm
        state = "activée" if enabled else "désactivée"
        self.app_context.notifications.notify(
            title="ℹ️ Auto-normalisation",
            message=state,
            type=NotificationType.INFO
        )

    def setNormalizationLevel(self, level: int):
        """Change le niveau de normalisation et le persiste dans QSettings."""
        logger.info(f"[SettingsService] Modification du niveau de normalisation à {level} LUFS")
        self._qs.setValue("normalizationLevel", level)
        self.normalizationLevelChanged.emit(level)

    def isAutoNormalizeEnabled(self) -> bool:
        return self._qs.value("autoNormalizeEnabled", False, type=bool)

    def getNormalizationLevel(self) -> int:
        return self._qs.value("normalizationLevel", -14, type=int)