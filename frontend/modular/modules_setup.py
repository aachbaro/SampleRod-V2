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


def _waveform_factory(ctx):
    from .waveform_module import WaveformModule

    return WaveformModule(ctx.app_context)


def _stems_factory(ctx):
    from frontend.labo.stem_separator_tool import StemSeparatorToolWidget

    return StemSeparatorToolWidget(ctx.app_context)


def _artifacts_factory(ctx):
    from .artifact_module import ArtifactModule

    return ArtifactModule(ctx.app_context)


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
    registry.register(
        ModuleType(
            type_id="waveform",
            label="Waveform",
            category="WAVEFORMS",
            icon="wave",
            factory=_waveform_factory,
            default_title="Waveform",
            multi=True,
        )
    )
    registry.register(
        ModuleType(
            type_id="stems",
            label="Stem Lab",
            category="STEM LABS",
            icon="layers",
            factory=_stems_factory,
            default_title="Stem Lab",
            multi=True,
        )
    )
    registry.register(
        ModuleType(
            type_id="artifacts",
            label="Artefacts",
            category="ARTEFACTS",
            icon="box",
            factory=_artifacts_factory,
            default_title="Artefacts",
            multi=False,
            workspace_creatable=False,
            renamable=False,
            duplicable=False,
            closable=False,
        )
    )
    return registry
