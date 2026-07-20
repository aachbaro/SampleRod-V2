# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'etat de selection (checkbox) d'une SampleCard.
# - Met a jour la propriete QSS "checked" et emet selectionChanged.
#
# FONCTIONS (sommaire)
# - SampleCardSelection          : controleur de selection
# - on_checkbox_toggled(checked) : met a jour isChecked + emet selectionChanged
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py        : selectionChanged signal
# - frontend/sample_gui/sample/sample_list_selection.py : recepteur du signal
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

logger = logging.getLogger("sample_card")


class SampleCardSelection:
    """Controleur de la checkbox de selection sur une SampleCard."""

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
