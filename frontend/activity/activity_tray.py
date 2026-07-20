# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le "plateau d'activite" : la fine barre en bas de la fenetre principale
#   qui montre les taches de fond (analyses, normalisations, stems...).
# - Deux etats :
#   * replie (par defaut) : une ligne resumant "N taches en cours" avec un
#     spinner et une barre de progression globale — ou, au repos, le dernier
#     message ("Gamme analysee : ... il y a 12s") ;
#   * deplie (clic sur la fleche) : la liste detaillee, section "En cours"
#     puis "Recentes", chaque ligne avec icone, nom de fichier, barre de
#     progression et statut colore.
# - Le contenu vient d'ActivityService ; ce fichier ne fait QUE l'affichage.
#
# CLASSES ET FONCTIONS (sommaire)
# - _pluralize()         : "1 tache" / "2 taches".
# - _relative_age_text() : "il y a 12s / 3min / 2h".
# - _SpinnerWidget       : petit arc qui tourne (dessine a la main, 80 ms/pas).
#   - set_active() / _advance() / paintEvent().
# - _ActivityRow         : une ligne de tache.
#   - update_item()      : adapte icone, texte, barre, spinner et couleurs
#                          au statut (attente/en cours/ok/echec).
#   - apply_styles()     : styles dependant du theme.
#   - start_fade()/_reset_fade_if_needed() : fondu de sortie des taches finies.
#   - _apply_progress_style() : couleur de la barre de progression.
# - ActivityTrayWidget   : le plateau complet.
#   - _build_ui()        : barre repliee + zone depliable (scrollable).
#   - _bind_signals()/_connect() : abonnements au service et au theme.
#   - _sync_from_service(): recree/recycle les lignes selon le registre.
#   - _populate_layout() : range les lignes dans les sections.
#   - _toggle_expanded() : animation d'ouverture/fermeture des details.
#   - _target_details_height() : hauteur cible (bornee a 192 px).
#   - _update_header()   : texte/spinner/barre globale de la ligne repliee.
#   - _on_refresh_tick() : toutes les 250 ms, rafraichit l'en-tete et lance
#                          le fondu des taches finies depuis > 4 s.
#   - _on_activity_echo()/_on_theme_changed()/_apply_styles().
#   - shutdown()         : stoppe timers et abonnements a la fermeture.
#
# LIENS CLES
# - frontend/activity/activity_service.py : la source des donnees.
# - frontend/main_window.py : place ce widget sous les onglets.
# -----------------------------------------------------------------------------

from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend.styles import theme

from .activity_service import ActivityItem, ActivityService, ActivityStatus


def _pluralize(value: int, singular: str, plural: str | None = None) -> str:
    """Accorde un mot en nombre ("1 tache", "2 taches")."""
    if value == 1:
        return singular
    return plural or f"{singular}s"


def _relative_age_text(timestamp: float | None) -> str:
    """Anciennete lisible d'un instant : "il y a 12s", "il y a 3min"..."""
    if timestamp is None:
        return ""
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return f"il y a {seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"il y a {minutes}min"
    hours = minutes // 60
    return f"il y a {hours}h"


class _SpinnerWidget(QWidget):
    """Petit indicateur d'attente circulaire, dessine a la main.

    Un timer fait tourner un arc de cercle de 30 degres toutes les 80 ms.
    Cache et fige quand inactif (aucun cout CPU au repos).
    """

    def __init__(self, size: int = 14, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._active = False
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if self._active == active:
            return
        self._active = active
        if active:
            self._timer.start()
            self.show()
        else:
            self._timer.stop()
            self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        color = QColor(theme.manager.p.INFO)
        color.setAlpha(230)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, 130 * 16)


class _ActivityRow(QWidget):
    """Une ligne du plateau : [icone] titre · fichier [barre] [statut]."""

    # Icone affichee selon le type de tache.
    ICONS = {
        "scale": "🎵",
        "stem": "🌿",
        "drum": "🥁",
        "normalize": "⚡",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item: ActivityItem | None = None
        self._is_fading = False
        self._fade_animation: QPropertyAnimation | None = None
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._build_ui()
        self.apply_styles()

    def _build_ui(self) -> None:
        self.setObjectName("ActivityRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        self.icon_label = QLabel("○")
        self.icon_label.setObjectName("ActivityRowIcon")
        self.icon_label.setFixedWidth(18)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_label = QLabel("")
        self.text_label.setObjectName("ActivityRowText")
        self.text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.text_label.setMinimumWidth(0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ActivityRowBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(110)
        self.progress_bar.setFixedHeight(8)

        self.spinner = _SpinnerWidget(12, self)
        self.spinner.hide()

        self.status_label = QLabel("")
        self.status_label.setObjectName("ActivityRowStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setFixedWidth(62)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label, 1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.spinner)
        layout.addWidget(self.status_label)

    def update_item(self, item: ActivityItem) -> None:
        """Met la ligne en accord avec l'etat de la tache.

        Chaque statut a sa presentation : attente = barre vide grise ;
        en cours = barre bleue avec %, ou spinner si la progression est
        inconnue ; ok = barre verte pleine ; echec = barre rouge pleine.
        """
        self._item = item
        self._reset_fade_if_needed()

        self.icon_label.setText(self.ICONS.get(item.kind, "○"))
        self.text_label.setText(f"{item.title} · {item.label}")

        if item.status is ActivityStatus.PENDING:
            progress_value = 0
            status_text = "attente"
            status_color = theme.manager.p.TEXT_MUTED
            bar_color = theme.manager.p.BORDER_LIGHT
            show_spinner = False
            show_bar = True
        elif item.status is ActivityStatus.RUNNING:
            progress_value = int(round(item.progress * 100))
            status_text = f"{progress_value}%" if progress_value > 0 else "en cours"
            status_color = theme.manager.p.INFO
            bar_color = theme.manager.p.INFO
            show_spinner = progress_value <= 0
            show_bar = progress_value > 0
        elif item.status is ActivityStatus.DONE:
            progress_value = 100
            status_text = "ok"
            status_color = theme.manager.p.SUCCESS
            bar_color = theme.manager.p.SUCCESS
            show_spinner = False
            show_bar = True
        else:
            progress_value = 100
            status_text = "echec"
            status_color = theme.manager.p.ERROR
            bar_color = theme.manager.p.ERROR
            show_spinner = False
            show_bar = True

        self.progress_bar.setVisible(show_bar)
        self.spinner.set_active(show_spinner)
        self.progress_bar.setValue(progress_value)
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(f"color: {status_color};")
        self._apply_progress_style(bar_color)

        tooltip_lines = [
            f"{item.title} · {item.label}",
            f"Etat : {status_text}",
        ]
        if item.detail:
            tooltip_lines.append(item.detail)
        self.setToolTip("\n".join(tooltip_lines))

    def apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#ActivityRow {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QLabel#ActivityRowIcon {{
                color: {p.TEXT};
                font-size: 13px;
            }}
            QLabel#ActivityRowText {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 500;
            }}
            QLabel#ActivityRowStatus {{
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )
        if self._item is not None:
            self.update_item(self._item)

    def start_fade(self) -> None:
        if self._is_fading:
            return
        self._is_fading = True
        animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        animation.setDuration(320)
        animation.setStartValue(float(self._opacity_effect.opacity()))
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._fade_animation = animation

    def _reset_fade_if_needed(self) -> None:
        if self._fade_animation is not None:
            self._fade_animation.stop()
            self._fade_animation = None
        self._is_fading = False
        self._opacity_effect.setOpacity(1.0)

    def _apply_progress_style(self, chunk_color: str) -> None:
        p = theme.manager.p
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar#ActivityRowBar {{
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
            }}
            QProgressBar#ActivityRowBar::chunk {{
                background: {chunk_color};
                border-radius: 3px;
            }}
            """
        )


class ActivityTrayWidget(QWidget):
    """Le plateau d'activite complet : barre repliee + details depliables."""

    DETAILS_MAX_HEIGHT = 192
    TRAY_TOOLTIP = "Les taches en cours seront interrompues a la fermeture."

    def __init__(self, activity_service: ActivityService, parent=None):
        super().__init__(parent)
        self.activity_service = activity_service
        self._expanded = False
        self._rows: dict[str, _ActivityRow] = {}
        self._connections: list[tuple[object, object]] = []
        self._height_animation: QPropertyAnimation | None = None

        self._build_ui()
        self._bind_signals()
        self._apply_styles()
        self._sync_from_service()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start()

    def shutdown(self) -> None:
        self._refresh_timer.stop()
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._connections.clear()
        for row in self._rows.values():
            row.spinner.set_active(False)
        self.header_spinner.set_active(False)

    def _build_ui(self) -> None:
        self.setObjectName("ActivityTrayRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setToolTip(self.TRAY_TOOLTIP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.details_wrap = QWidget()
        self.details_wrap.setObjectName("ActivityTrayDetails")
        self.details_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.details_wrap.setMaximumHeight(0)

        details_layout = QVBoxLayout(self.details_wrap)
        details_layout.setContentsMargins(8, 6, 8, 8)
        details_layout.setSpacing(6)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("ActivityScrollContent")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(6)

        self.active_header = QLabel("En cours")
        self.active_header.setObjectName("ActivitySectionHeader")
        self.active_list = QWidget()
        self.active_list_layout = QVBoxLayout(self.active_list)
        self.active_list_layout.setContentsMargins(0, 0, 0, 0)
        self.active_list_layout.setSpacing(6)

        self.recent_header = QLabel("Recentes")
        self.recent_header.setObjectName("ActivitySectionHeader")
        self.recent_list = QWidget()
        self.recent_list_layout = QVBoxLayout(self.recent_list)
        self.recent_list_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_list_layout.setSpacing(6)

        self.empty_label = QLabel("Aucune activite recente.")
        self.empty_label.setObjectName("ActivityEmpty")

        self.scroll_layout.addWidget(self.active_header)
        self.scroll_layout.addWidget(self.active_list)
        self.scroll_layout.addWidget(self.recent_header)
        self.scroll_layout.addWidget(self.recent_list)
        self.scroll_layout.addWidget(self.empty_label)
        self.scroll_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_content)
        details_layout.addWidget(self.scroll_area)

        self.header_bar = QWidget()
        self.header_bar.setObjectName("ActivityTrayHeader")
        self.header_bar.setFixedHeight(28)
        self.header_bar.setToolTip(self.TRAY_TOOLTIP)

        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(10, 3, 8, 3)
        header_layout.setSpacing(8)

        self.idle_icon = QLabel("○")
        self.idle_icon.setObjectName("ActivityIdleIcon")
        self.idle_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.idle_icon.setFixedWidth(14)

        self.header_spinner = _SpinnerWidget(14, self.header_bar)
        self.header_spinner.hide()

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("ActivitySummary")
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        self.global_bar = QProgressBar()
        self.global_bar.setObjectName("ActivityGlobalBar")
        self.global_bar.setRange(0, 100)
        self.global_bar.setValue(0)
        self.global_bar.setTextVisible(False)
        self.global_bar.setFixedWidth(104)
        self.global_bar.setFixedHeight(8)
        self.global_bar.hide()

        self.echo_label = QLabel("")
        self.echo_label.setObjectName("ActivityEcho")
        self.echo_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.echo_label.setMinimumWidth(0)

        self.toggle_button = QPushButton("▾")
        self.toggle_button.setObjectName("ActivityToggle")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setFixedSize(18, 18)
        self.toggle_button.setToolTip("Afficher les details")
        self.toggle_button.clicked.connect(self._toggle_expanded)

        header_layout.addWidget(self.idle_icon)
        header_layout.addWidget(self.header_spinner)
        header_layout.addWidget(self.summary_label)
        header_layout.addWidget(self.global_bar)
        header_layout.addWidget(self.echo_label, 1)
        header_layout.addWidget(self.toggle_button)

        root_layout.addWidget(self.details_wrap)
        root_layout.addWidget(self.header_bar)

    def _bind_signals(self) -> None:
        self._connect(self.activity_service.activityChanged, self._sync_from_service)
        self._connect(self.activity_service.activityEcho, self._on_activity_echo)
        self._connect(theme.manager.themeChanged, self._on_theme_changed)

    def _connect(self, signal, slot) -> None:
        signal.connect(slot)
        self._connections.append((signal, slot))

    def _sync_from_service(self) -> None:
        """Remet l'affichage en accord avec le registre du service.

        Strategie "recycler plutot que recreer" : les lignes existantes
        sont reutilisees et mises a jour, seules les nouvelles taches
        recoivent une ligne neuve, et les lignes orphelines sont detruites.
        """
        active_items = self.activity_service.get_active()
        recent_items = self.activity_service.get_recent(5)

        desired_ids = {item.uid for item in active_items + recent_items}
        for item in active_items + recent_items:
            row = self._rows.get(item.uid)
            if row is None:
                row = _ActivityRow(self)
                row.setToolTip(self.TRAY_TOOLTIP)
                self._rows[item.uid] = row
            row.update_item(item)

        for uid in list(self._rows):
            if uid in desired_ids:
                continue
            row = self._rows.pop(uid)
            row.setParent(None)
            row.deleteLater()

        self._populate_layout(self.active_list_layout, active_items)
        self._populate_layout(self.recent_list_layout, recent_items)

        self.active_header.setVisible(bool(active_items))
        self.active_list.setVisible(bool(active_items))
        self.recent_header.setVisible(bool(recent_items))
        self.recent_list.setVisible(bool(recent_items))
        self.empty_label.setVisible(not active_items and not recent_items)

        if self._expanded:
            self.details_wrap.setMaximumHeight(self._target_details_height())
        self._update_header()

    def _populate_layout(self, layout: QVBoxLayout, items: list[ActivityItem]) -> None:
        """Vide une section puis y range les lignes des taches, dans l'ordre."""
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.hide()
        for item in items:
            row = self._rows[item.uid]
            row.show()
            layout.addWidget(row)

    def _toggle_expanded(self) -> None:
        """Ouvre/ferme la zone de details avec une animation de hauteur."""
        self._expanded = not self._expanded
        self.toggle_button.setText("▴" if self._expanded else "▾")
        self.toggle_button.setToolTip(
            "Masquer les details" if self._expanded else "Afficher les details"
        )

        target = self._target_details_height() if self._expanded else 0
        animation = QPropertyAnimation(self.details_wrap, b"maximumHeight", self)
        animation.setDuration(180)
        animation.setStartValue(self.details_wrap.maximumHeight())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._height_animation = animation

    def _target_details_height(self) -> int:
        height = self.scroll_content.sizeHint().height() + 14
        return max(54, min(self.DETAILS_MAX_HEIGHT, height))

    def _update_header(self) -> None:
        """Rafraichit la ligne repliee : compteur + barre, ou dernier echo."""
        active_count = self.activity_service.active_count()
        has_active = active_count > 0

        self.idle_icon.setVisible(not has_active)
        self.header_spinner.set_active(has_active)

        if has_active:
            task_label = _pluralize(active_count, "tache")
            self.summary_label.setText(f"{active_count} {task_label} en cours")
            self.global_bar.show()
            self.global_bar.setValue(int(round(self.activity_service.session_progress() * 100)))
            self.echo_label.hide()
        else:
            self.summary_label.setText("Aucune tache en cours")
            self.global_bar.hide()
            echo_message, echo_at = self.activity_service.last_echo()
            if echo_message:
                age_text = _relative_age_text(echo_at)
                suffix = f"  {age_text}" if age_text else ""
                self.echo_label.setText(f"{echo_message}{suffix}")
                self.echo_label.show()
            else:
                self.echo_label.hide()

    def _on_refresh_tick(self) -> None:
        """Tick periodique (250 ms) : en-tete + fondu des taches finies."""
        self._update_header()
        for item in self.activity_service.get_recent(5):
            if item.ended_at is None:
                continue
            if time.time() - item.ended_at < self.activity_service.RECENT_VISIBLE_SECONDS:
                continue
            row = self._rows.get(item.uid)
            if row is not None:
                row.start_fade()

    def _on_activity_echo(self, _message: str) -> None:
        self._update_header()

    def _on_theme_changed(self, _theme_name: str) -> None:
        self._apply_styles()
        for row in self._rows.values():
            row.apply_styles()
        self._update_header()

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#ActivityTrayRoot {{
                background: {p.BG_DARK};
                border-top: 1px solid {p.BORDER};
            }}
            QWidget#ActivityTrayDetails {{
                background: {p.BG_MEDIUM};
            }}
            QWidget#ActivityTrayHeader {{
                background: {p.BG_DARK};
            }}
            QLabel#ActivityIdleIcon {{
                color: {p.TEXT_MUTED};
                font-size: 13px;
            }}
            QLabel#ActivitySummary {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#ActivityEcho {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#ActivitySectionHeader {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                padding: 0 2px;
            }}
            QLabel#ActivityEmpty {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
                padding: 4px 2px;
            }}
            QPushButton#ActivityToggle {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: none;
                border-radius: 6px;
                padding: 0;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#ActivityToggle:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
            }}
            QProgressBar#ActivityGlobalBar {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
            }}
            QProgressBar#ActivityGlobalBar::chunk {{
                background: {p.INFO};
                border-radius: 3px;
            }}
            """
        )
