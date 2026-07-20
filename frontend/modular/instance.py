# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Etat serialisable d'une INSTANCE de module (un outil ouvert : une reserve,
#   une waveform, un stem lab...). Distinct du WIDGET runtime, garde en vie
#   par le WindowManager.
# - Sert a la sauvegarde/restauration de session (workspace).
#
# CHAMPS
# - instance_id  : identifiant unique stable (ex "waveform_001")
# - module_type  : type de module (ex "reserve", "waveform")
# - title        : titre affiche / editable
# - artifact_ids : artefacts charges dans l'instance
# - visible      : fenetre visible ou masquee (contenu reste charge)
# - geometry     : {"x","y","width","height"} pour restaurer la fenetre
#
# LIENS CLES
# - frontend/modular/window_manager.py : cree et pilote les instances
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModuleInstance:
    """Etat persistable d'une instance de module (sans le widget runtime)."""

    instance_id: str
    module_type: str
    title: str
    artifact_ids: list[str] = field(default_factory=list)
    visible: bool = True
    geometry: dict | None = None  # {"x","y","width","height"}
    state: dict = field(default_factory=dict)  # etat specifique au module

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "module_type": self.module_type,
            "title": self.title,
            "artifact_ids": list(self.artifact_ids),
            "visible": bool(self.visible),
            "geometry": dict(self.geometry) if self.geometry else None,
            "state": dict(self.state) if self.state else {},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleInstance":
        geom = data.get("geometry")
        if isinstance(geom, dict):
            try:
                geom = {
                    "x": int(geom["x"]),
                    "y": int(geom["y"]),
                    "width": int(geom["width"]),
                    "height": int(geom["height"]),
                }
            except (KeyError, TypeError, ValueError):
                geom = None
        else:
            geom = None
        raw_state = data.get("state")
        state = dict(raw_state) if isinstance(raw_state, dict) else {}
        return cls(
            instance_id=str(data["instance_id"]),
            module_type=str(data["module_type"]),
            title=str(data.get("title") or data["module_type"]),
            artifact_ids=[str(a) for a in (data.get("artifact_ids") or [])],
            visible=bool(data.get("visible", True)),
            geometry=geom,
            state=state,
        )
