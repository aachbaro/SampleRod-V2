# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fichier d'index du paquet backend.models : il permet d'ecrire
#   "from backend.models import Sample" au lieu du chemin complet.
# - Particularite : les imports sont "paresseux" (lazy). Le vrai module n'est
#   charge qu'au moment ou on demande le nom (via __getattr__), ce qui evite
#   de charger toute la chaine (SQLAlchemy, services...) trop tot au demarrage.
#
# FONCTIONS (sommaire)
# - __getattr__() : appele par Python quand un nom n'est pas trouve ici ;
#   charge alors le module concerne et renvoie la classe demandee.
# -----------------------------------------------------------------------------

from __future__ import annotations

__all__ = ("Base", "Sample", "SampleBank", "AppContext")


def __getattr__(name: str):
    """Charge a la demande les classes exposees par backend.models."""
    if name == "Base":
        from backend.db import Base

        return Base
    if name == "Sample":
        from backend.models.sample import Sample

        return Sample
    if name == "SampleBank":
        from backend.models.SampleLibrary import SampleBank

        return SampleBank
    if name == "AppContext":
        from backend.models.AppContext import AppContext

        return AppContext
    raise AttributeError(f"module 'backend.models' has no attribute {name!r}")
