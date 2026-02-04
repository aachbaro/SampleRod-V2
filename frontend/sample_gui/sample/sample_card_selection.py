# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gère l'état de sélection (checkbox) d'une SampleCard.
# - Met à jour le style visuel et émet le signal vers le parent.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

logger = logging.getLogger("sample_card")


class SampleCardSelection:
    def __init__(self, card):
        self.card = card

    def on_checkbox_toggled(self, checked: bool):
        """
        :param checked: True si la case est cochée, False si elle vient d'être décochée.
        """
        c = self.card
        c.isChecked = checked
        c.selectionChanged.emit(c.sample.id, checked)
        logger.info(
            f"Checkbox toggled: {c.sample.id} is now {'checked' if checked else 'unchecked'}"
        )
        c.setProperty("checked", checked)
        c.style().unpolish(c)
        c.style().polish(c)
