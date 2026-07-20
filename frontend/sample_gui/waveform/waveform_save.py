# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere la sauvegarde (overwrite/copy) et l'export rapide depuis WaveformWidget.
# - Isole la logique I/O pour alleger wave_form.py.
#
# CE QUI EST COUVERT
# - Save (overwrite / save as copy) du fichier courant.
# - Notification de succes et mise a jour du SampleService.
# - Export shortcut (selection) via WaveformRegionController.
#
# RESPONSABILITES TECHNIQUES
# - Ecrire le WAV via soundfile.
# - Interagir avec SaveWaveformDialog.
# - Mettre a jour la base via SampleService.
#
# NON-OBJECTIFS
# - Decoupe de region (WaveformRegionController).
# - Playback (WaveformPlaybackController).
#
# DEPENDANCES
# - PySide6 (QMessageBox)
# - soundfile
# - SaveWaveformDialog, NotificationType
# -----------------------------------------------------------------------------

from __future__ import annotations

from frontend.custom_widgets import SaveWaveformDialog
from backend.services.notification_service import NotificationType


class WaveformSaveController:
    """Gere la sauvegarde (overwrite ou copie) et l'export rapide du fichier audio."""

    def __init__(self, widget):
        self.widget = widget

    def on_save_clicked(self):
        """
        Ouvre un dialog Overwrite / Save as copy, ecrit le WAV
        et met a jour la base si overwrite, ou cree un nouveau sample si copy.
        """
        w = self.widget
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        import os, soundfile as sf
        from backend.models.sample import Sample as DBSample

        # 1) Choix Overwrite vs Copy
        orig = w.audio_file_path
        folder = os.path.dirname(orig)
        ext = os.path.splitext(orig)[1]
        default_name = f"SMPL_{DBSample.get_next_id():04d}"

        dlg = SaveWaveformDialog(w, default_name)
        overwrite, new_name = dlg.choice()
        if overwrite is None:
            return  # utilisateur a annule

        if overwrite:
            target = orig
        else:
            target = os.path.join(folder, new_name + ext)

        try:
            sf.write(target, w.waveform_data, w.sample_rate)
        except Exception as e:
            QMessageBox.critical(w, "Erreur", str(e))
            return

        svc = w.app_context.sample_store

        if overwrite:
            # recalculer la duree et mettre a jour le service uniquement pour ce fichier
            svc.updateDurationFromFile(target)
            # Notification when the file is saved over the original
            w.app_context.notifications.notify(
                title="✅ Fichier sauvegarde",
                message=os.path.basename(target),
                type=NotificationType.SUCCESS,
            )
        else:
            # creation d'un nouveau sample (FS+BD) via SampleService.add()
            svc.add(target)

    def on_export_shortcut(self):
        """Callback du raccourci : exporte la region selectionnee si elle existe."""
        w = self.widget
        if hasattr(w, "region") and w.region is not None:
            start, end = w.region.getRegion()
            w._export_region(start, end)
