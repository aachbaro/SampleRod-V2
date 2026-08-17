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
    artifact_store: object | None
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
            artifact_store=getattr(app_context, "lab_artifact_store", None),
            window_manager=self,
        )
        self._instances: dict[str, ModuleInstance] = {}
        self._windows: dict[str, ModuleWindow] = {}
        self._counters: dict[str, int] = {}
        self._companions: list[QWidget] = []  # fenetres hors-module (Workspace)
        # Ordre d'empilement des instances, du DESSOUS vers le DESSUS.
        # Sans lui, raise_group() re-empilait le groupe dans l'ordre de
        # CREATION : la premiere instance creee (la Reserve, en pratique)
        # repassait sous toutes les autres a chaque clic sur une fenetre.
        self._stack_order: list[str] = []
        self._raising = False                 # garde anti-recursion group raise
        self._backdrop = None                 # fond global optionnel
        self._backdrop_enabled = False
        self._grid_overlay_visible = False    # reperage de grille sur le fond
        self._grid_overlay_multiplier = 4     # une ligne tous les 4 pas de snap
        # Controleur spatial : suit la geometrie des fenetres et planifie la
        # persistance. Cree paresseusement pour ne rien changer aux tests qui
        # instancient un WindowManager nu.
        self._layout_manager = None

    # -- Controleur spatial -------------------------------------------------
    @property
    def layout_manager(self):
        """Controleur spatial, cree a la demande.

        Il connait les fenetres ouvertes et leur geometrie ; le WindowManager
        reste seul maitre du cycle de vie des instances.
        """
        if self._layout_manager is None:
            from .layout.layout_manager import WorkspaceLayoutManager

            self._layout_manager = WorkspaceLayoutManager(self, parent=self)
        return self._layout_manager

    # -- Lecture ------------------------------------------------------------
    @property
    def context(self) -> ModuleContext:
        return self._context

    @property
    def registry(self) -> ModuleRegistry:
        return self._registry

    def instances(self) -> list[ModuleInstance]:
        return list(self._instances.values())

    def instances_for_type(self, module_type: str) -> list[ModuleInstance]:
        return [inst for inst in self._instances.values() if inst.module_type == module_type]

    def get_instance(self, instance_id: str) -> ModuleInstance | None:
        return self._instances.get(instance_id)

    def module_type_for_instance(self, instance_id: str) -> ModuleType | None:
        inst = self.get_instance(instance_id)
        if inst is None or not self._registry.has(inst.module_type):
            return None
        return self._registry.get(inst.module_type)

    def is_visible(self, instance_id: str) -> bool:
        win = self._windows.get(instance_id)
        return bool(win is not None and win.isVisible())

    def can_create_instance(self, module_type: str) -> bool:
        if not self._registry.has(module_type):
            return False
        mt = self._registry.get(module_type)
        return mt.multi or not self.instances_for_type(module_type)

    def can_rename_instance(self, instance_id: str) -> bool:
        mt = self.module_type_for_instance(instance_id)
        return bool(mt is not None and mt.renamable)

    def can_duplicate_instance(self, instance_id: str) -> bool:
        mt = self.module_type_for_instance(instance_id)
        return bool(mt is not None and mt.duplicable and mt.multi)

    def can_close_instance(self, instance_id: str) -> bool:
        mt = self.module_type_for_instance(instance_id)
        return bool(mt is not None and mt.closable)

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
        state: dict | None = None,
    ) -> str:
        mt = self._registry.get(module_type)
        if not mt.multi:
            existing = self.instances_for_type(module_type)
            if existing:
                target_id = existing[0].instance_id
                if show or visible:
                    self.show_instance(target_id)
                return target_id
        if instance_id is None:
            instance_id = self._next_id(module_type)
        inst = ModuleInstance(
            instance_id=instance_id,
            module_type=module_type,
            title=title or self._auto_title(mt),
            artifact_ids=list(artifact_ids or []),
            visible=bool(show if visible is None else visible),
            geometry=geometry,
            state=dict(state or {}),
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
        if not self.can_close_instance(instance_id):
            self.hide_instance(instance_id)
            return
        inst = self._instances.pop(instance_id, None)
        win = self._windows.pop(instance_id, None)
        if instance_id in self._stack_order:
            self._stack_order.remove(instance_id)
        # Desenregistrement SYSTEMATIQUE : une fenetre detruite mais toujours
        # connue du controleur deviendrait une cible fantome.
        self.layout_manager.unregister_window(instance_id)
        if win is not None:
            win.windowHidden.disconnect(self._on_window_hidden)
            widget = win.module_widget()
            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass
            win.deleteLater()
        if inst is not None:
            self.instancesChanged.emit()

    def rename_instance(self, instance_id: str, title: str) -> None:
        if not self.can_rename_instance(instance_id):
            return
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
        if not self.can_duplicate_instance(instance_id):
            return None
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
            if win is None:
                continue
            if win.isVisible():
                inst.geometry = win.current_geometry()
            widget = win.module_widget()
            saver = getattr(widget, "save_state", None)
            if callable(saver):
                try:
                    inst.state = dict(saver() or {})
                except Exception:
                    pass
        return {"instances": [inst.to_dict() for inst in self._instances.values()]}

    def restore_session(self, data: dict) -> None:
        # Toute la restauration est encadree : les geometries restaurees ne
        # doivent declencher ni magnetisme, ni re-ecriture immediate.
        with self.layout_manager.restoring_session_guard():
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
                    state=inst.state,
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

    def _touch_stack(self, instance_id: str) -> None:
        """Marque cette instance comme la plus recemment mise au premier plan."""
        if instance_id in self._stack_order:
            self._stack_order.remove(instance_id)
        self._stack_order.append(instance_id)

    def _stack_rank(self, instance_id: str) -> int:
        """Rang d'empilement : plus grand = plus haut. Inconnu = tout en haut."""
        try:
            return self._stack_order.index(instance_id)
        except ValueError:
            return len(self._stack_order)

    def raise_group(self, active_window: QWidget | None = None) -> None:
        """Remonte toutes les fenetres visibles ensemble (comme une seule).

        Le fond global (backdrop) est remonte en PREMIER pour rester sous les
        fenetres tout en passant au-dessus des autres applications. La fenetre
        active est remontee en dernier. Un verrou evite toute recursion via les
        evenements d'activation.

        Les modules sont remontes dans l'ordre d'empilement MEMORISE (le plus
        ancien au premier plan d'abord) et non dans leur ordre de creation :
        sinon la plus vieille instance — la Reserve — repassait derriere tout
        le monde des qu'on cliquait sur une autre fenetre.
        """
        if self._raising:
            return
        self._raising = True
        try:
            if self._backdrop is not None and self._backdrop.isVisible():
                self._backdrop.raise_()
            group: list[QWidget] = []
            for instance_id in sorted(self._instances, key=self._stack_rank):
                inst = self._instances[instance_id]
                if not inst.visible:
                    continue
                win = self._windows.get(instance_id)
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

    # -- Fond global (backdrop) --------------------------------------------
    def set_backdrop_enabled(self, enabled: bool) -> None:
        """Active/desactive l'aplat plein-ecran derriere les fenetres."""
        self._backdrop_enabled = bool(enabled)
        if self._backdrop_enabled:
            if self._backdrop is None:
                from .backdrop import BackdropWindow

                self._backdrop = BackdropWindow(self)
            # Un fond cree apres coup doit retrouver l'etat du reperage.
            self._push_grid_metrics()
            self._backdrop.set_grid_visible(self._grid_overlay_visible)
            self._backdrop.cover_screens()
            self._backdrop.show()
            self._backdrop.lower()
            self.raise_group()
        elif self._backdrop is not None:
            self._backdrop.hide()

    def is_backdrop_enabled(self) -> bool:
        return self._backdrop_enabled

    def set_grid_overlay_visible(self, visible: bool) -> None:
        """Affiche le reperage de grille sur le fond global.

        La grille se dessine SUR le fond : sans lui, il n'y a pas de surface
        pour la porter. On allume donc le fond au besoin, plutot que de
        laisser un bouton sans effet visible.
        """
        visible = bool(visible)
        self._grid_overlay_visible = visible
        if visible and not self._backdrop_enabled:
            self.set_backdrop_enabled(True)
        self._push_grid_metrics()
        if self._backdrop is not None:
            self._backdrop.set_grid_visible(visible)

    def is_grid_overlay_visible(self) -> bool:
        return self._grid_overlay_visible

    def set_grid_overlay_multiplier(self, multiplier: int) -> None:
        """Densite du quadrillage : une ligne tous les `pas x multiplicateur`.

        Un multiplicateur plutot qu'une taille libre : le quadrillage reste
        ainsi toujours un multiple du pas de magnetisme, donc chaque ligne
        affichee marque une position ou une fenetre s'accroche vraiment.
        """
        value = max(1, int(multiplier or 1))
        changed = value != self._grid_overlay_multiplier
        self._grid_overlay_multiplier = value
        self._push_grid_metrics()
        # Le quadrillage dessine est aussi la reference des prochains
        # deplacements : au relachement, x/y rejoignent une ligne visible.
        self.layout_manager.set_alignment_grid_px(self.grid_overlay_step_px())
        if changed:
            self.align_windows_to_grid()

    def align_windows_to_grid(self) -> int:
        """Aligne position et taille de toutes les fenetres sur la grille visible."""
        return self.layout_manager.align_windows_to_grid(self.grid_overlay_step_px())

    def grid_overlay_multiplier(self) -> int:
        return self._grid_overlay_multiplier

    def grid_overlay_step_px(self) -> int:
        """Pas reellement affiche, en pixels."""
        from .backdrop import display_step_px

        return display_step_px(
            self.layout_manager.settings.grid_px, self._grid_overlay_multiplier
        )

    def _push_grid_metrics(self) -> None:
        if self._backdrop is not None:
            self._backdrop.set_grid_metrics(
                snap_px=self.layout_manager.settings.grid_px,
                multiplier=self._grid_overlay_multiplier,
            )

    def suspend(self) -> None:
        """Masque les fenetres visibles SANS changer leur etat 'visible'.

        Utilise pour basculer vers l'affichage classique sans perdre la
        composition en cours.
        """
        for inst in self._instances.values():
            win = self._windows.get(inst.instance_id)
            if win is not None and inst.visible:
                win.hide()
        if self._backdrop is not None:
            self._backdrop.hide()

    def resume(self) -> None:
        """Re-affiche les fenetres dont l'instance est marquee visible."""
        for inst in self._instances.values():
            win = self._windows.get(inst.instance_id)
            if win is not None and inst.visible:
                win.show()
        if self._backdrop_enabled:
            self.set_backdrop_enabled(True)

    def _on_window_activated(self, instance_id: str) -> None:
        self._touch_stack(instance_id)
        self.raise_group(active_window=self._windows.get(instance_id))

    # -- Interne ------------------------------------------------------------
    def _build_window(self, inst: ModuleInstance) -> ModuleWindow:
        mt = self._registry.get(inst.module_type)
        widget = mt.factory(self._context)
        win = ModuleWindow(inst.instance_id, inst.title, widget)
        win.windowHidden.connect(self._on_window_hidden)
        win.activated.connect(self._on_window_activated)
        win.geometryChanged.connect(self.layout_manager.geometry_changed)
        # Le magnetisme n'ecoute QUE le cycle d'interaction, jamais
        # geometryChanged : un setGeometry programmatique n'est pas un geste.
        win.interactionStarted.connect(self.layout_manager.interaction_started)
        win.interactionFinished.connect(self.layout_manager.interaction_finished)
        # La geometrie restauree ne doit pas etre prise pour un geste.
        with self.layout_manager.restoring_session_guard():
            win.apply_geometry(inst.geometry)
        self._windows[inst.instance_id] = win
        self.layout_manager.register_window(
            inst.instance_id, win, module_type=inst.module_type
        )
        # Une nouvelle instance doit respecter la grille au meme titre que les
        # geometries restaurees. Pendant restore_session(), la garde du
        # controleur rend volontairement cet appel inerte ; le recalage global
        # est fait une seule fois apres la restauration.
        self.align_windows_to_grid()
        self._connect_module_signals(inst, widget)
        self._restore_module_state(inst, widget)
        return win

    def _restore_module_state(self, inst: ModuleInstance, widget: QWidget) -> None:
        if not inst.state:
            return
        restorer = getattr(widget, "restore_state", None)
        if callable(restorer):
            try:
                restorer(dict(inst.state))
            except Exception:
                pass

    def _show_window(self, inst: ModuleInstance) -> None:
        win = self._windows.get(inst.instance_id)
        if win is None:
            win = self._build_window(inst)
        # Re-affichage : la geometrie reappliquee n'est pas un geste utilisateur.
        with self.layout_manager.applying_geometry_guard():
            win.apply_geometry(inst.geometry)
        win.show()
        win.raise_()
        win.activateWindow()
        inst.visible = True
        # Une fenetre qu'on vient d'afficher est la plus haute du groupe.
        self._touch_stack(inst.instance_id)

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
        artifact_signal = getattr(widget, "artifactCreated", None)
        if artifact_signal is not None:
            artifact_signal.connect(self._on_artifact_created)

        if inst.module_type == "reserve":
            signal = getattr(widget, "sendToLaboRequested", None)
            if signal is not None:
                signal.connect(self._open_paths_in_waveform)
        elif inst.module_type == "bins":
            open_signal = getattr(widget, "openInReserveRequested", None)
            if open_signal is not None:
                open_signal.connect(self._open_directory_in_reserve)
            refresh_signal = getattr(widget, "reserveRefreshRequested", None)
            if refresh_signal is not None:
                refresh_signal.connect(self._refresh_reserve_views)
            moved_signal = getattr(widget, "sourcePathsMoved", None)
            if moved_signal is not None:
                moved_signal.connect(self._remove_paths_from_reserve)
        elif inst.module_type == "waveform":
            signal = getattr(widget, "separationRequested", None)
            if signal is not None:
                signal.connect(self._open_paths_in_stems)
        elif inst.module_type == "artifacts":
            signal = getattr(widget, "openPathsRequested", None)
            if signal is not None:
                signal.connect(self._open_paths_in_waveform)

    def _on_artifact_created(self, artifact) -> None:
        store = getattr(self._context, "artifact_store", None)
        if store is not None:
            try:
                store.upsert(artifact)
            except Exception:
                pass

        if self._registry.has("artifacts") and self._pick_target("artifacts") is None:
            self.create_instance("artifacts")

    def _open_paths_in_waveform(self, paths) -> str | None:
        """Ouvre chaque fichier en ONGLET dans une instance Waveform.

        Reutilise une fenetre Waveform existante (visible de preference) plutot
        que d'en creer une par fichier ; en cree une seule si aucune n'existe.
        """
        valid = [str(p) for p in (paths or []) if p and os.path.isfile(str(p))]
        if not valid or not self._registry.has("waveform"):
            return None
        target_id = self._pick_target("waveform")
        if target_id is None:
            target_id = self.create_instance("waveform")
        widget = self._windows[target_id].module_widget()
        opener = getattr(widget, "open_file", None)
        if callable(opener):
            for path in valid:
                try:
                    opener(path)
                except Exception:
                    pass
        self.show_instance(target_id)
        return target_id

    def _open_paths_in_stems(self, paths) -> str | None:
        """Envoie les fichiers vers une instance Stem Lab (file de separation)."""
        valid = [str(p) for p in (paths or []) if p and os.path.isfile(str(p))]
        if not valid or not self._registry.has("stems"):
            return None
        target_id = self._pick_target("stems")
        if target_id is None:
            target_id = self.create_instance("stems")
        widget = self._windows[target_id].module_widget()
        enqueue = getattr(widget, "enqueue_paths", None)
        if callable(enqueue):
            try:
                enqueue(valid)
            except Exception:
                pass
        self.show_instance(target_id)
        return target_id

    def _open_directory_in_reserve(self, path: str) -> str | None:
        if not path or not os.path.isdir(str(path)) or not self._registry.has("reserve"):
            return None
        target_id = self._pick_target("reserve")
        if target_id is None:
            target_id = self.create_instance("reserve")
        widget = self._windows[target_id].module_widget()
        opener = getattr(widget, "open_directory_in_folders", None)
        if callable(opener):
            try:
                opener(str(path))
            except Exception:
                pass
        self.show_instance(target_id)
        return target_id

    def _refresh_reserve_views(self) -> None:
        for inst in self.instances_for_type("reserve"):
            widget = self._windows.get(inst.instance_id).module_widget() if self._windows.get(inst.instance_id) else None
            refresher = getattr(widget, "refresh_current_view", None)
            if callable(refresher):
                try:
                    refresher()
                except Exception:
                    pass

    def _remove_paths_from_reserve(self, paths) -> None:
        normalized = [str(path) for path in (paths or []) if path]
        if not normalized:
            return
        for inst in self.instances_for_type("reserve"):
            widget = self._windows.get(inst.instance_id).module_widget() if self._windows.get(inst.instance_id) else None
            remover = getattr(widget, "remove_paths_from_folders_view", None)
            if callable(remover):
                try:
                    remover(normalized)
                except Exception:
                    pass

    def _pick_target(self, module_type: str) -> str | None:
        """Choisit une instance cible du type : une visible sinon n'importe laquelle."""
        fallback: str | None = None
        for inst in self._instances.values():
            if inst.module_type == module_type:
                fallback = inst.instance_id
                if self.is_visible(inst.instance_id):
                    return inst.instance_id
        return fallback

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
