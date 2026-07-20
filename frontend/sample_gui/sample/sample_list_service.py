# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Wrapper mince autour du SampleStore pour les actions CRUD basiques.
# - Isole SampleListWidget des appels directs au store (facade).
#
# FONCTIONS (sommaire)
# - SampleListServiceActions  : controleur d'actions CRUD
# - delete_sample(id)         : supprime le sample (FS + DB)
# - rename_sample(id, name)   : renomme le fichier + met a jour la DB
# - move_sample(id, folder)   : deplace le fichier vers un autre dossier
# - concat_with_previous(id)  : concatene ce sample avec le precedent
# - dismiss_concat(id)        : annule une proposition de concatenation
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py   : SampleListWidget (widget parent)
# - backend/models/SampleLibrary.py             : SampleStore (sample_store)
# -----------------------------------------------------------------------------

from __future__ import annotations


class SampleListServiceActions:
    """Controleur facade pour les actions CRUD de SampleListWidget."""

    def __init__(self, widget):
        self.widget = widget

    def delete_sample(self, sample_id: int):
        self.widget.sample_store.delete(sample_id)

    def rename_sample(self, sample_id: int, new_name: str):
        self.widget.sample_store.rename(sample_id, new_name)

    def move_sample(self, sample_id: int, target_folder: str):
        self.widget.sample_store.move(sample_id, target_folder)

    def concat_with_previous(self, sample_id: int):
        self.widget.sample_store.concat_with_previous(sample_id)

    def dismiss_concat(self, sample_id: int):
        self.widget.sample_store.dismiss_concat(sample_id)
