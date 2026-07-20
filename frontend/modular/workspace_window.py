# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre Workspace : le "centre de controle" compact de l'atelier modulaire.
# - Liste toutes les instances ouvertes par categorie (RESERVES, WAVEFORMS...)
#   et sert de barre des taches interne : creer, afficher, masquer, renommer,
#   dupliquer, fermer une instance ; voir son etat (visible / masquee).
#
# STRUCTURE
# - En-tete "SAMPLEROD" ; zone scrollable ; une section par categorie avec un
#   bouton "+" (nouvelle instance) ; une ligne par instance avec ses actions.
# - Se reconstruit sur WindowManager.instancesChanged / instanceUpdated.
#
# LIENS CLES
# - frontend/modular/window_manager.py : pilote (create/show/hide/...)
# - frontend/ui/                        : IconButton + icones + theme
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from frontend.styles import theme
from frontend.ui import IconButton, themed_icon

from .window_manager import WindowManager


class _InstanceRow(QWidget):
    """Une ligne d'instance : pastille d'etat, titre, actions."""

    activate = Signal(str)
    toggleVisibility = Signal(str)
    rename = Signal(str)
    duplicate = Signal(str)
    closeInstance = Signal(str)

    def __init__(
        self,
        instance_id: str,
        title: str,
        visible: bool,
        *,
        renamable: bool = True,
        duplicable: bool = True,
        closable: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._instance_id = instance_id
        self._visible = visible
        self._renamable = bool(renamable)
        self._duplicable = bool(duplicable)
        self._closable = bool(closable)
        self.setObjectName("WsInstanceRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(6)

        self._dot = QLabel()
        self._dot.setFixedSize(16, 16)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel(title)
        self._title.setObjectName("WsInstanceTitle")
        self._title.setCursor(Qt.CursorShape.PointingHandCursor)

        self._eye_btn = IconButton("eye", tooltip="Afficher / masquer", size="s")
        self._rename_btn = IconButton("pencil", tooltip="Renommer", size="s")
        self._dup_btn = IconButton("copy", tooltip="Dupliquer", size="s")
        self._close_btn = IconButton("x", tooltip="Fermer", size="s")

        self._eye_btn.clicked.connect(lambda: self.toggleVisibility.emit(self._instance_id))
        self._rename_btn.clicked.connect(lambda: self.rename.emit(self._instance_id))
        self._dup_btn.clicked.connect(lambda: self.duplicate.emit(self._instance_id))
        self._close_btn.clicked.connect(lambda: self.closeInstance.emit(self._instance_id))

        row.addWidget(self._dot, 0)
        row.addWidget(self._title, 1)
        row.addWidget(self._eye_btn, 0)
        row.addWidget(self._rename_btn, 0)
        row.addWidget(self._dup_btn, 0)
        row.addWidget(self._close_btn, 0)

        # Boutons d'action visibles seulement au survol de la ligne.
        self._actions = [self._eye_btn, self._rename_btn, self._dup_btn, self._close_btn]
        self._set_actions_visible(False)
        self._refresh_visual()

    def _set_actions_visible(self, visible: bool) -> None:
        self._eye_btn.setVisible(visible)
        self._rename_btn.setVisible(visible and self._renamable)
        self._dup_btn.setVisible(visible and self._duplicable)
        self._close_btn.setVisible(visible and self._closable)

    def enterEvent(self, event):  # noqa: N802
        self._set_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._set_actions_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate.emit(self._instance_id)
        super().mousePressEvent(event)

    def set_state(self, title: str, visible: bool) -> None:
        self._title.setText(title)
        self._visible = visible
        self._refresh_visual()

    def _refresh_visual(self) -> None:
        p = theme.manager.p
        color = p.ACCENT if self._visible else p.TEXT_MUTED
        self._dot.setPixmap(
            themed_icon("dot-filled" if self._visible else "dot-empty", 12, color).pixmap(12, 12)
        )
        self._eye_btn.set_icon_name("eye" if self._visible else "eye-off")
        self._title.setStyleSheet(
            f"color: {p.TEXT if self._visible else p.TEXT_MUTED}; font-size: 12px;"
        )


class WorkspaceWindow(QWidget):
    """Centre de controle compact listant les instances par categorie."""

    exitRequested = Signal()  # basculer vers l'affichage classique (bouton toggle)
    quitRequested = Signal()  # fermer l'application (croix de l'orchestrateur)

    def __init__(self, window_manager: WindowManager, parent=None):
        super().__init__(parent)
        self._wm = window_manager
        self.setObjectName("WorkspaceWindow")
        self.setWindowTitle("SampleRod - Workspace")
        self.setMinimumWidth(280)
        self.resize(320, 620)

        self._build_ui()
        self._wm.instancesChanged.connect(self._rebuild)
        self._wm.instanceUpdated.connect(lambda *_a: self._rebuild())
        theme.manager.themeChanged.connect(lambda *_a: self._apply_styles())
        self._wm.add_companion(self)
        self._rebuild()
        # Restaure l'etat du fond global (backdrop)
        backdrop_on = QSettings("SampleRod", "Main").value(
            "modular_backdrop_enabled", False, type=bool
        )
        self._backdrop_btn.setChecked(bool(backdrop_on))
        self._wm.set_backdrop_enabled(bool(backdrop_on))

    def _on_backdrop_toggled(self, *_args) -> None:
        enabled = self._backdrop_btn.isChecked()
        self._wm.set_backdrop_enabled(enabled)
        QSettings("SampleRod", "Main").setValue("modular_backdrop_enabled", enabled)

    def changeEvent(self, event):  # noqa: N802
        # Workspace active -> remonte tout le groupe de fenetres visibles.
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._wm.raise_group(active_window=self)
        super().changeEvent(event)

    def closeEvent(self, event):  # noqa: N802
        # Fermer l'orchestrateur = fermer l'application (les deux modes sont
        # au meme niveau ; pour revenir au classique, utiliser le bouton toggle).
        event.ignore()
        self.quitRequested.emit()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("WsHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 10, 8, 10)
        self._brand = QLabel("SAMPLEROD")
        self._brand.setObjectName("WsBrand")
        self._backdrop_btn = IconButton(
            "square",
            tooltip="Fond global : masquer le bureau derriere l'atelier",
            size="s",
        )
        self._backdrop_btn.setCheckable(True)
        self._backdrop_btn.clicked.connect(self._on_backdrop_toggled)
        self._exit_btn = IconButton(
            "window",
            tooltip="Revenir a l'affichage classique",
            size="s",
        )
        self._exit_btn.clicked.connect(self.exitRequested.emit)
        h.addWidget(self._brand, 1)
        h.addWidget(self._backdrop_btn, 0)
        h.addWidget(self._exit_btn, 0)
        root.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("WsScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body.setObjectName("WsBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 8, 8, 12)
        self._body_layout.setSpacing(4)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)

        root.addWidget(self._scroll, 1)
        self._apply_styles()

    # -- Construction du contenu -------------------------------------------
    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear_body()
        grouped = self._wm.instances_by_category()
        registry = self._wm.registry
        # type de module par categorie (v1 : un type par categorie).
        type_for_category: dict[str, str] = {}
        for mt in registry.all():
            type_for_category.setdefault(mt.category, mt.type_id)

        any_instance = False
        for category in registry.categories():
            instances = grouped.get(category, [])
            self._body_layout.addWidget(
                self._build_category_header(category, type_for_category.get(category))
            )
            for inst in instances:
                any_instance = True
                self._body_layout.addWidget(self._build_row(inst))

        if not any_instance:
            hint = QLabel("Aucune instance. Utilise + pour en creer une.")
            hint.setObjectName("WsEmpty")
            hint.setWordWrap(True)
            self._body_layout.addWidget(hint)

        self._body_layout.addStretch(1)

    def _build_category_header(self, category: str, type_id: str | None) -> QWidget:
        widget = QWidget()
        widget.setObjectName("WsCategory")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(widget)
        lay.setContentsMargins(6, 8, 4, 2)
        lay.setSpacing(6)

        label = QLabel(category)
        label.setObjectName("WsCategoryLabel")
        lay.addWidget(label, 1)

        if type_id is not None:
            mt = self._wm.registry.get(type_id)
        else:
            mt = None

        if (
            type_id is not None
            and mt is not None
            and mt.workspace_creatable
            and self._wm.can_create_instance(type_id)
        ):
            add_btn = IconButton("plus", tooltip=f"Nouvelle instance ({category.lower()})", size="s")
            add_btn.clicked.connect(lambda _=False, tid=type_id: self._wm.create_instance(tid))
            lay.addWidget(add_btn, 0)
        return widget

    def _build_row(self, inst) -> _InstanceRow:
        mt = self._wm.module_type_for_instance(inst.instance_id)
        row = _InstanceRow(
            inst.instance_id,
            inst.title,
            self._wm.is_visible(inst.instance_id),
            renamable=bool(mt is not None and mt.renamable),
            duplicable=bool(mt is not None and mt.duplicable and mt.multi),
            closable=bool(mt is not None and mt.closable),
        )
        row.activate.connect(self._wm.show_instance)
        row.toggleVisibility.connect(self._wm.toggle_instance)
        row.duplicate.connect(self._wm.duplicate_instance)
        row.closeInstance.connect(self._wm.close_instance)
        row.rename.connect(self._on_rename)
        return row

    def _on_rename(self, instance_id: str) -> None:
        if not self._wm.can_rename_instance(instance_id):
            return
        inst = self._wm.get_instance(instance_id)
        if inst is None:
            return
        new_title, ok = QInputDialog.getText(
            self, "Renommer l'instance", "Nouveau nom :", text=inst.title
        )
        if ok and new_title.strip():
            self._wm.rename_instance(instance_id, new_title.strip())

    # -- Styles -------------------------------------------------------------
    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#WorkspaceWindow, QWidget#WsBody {{ background: {p.BG_DARK}; }}
            QWidget#WsHeader {{
                background: {p.BG_MEDIUM};
                border-bottom: 1px solid {p.BORDER};
            }}
            QLabel#WsBrand {{
                color: {p.TEXT};
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 2px;
            }}
            QLabel#WsCategoryLabel {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QWidget#WsInstanceRow {{ background: transparent; border-radius: 6px; }}
            QWidget#WsInstanceRow:hover {{ background: {p.BG_HOVER}; }}
            QLabel#WsEmpty {{ color: {p.TEXT_MUTED}; font-size: 11px; padding: 8px; }}
            """
        )
