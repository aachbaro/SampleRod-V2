# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Enregistre les TYPES de modules concrets dans un ModuleRegistry.
# - Point unique ou l'on branche un outil existant (widget autonome) dans
#   l'atelier modulaire, via une factory.
#
# AJOUTER UN MODULE
# - Ecrire une factory(ctx) -> QWidget (ctx : app_context, directory_service,
#   window_manager) et l'enregistrer avec un ModuleType.
#
# LIENS CLES
# - frontend/reserve/reserve_pane.py : ReservePane (1er module branche)
# -----------------------------------------------------------------------------

from __future__ import annotations

from .module_registry import ModuleRegistry, ModuleType


def _reserve_factory(ctx):
    # Import local : evite de charger les modules lourds tant qu'aucune
    # instance n'est creee (et allege les tests unitaires du manager).
    from frontend.reserve.reserve_pane import ReservePane

    return ReservePane(
        directory_service=ctx.directory_service,
        app_context=ctx.app_context,
    )


def build_default_registry() -> ModuleRegistry:
    """Registre des modules disponibles dans l'atelier modulaire (v1)."""
    registry = ModuleRegistry()
    registry.register(
        ModuleType(
            type_id="reserve",
            label="Reserve",
            category="RESERVES",
            icon="folder",
            factory=_reserve_factory,
            default_title="Reserve principale",
            multi=True,
        )
    )
    return registry
