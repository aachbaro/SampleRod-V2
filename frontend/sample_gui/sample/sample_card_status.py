# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gère les updates simples de l'état "statique" d'une SampleCard.
# - Centralise la mise à jour de la durée et du nom affiché.
# -----------------------------------------------------------------------------

from __future__ import annotations


class SampleCardStatus:
    def __init__(self, card):
        self.card = card

    def refresh_display(self):
        """Met à jour l'affichage du nom du sample."""
        self.card.name_label.setText(self.card.sample.name)

    def on_duration_changed(self, sample_id, new_duration: float):
        c = self.card
        if c.sample.id == sample_id:
            c.sample.duration = new_duration
            c.length_label.setText(f"{new_duration:.1f}s")
