# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere les mises a jour d'affichage "statiques" d'une SampleCard.
# - Rafraichit nom, duree et badge de statut sans toucher a la logique metier.
#
# FONCTIONS (sommaire)
# - SampleCardStatus            : controleur d'etat d'affichage
# - refresh_display()           : met a jour name_label, length_label, status_label
# - on_duration_changed(id, s)  : slot du SampleStore -> rafraichit duree + badge
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py : carte parente
# - frontend/reserve/__init__.py              : apply_status_badge / reserve_entry_from_sample
# -----------------------------------------------------------------------------

from __future__ import annotations

from frontend.reserve import (
    apply_status_badge,
    format_reserve_clock_duration,
    reserve_entry_from_sample,
)


class SampleCardStatus:
    """Controleur des mises a jour d'affichage statiques (nom, duree, badge)."""

    def __init__(self, card):
        self.card = card

    def refresh_display(self):
        """Met a jour nom, duree et badge de statut depuis sample.name / sample.duration."""
        c = self.card
        c._recent_full_name = str(c.sample.name)
        c.name_label.setText(c._recent_full_name)
        c.length_label.setText(
            format_reserve_clock_duration(c.sample.duration)
        )
        entry = reserve_entry_from_sample(c.sample, source_kind="history")
        apply_status_badge(c.status_label, entry.status)
        status_value = str(getattr(entry.status, "value", entry.status))
        c.status_label.setVisible(status_value != "normal")
        c.play_button.setEnabled(entry.capabilities.can_preview)

    def on_duration_changed(self, sample_id, new_duration: float):
        """Slot du SampleStore: met a jour la duree et le badge de statut."""
        c = self.card
        if c.sample.id == sample_id:
            c.sample.duration = new_duration
            c.length_label.setText(
                format_reserve_clock_duration(new_duration)
            )
            entry = reserve_entry_from_sample(c.sample, source_kind="history")
            apply_status_badge(c.status_label, entry.status)
            status_value = str(getattr(entry.status, "value", entry.status))
            c.status_label.setVisible(status_value != "normal")
            c.play_button.setEnabled(entry.capabilities.can_preview)
