# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service central de configuration (QSettings) pour l'app audio.
# - Source de verite des parametres UI/Audio/Librairies/Normalisation.
# - Emet des signaux Qt pour synchroniser les autres services (Recorder, UI...).
#
# CE QUI EST DEJA EN PLACE
# - Retro-recording: enable/disable + preSeconds.
# - Audio: sample rate + loopback device (soundcard).
# - Libraries: ajout/suppression/reorder.
# - Normalization: auto-normalize + niveau LUFS.
# - Display: pagination des samples.
# - Remote control: toggle + port serveur HTTP.
#
# CE QUI RESTE A IMPLEMENTER (IDEES)
# - Latence/buffer: taille de buffer, taille de bloc, device input/output.
# - Monitoring: volume monitor, mute, solo, pan, output device.
# - Formats: WAV/FLAC/AIFF, bitrate, dither, export profiles.
# - Metadonnees: tags, BPM, key, gain, colors, favoris.
# - Workflow: auto-nommage, templates, dossiers par projet, hotkeys.
# - Qualite: limiter/soft-clip, normalize peak vs LUFS, true-peak.
# - UI: theme, densite d'info, auto-scroll, zoom waveform.
#
# NOTES
# - Toute nouvelle option doit etre persistee dans QSettings et emitter un signal.
# - Garder les defaults coherents avec le recorder_worker.
# -----------------------------------------------------------------------------
# settings_service.py
# Qt: QObject + signaux
from PySide6.QtCore import QObject, Signal
# QSettings: persistance des preferences
from PySide6.QtCore import QSettings
# SampleBank: gestion des librairies
from backend.models.SampleLibrary import SampleBank
# DB session (utilisee par SampleBank)
from backend.db import SessionLocal
# soundcard: detection des devices audio (loopback)
import soundcard as sc
# Acces aux variables d'environnement
import os
# Notifications UI
from backend.services.notification_service import NotificationType
# Logging
import logging
# Logger specifique au service
logger = logging.getLogger("settings_service")

class SettingsService(QObject):
    # Signaux emis pour synchroniser UI et services
    retroToggled      = Signal(bool)
    preSecondsChanged = Signal(int)
    librariesChanged  = Signal(list)
    sampleRateChanged = Signal(int)
    loopbackDeviceChanged = Signal(object)
    autoNormalizeToggled   = Signal(bool)
    normalizationLevelChanged = Signal(int)
    samplesPerPageChanged = Signal(int)
    remoteControlToggled = Signal(bool)
    remoteControlPortChanged = Signal(int)
    screenshotToggled = Signal(bool)
    screenshotLibraryChanged = Signal(str)
    screenshotDefaultScreenChanged = Signal(int)

    def __init__(self, app_context):
        super().__init__()
        # Store persistent des settings (cle/valeur)
        self._qs = QSettings("SampleRod", "Main")

        # Acces aux autres services via le contexte
        self.app_context = app_context
        
        # Chargement initial des librairies
        self.libraries = SampleBank.get_all_libraries()

        # Audio: device loopback + sample rate
        self.loopback_device = None
        self.sample_rate = 44100  # valeur récupérée du QSettings
        self._sample_rate = self.sample_rate

        # Display: pagination des samples
        self.samples_per_page = self._qs.value(
            "display/samples_per_page", 20, type=int
        )
        self.samplesPerPageChanged.emit(self.samples_per_page)

        # Screenshot: activation + dossier + ecran par defaut
        self.screenshot_enabled = self._qs.value("screenshot/enabled", False, type=bool)
        self.screenshot_library_path = self._qs.value("screenshot/library_path", "", type=str)
        self.screenshot_default_screen = self._qs.value("screenshot/default_screen", 0, type=int)
        self.screenshotToggled.emit(self.screenshot_enabled)
        self.screenshotLibraryChanged.emit(self.screenshot_library_path)
        self.screenshotDefaultScreenChanged.emit(self.screenshot_default_screen)

        # Normalization: auto + niveau LUFS
        auto_norm = self._qs.value("autoNormalizeEnabled", False, type=bool)
        self.normalization_level = self._qs.value("normalizationLevel", -14, type=int)  # ex : -14 LUFS
        self.autoNormalizeToggled.emit(auto_norm)
        self.normalizationLevelChanged.emit(self.normalization_level)

        # Emission initiale pour l'UI
        self.librariesChanged.emit(self.libraries)

        # Initialise les parametres audio (sample rate + loopback)
        self._init_audio_settings()


        logger.info("[SettingsService] Initialisation des paramètres de l'application")
        logger.info(
            "[SettingsService] loopback_device : %s",
            self.loopback_device
        )

    # ——— Retro Recording —————————————————————————————

    # ------------------------------------------------------------------ Retro Recording
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

    # ------------------------------------------------------------------ Sample Libraries
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

    # ------------------------------------------------------------------ Audio Settings
    def _init_audio_settings(self):
        # → Sample rate
        # Charge/emet le sample rate sauvegarde
        rate = self._qs.value("sampleRate", 44100, type=int)
        self.sample_rate = rate
        self.sampleRateChanged.emit(rate)
        self._qs.setValue("sampleRate", rate)

        # → Loopback device
        # Liste des devices loopback disponibles
        mics = sc.all_microphones(include_loopback=True)
        # Nom sauvegarde du device loopback
        saved_name = self._qs.value("loopbackDeviceName", "", type=str)

        # Si on a déjà un choix, on cherche l’objet qui correspond
        # Retrouver le device par nom
        device = next((m for m in mics if m.name == saved_name), None)

        # Sinon fallback sur la même logique que dans recorder_worker
        # Fallback: prendre le device qui correspond au speaker par defaut
        if device is None and mics:
            speaker = sc.default_speaker()
            device = next((m for m in mics if speaker.name in m.name), mics[0])

        # Memoriser le device et reemettre vers l'UI
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

    # ------------------------------------------------------------------ Normalization Settings
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

    # ------------------------------------------------------------------ Display Settings
    def setSamplesPerPage(self, count: int):
        """Change le nombre de samples affichés par page."""
        logger.info(
            f"[SettingsService] Modification du nombre de samples/page à {count}"
        )
        self.samples_per_page = count
        self._qs.setValue("display/samples_per_page", count)
        self.samplesPerPageChanged.emit(count)

    def getSamplesPerPage(self) -> int:
        return self._qs.value("display/samples_per_page", 20, type=int)

    # ------------------------------------------------------------------ Remote Control Settings
    def isRemoteControlEnabled(self) -> bool:
        """Retourne si le controle distant est actif (QSettings + fallback env)."""
        default_enabled = os.getenv("REMOTE_CONTROL_ENABLED", "1").lower() not in ("0", "false", "no")
        return self._qs.value("remote_control/enabled", default_enabled, type=bool)

    def setRemoteControlEnabled(self, enabled: bool):
        """Persiste le toggle du controle distant."""
        self._qs.setValue("remote_control/enabled", enabled)
        self.remoteControlToggled.emit(enabled)

    def getRemoteControlPort(self) -> int:
        """Port HTTP pour le controle distant (QSettings + fallback env)."""
        env_port = os.getenv("REMOTE_CONTROL_PORT", "8765")
        try:
            default_port = int(env_port)
        except ValueError:
            default_port = 8765
        return self._qs.value("remote_control/port", default_port, type=int)

    def setRemoteControlPort(self, port: int):
        """Persiste le port HTTP du controle distant."""
        self._qs.setValue("remote_control/port", port)
        self.remoteControlPortChanged.emit(port)

    # ------------------------------------------------------------------ Screenshot Settings
    def isScreenshotEnabled(self) -> bool:
        return self._qs.value("screenshot/enabled", False, type=bool)

    def setScreenshotEnabled(self, enabled: bool):
        self.screenshot_enabled = enabled
        self._qs.setValue("screenshot/enabled", enabled)
        self.screenshotToggled.emit(enabled)

    def getScreenshotLibraryPath(self) -> str:
        return self._qs.value("screenshot/library_path", "", type=str)

    def setScreenshotLibraryPath(self, path: str):
        self.screenshot_library_path = path
        self._qs.setValue("screenshot/library_path", path)
        self.screenshotLibraryChanged.emit(path)
        if path and not self.isScreenshotEnabled():
            self.setScreenshotEnabled(True)

    def getScreenshotDefaultScreen(self) -> int:
        return self._qs.value("screenshot/default_screen", 0, type=int)

    def setScreenshotDefaultScreen(self, index: int):
        self.screenshot_default_screen = index
        self._qs.setValue("screenshot/default_screen", index)
        self.screenshotDefaultScreenChanged.emit(index)
