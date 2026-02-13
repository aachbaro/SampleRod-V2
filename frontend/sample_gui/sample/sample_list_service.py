# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Wrap des commandes simples vers SampleService (delete/rename/move).
# -----------------------------------------------------------------------------

from __future__ import annotations


class SampleListServiceActions:
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
