# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere les updates simples de l'etat "statique" d'une SampleCard.
# -----------------------------------------------------------------------------

from __future__ import annotations

from frontend.reserve import apply_status_badge, reserve_entry_from_sample


class SampleCardStatus:
    def __init__(self, card):
        self.card = card

    def refresh_display(self):
        c = self.card
        c.name_label.setText(c.sample.name)
        c.length_label.setText(f"{float(c.sample.duration or 0.0):.1f}s")
        entry = reserve_entry_from_sample(c.sample, source_kind="history")
        apply_status_badge(c.status_label, entry.status)
        c.status_label.setVisible(True)

    def on_duration_changed(self, sample_id, new_duration: float):
        c = self.card
        if c.sample.id == sample_id:
            c.sample.duration = new_duration
            c.length_label.setText(f"{new_duration:.1f}s")
            entry = reserve_entry_from_sample(c.sample, source_kind="history")
            apply_status_badge(c.status_label, entry.status)
            c.status_label.setVisible(True)
