# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere les operations de normalisation (UI + workers).
# - Centralise les callbacks started / finished / failed.
# -----------------------------------------------------------------------------

from __future__ import annotations

from backend.models.normalize_worker import NormalizeWorker
from backend.services.notification_service import NotificationType


class SampleListNormalize:
    def __init__(self, widget):
        self.widget = widget

    def on_started(self, sample_id: int):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationStarted()

    def on_finished(self, sample_id: int):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationFinished()

    def on_failed(self, sample_id: int, message: str):
        card = self.widget._card_widgets.get(sample_id)
        if card:
            card.indicateNormalizationError(message)

    def on_clicked(self, sample_id: int):
        if self.widget.sample_store.is_normalization_locked(sample_id):
            self.widget.app_context.notifications.notify(
                title="Normalisation en attente",
                message="Decide d'abord si tu veux concatener ce sample.",
                type=NotificationType.WARNING,
            )
            return

        samp = next(
            (s for s in self.widget.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if samp is None:
            return

        running = self.widget.app_context.sample_store._normalize_threads.get(sample_id)
        if running is not None and running.isRunning():
            return

        worker = NormalizeWorker(
            sample_id=sample_id,
            file_path=samp.path,
            mode="lufs",
            target_db=self.widget.app_context.settings.getNormalizationLevel(),
        )
        worker.startedNormalization.connect(self.widget.onStartedNormalization)
        worker.finishedNormalization.connect(self.widget.onFinishedNormalization)
        worker.start()
        self.widget.app_context.sample_store._normalize_threads[sample_id] = worker
