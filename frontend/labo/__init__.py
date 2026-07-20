# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Index du paquet "labo" (l'onglet Labo : outils d'experimentation audio).
#   Permet d'importer les widgets principaux directement depuis frontend.labo.
# -----------------------------------------------------------------------------

"""Labo widgets and artifact helpers."""

from .artifact_tray import ArtifactTrayWidget
from .bins_panel import LaboBinsPanel
from .lab_artifact import LabArtifact
from .labo_widget import LaboWidget
from .stem_separator_tool import StemSeparatorToolWidget
from .waveform_tool import WaveformToolWidget

__all__ = [
    "ArtifactTrayWidget",
    "LaboBinsPanel",
    "LabArtifact",
    "LaboWidget",
    "StemSeparatorToolWidget",
    "WaveformToolWidget",
]
