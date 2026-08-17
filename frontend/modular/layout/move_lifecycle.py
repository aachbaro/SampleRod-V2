# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Delimite le GESTE de l'utilisateur : ou commence-t-il, ou finit-il.
# - C'est la seule source du magnetisme : le snap ne s'applique qu'a la fin
#   d'une interaction, jamais sur un simple changement de geometrie.
#
# POURQUOI PAS DE SNAP CONTINU
# - Sous Windows, glisser une fenetre par sa barre de titre lance une BOUCLE
#   MODALE de l'OS. Pendant cette boucle, l'OS garde sa propre position de
#   reference : corriger la geometrie par-dessus revient a lutter contre elle,
#   d'ou les tremblements. Un prototype a mesure la re-entrance (profondeur 2).
# - On observe donc, et on n'agit qu'a WM_EXITSIZEMOVE.
#
# STRICTE PASSIVITE
# - `handle_native` ne consomme JAMAIS l'evenement, ne renvoie jamais True,
#   ne touche jamais au RECT. WM_MOVING et WM_SIZING sont volontairement
#   ignores : les decoder ne servirait qu'a un snap continu, qu'on ne fait pas.
#
# FALLBACK
# - Hors Windows, un observateur a timer prend le relais. ATTENTION : il
#   detecte une INACTIVITE, pas un relachement de bouton. Un utilisateur qui
#   maintient le clic sans bouger declencherait une fin prematuree. C'est
#   precisement pourquoi il n'est jamais choisi sous Windows.
#
# LIENS CLES
# - frontend/modular/module_window.py        : delegue son nativeEvent ici
# - frontend/modular/layout/layout_manager.py: consommateur des signaux
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import sys
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("move_lifecycle")

# Messages Win32 du cycle de deplacement/redimensionnement.
WM_SIZING = 0x0214
WM_MOVING = 0x0216
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232

# Inactivite au-dela de laquelle le fallback considere le geste termine.
FALLBACK_IDLE_MS = 220


class InteractionPhase(Enum):
    """Debut ou fin d'un geste utilisateur sur une fenetre."""

    START = "start"
    END = "end"


def decode_win32_message(msg_id: int) -> InteractionPhase | None:
    """Traduit un identifiant de message Win32 en phase d'interaction.

    PURE : testable avec de simples entiers, sans Windows ni fenetre.

    WM_MOVING et WM_SIZING renvoient volontairement None. Les traiter
    supposerait un snap continu, qui lutterait contre la boucle modale de l'OS.
    """
    if msg_id == WM_ENTERSIZEMOVE:
        return InteractionPhase.START
    if msg_id == WM_EXITSIZEMOVE:
        return InteractionPhase.END
    return None


class _BaseInteractionWatcher(QObject):
    """Contrat commun : deux signaux, et un etat 'geste en cours'."""

    interactionStarted = Signal(str)
    interactionFinished = Signal(str)

    def __init__(self, window_id: str, parent=None):
        super().__init__(parent)
        self._window_id = str(window_id)
        self._active = False

    @property
    def window_id(self) -> str:
        return self._window_id

    @property
    def is_interacting(self) -> bool:
        return self._active

    def handle_native(self, event_type, message) -> bool:
        """Observation seulement. Renvoie TOUJOURS False (jamais consomme)."""
        return False

    def on_geometry_event(self) -> None:
        """Signale un moveEvent/resizeEvent. Sans effet hors fallback."""

    # -- Interne ------------------------------------------------------------
    def _begin(self) -> None:
        if self._active:
            return
        self._active = True
        self.interactionStarted.emit(self._window_id)

    def _end(self) -> None:
        if not self._active:
            return
        self._active = False
        self.interactionFinished.emit(self._window_id)


class Win32InteractionWatcher(_BaseInteractionWatcher):
    """Observe WM_ENTERSIZEMOVE / WM_EXITSIZEMOVE. Ne consomme rien."""

    def handle_native(self, event_type, message) -> bool:
        phase = self._phase_of(message)
        if phase is InteractionPhase.START:
            self._begin()
        elif phase is InteractionPhase.END:
            self._end()
        # Toujours False : l'evenement poursuit sa route vers Qt puis l'OS.
        return False

    @staticmethod
    def _phase_of(message) -> InteractionPhase | None:
        """Extrait l'identifiant du message, puis delegue au decodage pur."""
        msg_id = _win32_message_id(message)
        if msg_id is None:
            return None
        return decode_win32_message(msg_id)


class TimerInteractionWatcher(_BaseInteractionWatcher):
    """Fallback portable : detecte une INACTIVITE, pas un relachement.

    Utilisable la ou aucun cycle natif fiable n'existe. Sous Windows on lui
    prefere toujours Win32InteractionWatcher (voir l'en-tete du module).
    """

    def __init__(self, window_id: str, parent=None, idle_ms: int = FALLBACK_IDLE_MS):
        super().__init__(window_id, parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(idle_ms))
        self._timer.timeout.connect(self._on_idle)

    def on_geometry_event(self) -> None:
        self._begin()          # sans effet si un geste est deja en cours
        self._timer.start()    # relance : tant que ca bouge, on ne conclut pas

    def _on_idle(self) -> None:
        self._end()

    def stop(self) -> None:
        self._timer.stop()


def _win32_message_id(message):
    """Identifiant du message Win32 porte par un voidptr PySide6.

    Toute la fragilite ctypes tient ici : extraire un entier. La logique, elle,
    vit dans `decode_win32_message`, qui se teste sans Windows.
    """
    if message is None:
        return None
    # Doublure de test : un objet exposant deja `.message`.
    direct = getattr(message, "message", None)
    if isinstance(direct, int):
        return direct
    try:
        import ctypes
        from ctypes import wintypes

        class _MSG(ctypes.Structure):
            _fields_ = [
                ("hWnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG),
            ]

        return ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents.message
    except Exception:
        return None


def create_interaction_watcher(window_id: str, parent=None, *, force=None):
    """Observateur adapte a la plateforme.

    `force` sert aux tests : il permet d'exercer le fallback sous Windows sans
    dependre de la plateforme reelle.
    """
    if force is not None:
        return force(window_id, parent)
    if sys.platform.startswith("win"):
        return Win32InteractionWatcher(window_id, parent)
    return TimerInteractionWatcher(window_id, parent)
