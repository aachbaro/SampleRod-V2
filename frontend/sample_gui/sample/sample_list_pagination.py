# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere la pagination de SampleListWidget (page courante, boutons, label).
# - Centralise la logique de navigation et d'arret de lecture hors page.
# -----------------------------------------------------------------------------

from __future__ import annotations


class SampleListPagination:
    def __init__(self, widget):
        self.widget = widget

    def update_label(self, start_idx: int, end_idx: int, total_samples: int):
        self.widget.pagination_label.setText(f"{start_idx} - {end_idx} / {total_samples}")

    def on_samples_per_page_changed(self, count: int):
        self.widget.samples_per_page = count
        self.set_current_page(1)

    def set_current_page(self, page: int):
        if page < 1:
            page = 1
        self.widget.current_page = page
        self.widget.refreshList()

    def change_page(self, page: int):
        # Calcul des IDs de la nouvelle page
        ordered = sorted(self.widget.samples, key=lambda s: s.created_at, reverse=True)
        start = (page - 1) * self.widget.samples_per_page
        end = start + self.widget.samples_per_page
        ids_page = {s.id for s in ordered[start:end]}

        # 1) Stopper les waveforms hors page
        for sid, card in list(self.widget._card_widgets.items()):
            if sid not in ids_page and card.wave_edition_widget:
                try:
                    card.wave_edition_widget.stop_audio()
                except Exception:
                    pass
                try:
                    card.wave_edition_widget.timer.stop()
                except Exception:
                    pass

        # 2) Stopper le player global si besoin
        current_id = self.widget.app_context.audio_player.current_sample_id
        if current_id != -1 and current_id not in ids_page:
            player = self.widget.app_context.audio_player
            if hasattr(player, "stop_playback"):
                try:
                    player.stop_playback()
                except Exception:
                    pass

        self.set_current_page(page)

    def prev_page(self):
        if self.widget.current_page > 1:
            self.change_page(self.widget.current_page - 1)

    def next_page(self):
        max_pages = (len(self.widget.samples) - 1) // self.widget.samples_per_page + 1
        if self.widget.current_page < max_pages:
            self.change_page(self.widget.current_page + 1)
