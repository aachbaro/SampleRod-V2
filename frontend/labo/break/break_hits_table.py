# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique du tableau de hits du BreakWidget.
# - Isole selection, relabel manuel, suppression de hit et reconstruction du
#   resultat d'analyse apres edition humaine.
#
# LIENS CLES
# - frontend/labo/break/hit_row.py : ligne UI unitaire.
# - frontend/sample_gui/waveform/waveform_plot_helpers.py : region de selection.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from dataclasses import replace

import pyqtgraph as pg

from frontend.sample_gui.waveform.waveform_plot_helpers import ContextMenuLinearRegionItem

from .hit_row import _HitRow


class BreakHitsTableController:
    """Gere le tableau de hits et les editions manuelles du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def _on_hit_selected(self, hit_index: int) -> None:
        self.widget._selected_hit_index = hit_index
        for row in self.widget._hit_rows:
            row.set_selected(row.drum_slice.index == hit_index)

        if self.widget._analysis_result is None:
            return
        ds = next(
            (s for s in self.widget._analysis_result.slices if s.index == hit_index),
            None,
        )
        if ds is None:
            return

        start_s = float(ds.start_s)
        end_s = float(ds.end_s)
        w = self.widget._waveform_widget
        if w is None:
            return

        try:
            if w.region is not None:
                w.plot.removeItem(w.region)
                w.region = None
        except Exception:
            pass
        try:
            region = ContextMenuLinearRegionItem(
                [start_s, end_s],
                brush=pg.mkBrush(255, 255, 255, 35),
                pen=pg.mkPen("#4bb6b7", width=1),
            )
            region.setZValue(1)
            region.setBounds([0, float(w.duration or end_s)])
            region.sigRegionChangeFinished.connect(w.on_region_changed)
            region._parent = w
            w.plot.addItem(region)
            w.region = region
        except Exception:
            pass

        padding = max(0.08, (end_s - start_s) * 0.6)
        try:
            w.plot.setXRange(
                max(0.0, start_s - padding),
                min(float(w.duration or end_s + padding), end_s + padding),
                padding=0,
            )
        except Exception:
            pass

        try:
            w.play_start = start_s
            w.play_end = end_s
            w.read_head.setPos(start_s)
            w.play_audio(start_s)
        except Exception:
            pass

    def _inspect_slice(self, hit_index: int) -> None:
        """Bascule sur Decoupage et met la slice `hit_index` sous les yeux."""
        row = next(
            (r for r in self.widget._hit_rows if int(r.drum_slice.index) == int(hit_index)),
            None,
        )
        if row is None:
            self.widget.status_label.setText(
                f"Slice {hit_index} introuvable : relance l'analyse du break."
            )
            return
        self.widget._on_tab_clicked(0)
        self._on_hit_selected(int(hit_index))
        self.widget._hits_scroll.ensureWidgetVisible(row, 0, 40)
        self.widget.status_label.setText(
            f"Slice {hit_index} ({row.get_label().replace('_', ' ')}) : "
            "change sa classe puis regenere le break."
        )

    def _rebuild_hits_table(self, result) -> None:
        self._clear_hits_table()
        self.widget._selected_hit_index = None
        has_slices = bool(result.slices)
        self.widget._empty_label.setVisible(not has_slices)
        self.widget._hits_scroll.setVisible(has_slices)
        # Les slices sont decoupees dans l'audio ANALYSE : si la waveform a ete
        # editee, c'est le WAV temporaire, pas le fichier d'origine.
        slice_source = result.source_path or self.widget._working_path or self.widget._current_path or ""
        for ds in result.slices:
            row = _HitRow(ds, slice_source, self.widget.hits_container)
            row.selected.connect(self.widget._on_hit_selected)
            row.removeRequested.connect(self.widget._on_hit_remove_requested)
            row.labelChanged.connect(self.widget._on_hit_label_changed)
            row.dragStarted.connect(lambda: setattr(self.widget, "_internal_drag_active", True))
            row.dragFinished.connect(lambda: setattr(self.widget, "_internal_drag_active", False))
            self.widget._hit_rows.append(row)
            self.widget.hits_vbox.insertWidget(self.widget.hits_vbox.count() - 1, row)

    def _clear_hits_table(self) -> None:
        for row in self.widget._hit_rows:
            self.widget.hits_vbox.removeWidget(row)
            row.deleteLater()
        self.widget._hit_rows = []

    def _commit_manual_analysis_update(
        self,
        updated_slices,
        *,
        status_message: str | None = None,
    ) -> None:
        if self.widget._analysis_result is None:
            return
        raw_result = getattr(self.widget._analysis_result, "prototype_result", None)
        normalized_slices = tuple(
            replace(drum_slice, index=index)
            for index, drum_slice in enumerate(updated_slices, start=1)
        )
        updated_raw_result = raw_result
        if raw_result is not None:
            try:
                raw_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
                old_index_to_slice = {
                    int(original_slice.index): normalized_slice
                    for original_slice, normalized_slice in zip(updated_slices, normalized_slices)
                }
                normalized_hits = []
                for raw_hit in raw_hits:
                    target_slice = old_index_to_slice.get(int(getattr(raw_hit, "index", -1)))
                    if target_slice is None:
                        continue
                    normalized_hits.append(
                        replace(
                            raw_hit,
                            index=int(target_slice.index),
                            start_s=float(target_slice.start_s),
                            end_s=float(target_slice.end_s),
                            label=str(target_slice.label),
                            confidence=float(target_slice.confidence),
                            secondary_labels=tuple(target_slice.secondary_labels),
                            layer_score=float(target_slice.layer_score),
                            role=str(target_slice.role),
                            rhythmic_position=str(target_slice.rhythmic_position),
                        )
                    )
                updated_raw_result = replace(
                    raw_result,
                    onset_count=len(normalized_hits),
                    transient_hits=tuple(normalized_hits),
                    hit_sequences=(),
                )
            except Exception:
                updated_raw_result = None
        updated_result = replace(
            self.widget._analysis_result,
            onset_count=len(normalized_slices),
            slices=normalized_slices,
            prototype_result=updated_raw_result,
        )
        self._commit_updated_result(
            updated_result, status_message=status_message, rebuild_rows=False
        )

    def _commit_updated_result(
        self,
        updated_result,
        *,
        status_message: str | None = None,
        rebuild_rows: bool = True,
    ) -> None:
        """Installe un resultat deja construit et propage aux consommateurs.

        `rebuild_rows=False` quand l'appelant a deja mis la liste a jour lui-
        meme (un simple changement de label, par exemple).
        """
        self.widget._analysis_result = updated_result
        if rebuild_rows:
            self._rebuild_hits_table(updated_result)
        self.widget._refresh_quantized_projection()
        self.widget.generator_panel.set_analysis_result(updated_result)
        self.widget._break_service.cache_result(updated_result)
        if status_message:
            self.widget.status_label.setText(status_message)
        self.widget._refresh_actions()

    def _on_hit_label_changed(self, hit_index: int, new_label: str) -> None:
        result = self.widget._analysis_result
        if result is None:
            return
        # La correction est memorisee sur le disque, indexee par la POSITION
        # du hit : elle survit donc a un redecoupage et aux sessions suivantes
        # (une analyse re-classe tout, sans ca on repartait de zero).
        target = next(
            (s for s in result.slices if int(s.index) == int(hit_index)),
            None,
        )
        if target is not None:
            self.widget._break_service.set_manual_label(
                result.source_path, float(target.start_s), new_label
            )
        updated_slices = tuple(
            replace(drum_slice, label=new_label)
            if int(drum_slice.index) == int(hit_index)
            else drum_slice
            for drum_slice in result.slices
        )
        self._commit_manual_analysis_update(
            updated_slices,
            status_message=(
                f"Hit {hit_index} reclasse en {new_label}. "
                "Correction memorisee : elle sera reappliquee aux prochaines analyses."
            ),
        )
        self.widget._refresh_manual_label_action()

    def _reset_manual_labels(self) -> None:
        """Oublie les corrections de classe et relance une classification propre."""
        path = self.widget._current_path
        if not path:
            return
        self.widget._break_service.clear_manual_labels(path)
        self.widget._refresh_manual_label_action()
        self.widget.status_label.setText(
            "Corrections de classe oubliees. Relance l'analyse des slices "
            "pour revenir a la classification automatique."
        )

    def _on_hit_remove_requested(self, hit_index: int) -> None:
        """Retirer une slice la FUSIONNE avec sa voisine de gauche.

        Retirer le marqueur de debut d'une slice, c'est dire « cette coupe
        n'aurait pas du exister » : la precedente reprend donc le territoire
        libere et garde sa classe, au lieu de laisser un trou dans le break.
        """
        result = self.widget._analysis_result
        if result is None:
            return
        ds = next((s for s in result.slices if s.index == hit_index), None)
        if ds is None:
            return

        merged = self.widget._break_service.merge_slice_into_previous(result, int(hit_index))
        if merged is None:
            self.widget.status_label.setText(
                "Fusion impossible : il ne reste qu'une slice."
            )
            return

        w = self.widget._waveform_widget
        if w is not None:
            try:
                w.remove_marker(float(ds.start_s))
            except Exception:
                pass
        if self.widget._selected_hit_index == hit_index:
            self.widget._selected_hit_index = None
        # Le hit disparait : sa correction de classe n'a plus d'objet et ne
        # doit pas se recoller a un futur hit voisin.
        self.widget._break_service.drop_manual_label(result.source_path, float(ds.start_s))

        neighbour = "la precedente" if int(hit_index) > 1 else "la suivante"
        self._commit_updated_result(
            merged,
            status_message=(
                f"Slice {hit_index} fusionnee avec {neighbour} "
                f"({len(merged.slices)} slices restantes)."
            ),
        )
        self.widget._refresh_manual_label_action()

    def _on_marker_moved(self, from_s: float, to_s: float) -> None:
        """Deplacer un marqueur recale la frontiere des deux slices voisines.

        Les corrections de classe suivent le marqueur, sinon celle posee sur
        l'ancienne position se recollerait au mauvais hit.
        """
        result = self.widget._analysis_result
        if result is None or not result.slices:
            return
        audio_path = result.source_path or self.widget._working_path or self.widget._current_path
        updated = self.widget._break_service.move_slice_boundary(
            result, float(from_s), float(to_s), source_path=audio_path
        )
        if updated is None:
            return
        service = self.widget._break_service
        overrides = service.load_manual_labels(result.source_path)
        moved_label = service._nearest_override_key(overrides, float(from_s))
        if moved_label is not None:
            service.drop_manual_label(result.source_path, float(from_s))
            service.set_manual_label(result.source_path, float(to_s), overrides[moved_label])
        self._commit_updated_result(
            updated,
            status_message=(
                f"Frontiere deplacee de {from_s:.3f}s a {to_s:.3f}s, "
                "slices voisines reclassees."
            ),
        )

    def _on_marker_added(self, position_s: float) -> None:
        """Un marqueur pose = une slice coupee en deux, reclassees sur place.

        Pas de re-analyse complete : seules les deux moities sont mesurees,
        et la nouvelle slice s'insere au bon rang dans la liste.
        """
        result = self.widget._analysis_result
        if result is None or not result.slices:
            return
        audio_path = result.source_path or self.widget._working_path or self.widget._current_path
        updated = self.widget._break_service.split_slice_at(
            result, float(position_s), source_path=audio_path
        )
        if updated is None:
            return
        new_slice = next(
            (s for s in updated.slices if abs(float(s.start_s) - float(position_s)) < 1e-6),
            None,
        )
        label = new_slice.label.replace("_", " ") if new_slice is not None else "?"
        self._commit_updated_result(
            updated,
            status_message=(
                f"Slice ajoutee a {position_s:.3f}s, detectee comme {label} "
                f"({len(updated.slices)} slices)."
            ),
        )

    def _clear_analysis(self) -> None:
        current_preview = self.widget._quantized_preview_path
        if current_preview:
            current_audio = os.path.normcase(
                os.path.normpath(self.widget.app_context.audio_player.current_sample_path or "")
            )
            if current_audio == os.path.normcase(os.path.normpath(current_preview)):
                try:
                    self.widget.app_context.audio_player.clear_audio()
                except Exception:
                    pass
        self.widget._analysis_result = None
        self.widget._quantized_slices = ()
        self.widget._quantize_request_mode = None
        self.widget._quantized_preview_signature = None
        self.widget._quantized_preview_path = ""
        self.widget._quantized_preview_duration_s = 0.0
        self.widget._pending_cached_result = None
        self.widget._selected_hit_index = None
        self._clear_hits_table()
        self.widget.generator_panel.set_analysis_result(None)
        self.widget._update_header_meta()
        self.widget._update_slices_label()
        self.widget._empty_label.setVisible(True)
        self.widget._hits_scroll.setVisible(False)
        self.widget._refresh_actions()
