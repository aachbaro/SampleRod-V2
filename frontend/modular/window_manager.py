# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Controleur central de l'atelier modulaire (le "gestionnaire de fenetres").
# - Cree/affiche/masque/ferme/renomme/duplique les instances de modules ;
#   garde la liste, emet des signaux pour la fenetre Workspace ; sauvegarde et
#   restaure la session (workspace).
#
# SIGNAUX
# - instancesChanged()        : la liste a change (ajout/suppression)
# - instanceUpdated(str id)   : titre/visibilite d'une instance a change
#
# LIENS CLES
# - frontend/modular/module_registry.py : catalogue des types
# - frontend/modular/module_window.py   : fenetres top-level (hide-on-close)
# - frontend/modular/instance.py        : etat serialisable
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from .instance import ModuleInstance
from .module_registry import ModuleRegistry, ModuleType
from .module_window import ModuleWindow


@dataclass
class ModuleContext:
    """Contexte passe aux factories de modules."""

    app_context: object
    directory_service: object
    window_manager: "WindowManager"


class WindowManager(QObject):
    """Gestionnaire central des instances de modules et de leurs fenetres."""

    instancesChanged = Signal()
    instanceUpdated = Signal(str)

    def __init__(self, app_context, directory_service, registry: ModuleRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._context = ModuleContext(
            app_context=app_context,
            directory_service=directory_service,
            window_manager=self,
        )
        self._instances: dict[str, ModuleInstance] = {}
        self._windows: dict[str, ModuleWindow] = {}
        self._counters: dict[str, int] = {}
        self._companions: list[QWidget] = []  # fenetres hors-module (Workspace)
        self._raising = False                 # garde anti-recursion group raise

    # -- Lecture ------------------------------------------------------------
    @property
    def context(self) -> ModuleContext:
        return self._context

    @property
    def registry(self) -> ModuleRegistry:
        return self._registry

    def instances(self) -> list[ModuleInstance]:
        return list(self._instances.values())

    def get_instance(self, instance_id: str) -> ModuleInstance | None:
        return self._instances.get(instance_id)

    def is_visible(self, instance_id: str) -> bool:
        win = self._windows.get(instance_id)
        return bool(win is not None and win.isVisible())

    def instances_by_category(self) -> dict[str, list[ModuleInstance]]:
        """Instances regroupees par categorie, dans l'ordre du registre."""
        grouped: dict[str, list[ModuleInstance]] = {
            cat: [] for cat in self._registry.categories()
        }
        for inst in self._instances.values():
            if self._registry.has(inst.module_type):
                cat = self._registry.get(inst.module_type).category
                grouped.setdefault(cat, []).append(inst)
        return grouped

    # -- Cycle de vie -------------------------------------------------------
    def create_instance(
        self,
        module_type: str,
        *,
        title: str | None = None,
        artifact_ids: list[str] | None = None,
        show: bool = True,
        instance_id: str | None = None,
        geometry: dict | None = None,
        visible: bool | None = None,
    ) -> str:
        mt = self._registry.get(module_type)
        if instance_id is None:
            instance_id = self._next_id(module_type)
        inst = ModuleInstance(
            instance_id=instance_id,
            module_type=module_type,
            title=title or self._auto_title(mt),
            artifact_ids=list(artifact_ids or []),
            visible=bool(show if visible is None else visible),
            geometry=geometry,
        )
        self._instances[instance_id] = inst
        self._build_window(inst)
        if inst.visible:
            self._show_window(inst)
        self.instancesChanged.emit()
        return instance_id

    def show_instance(self, instance_id: str) -> None:
        inst = self._instances.get(instance_id)
        if inst is None:
            return
        self._show_window(inst)
        self.instanceUpdated.emit(instance_id)

    def hide_instance(self, instance_id: str) -> None:
        inst = self._instances.get(instance_id)
        win = self._windows.get(instance_id)
        if inst is None or win is None:
            return
        inst.geometry = win.current_geometry()
        inst.visible = False
        win.hide()
        self.instanceUpdated.emit(instance_id)

    def toggle_instance(self, instance_id: str) -> None:
        if self.is_visible(instance_id):
            self.hide_instance(instance_id)
        else:
            self.show_instance(instance_id)

    def close_instance(self, instance_id: str) -> None:
        inst = self._instances.pop(instance_id, None)
        win = self._windows.pop(instance_id, None)
        if win is not None:
            win.windowHidden.disconnect(self._on_window_hidden)
            win.setCentralWidget(QWidget())  # detache le widget module
            win.deleteLater()
        if inst is not None:
            self.instancesChanged.emit()

    def rename_instance(self, instance_id: str, title: str) -> None:
        inst = self._instances.get(instance_id)
        if inst is None:
            return
        title = (title or "").strip()
        if not title or title == inst.title:
            return
        inst.title = title
        win = self._windows.get(instance_id)
        if win is not None:
            win.set_title(title)
        self.instanceUpdated.emit(instance_id)

    def duplicate_instance(self, instance_id: str) -> str | None:
        inst = self._instances.get(instance_id)
        if inst is None:
            return None
        return self.create_instance(
            inst.module_type,
            title=f"{inst.title} (copie)",
            artifact_ids=list(inst.artifact_ids),
            show=True,
        )

    # -- Session ------------------------------------------------------------
    def save_session(self) -> dict:
        for inst in self._instances.values():
            win = self._windows.get(inst.instance_id)
            if win is not None and win.isVisible():
                inst.geometry = win.current_geometry()
        return {"instances": [inst.to_dict() for inst in self._instances.values()]}

    def restore_session(self, data: dict) -> None:
        self.clear()
        for raw in (data or {}).get("instances", []):
            try:
                inst = ModuleInstance.from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if not self._registry.has(inst.module_type):
                continue
            self.create_instance(
                inst.module_type,
                title=inst.title,
                artifact_ids=inst.artifact_ids,
                show=inst.visible,
                instance_id=inst.instance_id,
                geometry=inst.geometry,
                visible=inst.visible,
            )
            self._bump_counter(inst.instance_id)

    def clear(self) -> None:
        for instance_id in list(self._instances.keys()):
            self.close_instance(instance_id)
        self._counters.clear()

    # -- Groupe de fenetres / mode d'affichage ------------------------------
    def add_companion(self, window: QWidget) -> None:
        """Ajoute une fenetre hors-module (ex: Workspace) au groupe remonte."""
        if window not in self._companions:
            self._companions.append(window)

    def raise_group(self, active_window: QWidget | None = None) -> None:
        """Remonte toutes les fenetres visibles ensemble (comme une seule).

        La fenetre active est remontee en dernier pour rester au-dessus.
        Un verrou evite toute recursion via les evenements d'activation.
        """
        if self._raising:
            return
        self._raising = True
        try:
            group: list[QWidget] = []
            for inst in self._instances.values():
                if not inst.visible:
                    continue
                win = self._windows.get(inst.instance_id)
                if win is not None and win.isVisible():
                    group.append(win)
            group.extend(c for c in self._companions if c.isVisible())
            for win in group:
                if win is not active_window:
                    win.raise_()
            if active_window is not None:
                active_window.raise_()
        finally:
            self._raising = False

    def suspend(self) -> None:
        """Masque les fenetres visibles SANS changer leur etat 'visible'.

        Utilise pour basculer vers l'affichage classique sans perdre la
        composition en cours.
        """
        for inst in self._instances.values():
            win = self._windows.get(inst.instance_id)
            if win is not None and inst.visible:
                win.hide()

    def resume(self) -> None:
        """Re-affiche les fenetres dont l'instance est marquee visible."""
        for inst in self._instances.values():
            win = self._windows.get(inst.instance_id)
            if win is not None and inst.visible:
                win.show()

    def _on_window_activated(self, instance_id: str) -> None:
        self.raise_group(active_window=self._windows.get(instance_id))

    # -- Interne ------------------------------------------------------------
    def _build_window(self, inst: ModuleInstance) -> ModuleWindow:
        mt = self._registry.get(inst.module_type)
        widget = mt.factory(self._context)
        win = ModuleWindow(inst.instance_id, inst.title, widget)
        win.windowHidden.connect(self._on_window_hidden)
        win.activated.connect(self._on_window_activated)
        win.apply_geometry(inst.geometry)
        self._windows[inst.instance_id] = win
        self._connect_module_signals(inst, widget)
        return win

    def _show_window(self, inst: ModuleInstance) -> None:
        win = self._windows.get(inst.instance_id)
        if win is None:
            win = self._build_window(inst)
        win.apply_geometry(inst.geometry)
        win.show()
        win.raise_()
        win.activateWindow()
        inst.visible = True

    def _on_window_hidden(self, instance_id: str) -> None:
        # La croix a masque la fenetre : on met a jour l'etat.
        inst = self._instances.get(instance_id)
        win = self._windows.get(instance_id)
        if inst is None or win is None:
            return
        inst.geometry = win.current_geometry()
        inst.visible = False
        self.instanceUpdated.emit(instance_id)

    def _connect_module_signals(self, inst: ModuleInstance, widget: QWidget) -> None:
        # Cablage inter-modules, etendu au fur et a mesure que les modules
        # rejoignent l'atelier.
        if inst.module_type == "reserve":
            signal = getattr(widget, "sendToLaboRequested", None)
            if signal is not None:
                signal.connect(self._open_paths_in_waveform)

    def _open_paths_in_waveform(self, paths) -> list[str]:
        """Ouvre chaque fichier dans sa propre instance Waveform (une par fichier)."""
        created: list[str] = []
        if not self._registry.has("waveform"):
            return created
        for raw in paths or []:
            path = str(raw or "")
            if not path or not os.path.isfile(path):
                continue
            instance_id = self.create_instance("waveform", title=Path(path).stem)
            widget = self._windows[instance_id].centralWidget()
            opener = getattr(widget, "open_file", None)
            if callable(opener):
                try:
                    opener(path)
                except Exception:
                    pass
            created.append(instance_id)
        return created

    def _auto_title(self, mt: ModuleType) -> str:
        count = sum(
            1 for inst in self._instances.values() if inst.module_type == mt.type_id
        )
        if count == 0:
            return mt.default_title
        return f"{mt.default_title} {count + 1}"

    def _next_id(self, module_type: str) -> str:
        self._counters[module_type] = self._counters.get(module_type, 0) + 1
        candidate = f"{module_type}_{self._counters[module_type]:03d}"
        while candidate in self._instances:
            self._counters[module_type] += 1
            candidate = f"{module_type}_{self._counters[module_type]:03d}"
        return candidate

    def _bump_counter(self, instance_id: str) -> None:
        # Aligne le compteur sur un id restaure du type "waveform_004".
        if "_" not in instance_id:
            return
        module_type, _, suffix = instance_id.rpartition("_")
        if suffix.isdigit():
            self._counters[module_type] = max(
                self._counters.get(module_type, 0), int(suffix)
            )
