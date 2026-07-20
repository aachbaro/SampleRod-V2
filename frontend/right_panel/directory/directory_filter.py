# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe les filtres Reserve du DirectoryWidget.
# - Isole recherche texte, filtre de statut et filtre de gammes compatibles.
#
# CE QUI EST COUVERT
# - set_reserve_query()          : recherche texte simple.
# - set_reserve_status_filter()  : filtre de statut.
# - set_compatible_scales_filter(): filtre "compatibles avec".
# - clear_compatible_scales_filter() / on_find_compatibles_requested()
# - _sample_by_id() / _sync_compat_filter_ui() : helpers UI associes.
# -----------------------------------------------------------------------------
#
# LIENS CLES
# - directory_widget.py : facade et signaux Qt.
# - directory_index.py  : construit les ReserveEntry utilises ici.
# -----------------------------------------------------------------------------

from __future__ import annotations


class DirectoryFilterController:
    """Gere les filtres de Reserve appliques au navigateur de dossiers."""

    def __init__(self, widget):
        self.widget = widget

    def set_reserve_query(self, query: str) -> None:
        query = (query or "").strip()
        if query == self.widget._reserve_query_text:
            return
        self.widget._reserve_query_text = query
        self.widget.refresh_list()

    def set_reserve_status_filter(self, status_filter: str) -> None:
        status_filter = status_filter or "all"
        if status_filter == self.widget._reserve_status_filter:
            return
        self.widget._reserve_status_filter = status_filter
        self.widget.refresh_list()

    def set_compatible_scales_filter(self, sample_id: int | None) -> None:
        if sample_id is None:
            if self.widget._compat_filter_sample_id is None and not self.widget._compat_filter_scales:
                return
            self.widget._compat_filter_sample_id = None
            self.widget._compat_filter_scales = set()
            self._sync_compat_filter_ui()
            self.widget.compatFilterChanged.emit(0)
            self.widget.refresh_list()
            return

        sample = self._sample_by_id(sample_id)
        if sample is None:
            return

        entry = self.widget._build_reserve_entry(
            getattr(sample, "path", "") or "",
            sample_id=sample_id,
        )
        scales = set(entry.compatible_scales)
        if not scales:
            return
        if (
            self.widget._compat_filter_sample_id == int(sample_id)
            and self.widget._compat_filter_scales == scales
        ):
            return

        self.widget._compat_filter_sample_id = int(sample_id)
        self.widget._compat_filter_scales = scales
        self._sync_compat_filter_ui()
        self.widget.compatFilterChanged.emit(int(sample_id))
        self.widget.refresh_list()

    def clear_compatible_scales_filter(self) -> None:
        self.set_compatible_scales_filter(None)

    def on_find_compatibles_requested(self, sample_id: int) -> None:
        self.set_compatible_scales_filter(sample_id)

    def _sample_by_id(self, sample_id: int):
        try:
            samples = self.widget.app_context.sample_store.get_cached()
        except Exception:
            return None
        return next(
            (
                sample
                for sample in samples
                if int(getattr(sample, "id", -1)) == int(sample_id)
            ),
            None,
        )

    def _sync_compat_filter_ui(self) -> None:
        if self.widget.embedded_in_reserve:
            self.widget.compat_filter_row.setVisible(False)
            return
        if self.widget._compat_filter_sample_id is None or not self.widget._compat_filter_scales:
            self.widget.compat_filter_row.setVisible(False)
            self.widget.compat_filter_label.setText("")
            return
        sample = self._sample_by_id(self.widget._compat_filter_sample_id)
        note = (
            str(getattr(sample, "detected_scale_label", "") or "").strip()
            if sample is not None
            else ""
        )
        if not note and sample is not None:
            note = str(getattr(sample, "dominant_note", "") or "").strip()
        name = str(getattr(sample, "name", "") or "").strip() if sample is not None else ""
        label_name = note or name or f"#{self.widget._compat_filter_sample_id}"
        self.widget.compat_filter_label.setText(f"Compatibles avec : {label_name}")
        self.widget.compat_filter_row.setVisible(True)
