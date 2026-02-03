# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Centralise toute la logique d'interactions pour la WaveformWidget.
# - Sert de "controleur d'entrees" (mouse/keyboard) pour la selection, les
#   marqueurs, le drag de region et les gestes specifiques (molette, ctrl, etc.).
# - Est instancie par WaveformWidget et s'appuie sur ses methodes/proprietes.
#
# CE QUI EST COUVERT
# - Clic molette : position + lecture a cet endroit.
# - Mode marker : clic gauche pour poser un marqueur, drag des markers existants.
# - Mode region : clic-drag pour creer/redimensionner une region.
# - Maj + drag : deplacement complet de la region (shift move).
# - Ctrl + double-clic : selection rapide entre markers.
#
# RESPONSABILITES TECHNIQUES
# - Interpreter les QEvent (GraphicsSceneMouse...).
# - Maintenir l'etat temporaire (dragging/creating/shifting).
# - Creer/retirer la region (LinearRegionItem) et synchroniser play_start/end.
# - Deleguer au widget la logique metier (ajout marker, lecture, etc.).
#
# NON-OBJECTIFS
# - Aucun traitement audio (delegue a WaveformPlaybackController).
# - Aucun rendu de waveform (delegue a WaveformWidget).
#
# DEPENDANCES
# - PyQt6 (QEvent, Qt)
# - pyqtgraph (LinearRegionItem via region_cls)
# - numpy (convertit scene -> temps)
#
# IDEES / TODO
# - Refactor par sous-blocs (markers / region / gestures) pour lisibilite.
# - Ajouter des tests d'interaction par scenarios (smoke tests UI).
# - Harmoniser les gestes avec le reste de l'application.
# -----------------------------------------------------------------------------

import logging
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QEvent

logger = logging.getLogger("waveform_interactions")


class WaveformInteractionsController:
    def __init__(self, widget, region_cls):
        self.widget = widget
        self.region_cls = region_cls

    def eventFilter(self, source, event):
        w = self.widget
        region_cls = self.region_cls
        vb = w.plot.getViewBox()

        # --- 0) Clic molette: place la selection + lance la lecture
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.MiddleButton:
            if w.waveform_data is None or w.duration is None:
                return False
            pos = event.scenePos()
            t = float(np.clip(vb.mapSceneToView(pos).x(), 0, w.duration))
            # Visuel: poser un marqueur unique
            w._set_marker(t)
            # Selection logique + tete de lecture
            w.play_start = t
            w.play_end = t
            w.current_time = t
            w.read_head.setPos(t)
            # Lecture immediatement (comme clic gauche + ctrl+space)
            w.play_from_start()
            return True

        # --- 0) En mode marker, Ctrl+clic simple → sélection de la région ---
        if w.marker_mode \
           and event.type() == QEvent.GraphicsSceneMousePress \
           and event.button() == Qt.MouseButton.LeftButton \
           and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):

            logger.info("Ctrl+clic simple en mode marker")
            pos = event.scenePos()
            # Si on a cliqué sur un marker existant, on laisse InfiniteLine gérer
            for line in w.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

            # Sinon, on crée la région comme avec Ctrl+double-clic en mode non-marker
            w._handle_ctrl_double_click(vb, event)
            return True


        # 1) Ctrl + double-clic → délégation à la méthode dédiée

        if (event.type() == QEvent.GraphicsSceneMouseDoubleClick and
            event.button() == Qt.MouseButton.LeftButton and
            (event.modifiers() & Qt.KeyboardModifier.ControlModifier)):

            logger.info("Ctrl+double-clic détecté")
            # Si on a cliqué sur un marqueur, on le laisse gérer (suppression)
            pos = event.scenePos()
            for line in w.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

            # Sinon, on appelle la nouvelle méthode
            w._handle_ctrl_double_click(vb, event)
            return True

        # 0) Maj + clic gauche DANS le corps (pas sur les handles) → début du déplacement
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.LeftButton \
        and event.modifiers() & Qt.KeyboardModifier.ShiftModifier \
        and w.region:

            pos = event.scenePos()
            # handles
            line0, line1 = w.region.lines
            scene_h0 = line0.mapToScene(line0.boundingRect()).boundingRect().center().x()
            scene_h1 = line1.mapToScene(line1.boundingRect()).boundingRect().center().x()
            tol = 5
            if abs(pos.x() - scene_h0) < tol or abs(pos.x() - scene_h1) < tol:
                # on est sur un handle → pas notre cas
                return False

            # on est bien dans le corps de la région
            w._shifting = True
            # coordonnée de départ (en secondes)
            w._shift_press_x = float(vb.mapSceneToView(pos).x())
            # bornes d’origine
            w._orig_region = tuple(w.region.getRegion())
            return True

        # 1) déplacement pendant Maj+glissé
        if event.type() == QEvent.GraphicsSceneMouseMove \
        and w._shifting:

            pos = event.scenePos()
            x = float(vb.mapSceneToView(pos).x())
            dx = x - w._shift_press_x

            start0, end0 = w._orig_region
            length = end0 - start0
            # clamp pour rester dans [0, duration]
            new_start = max(0.0, min(start0 + dx, w.duration - length))
            new_end   = new_start + length

            w.region.setRegion([new_start, new_end])
            # mets à jour play_start/play_end sans déclencher création
            w.play_start, w.play_end = new_start, new_end
            return True

        # 2) fin du déplacement
        if event.type() == QEvent.GraphicsSceneMouseRelease \
        and event.button() == Qt.MouseButton.LeftButton \
        and w._shifting:

            w._shifting = False
            # ici, tu peux pousser dans l'historique si tu veux
            # w._push_history({...})
            return True

        if event.type() in (QEvent.GraphicsSceneMousePress,
                            QEvent.GraphicsSceneMouseMove,
                            QEvent.GraphicsSceneMouseRelease):
            pos = event.scenePos()
            # si on clique ou drag sur un marker, on ne filtre pas l'événement
            for line in w.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

        # 1) En mode marker, on intercepte seulement les clics hors des lignes existantes
        if w.marker_mode:
            if event.type() == QEvent.GraphicsSceneMousePress \
               and event.button() == Qt.MouseButton.LeftButton:
                pos = event.scenePos()
                # si on a cliqué SUR un marker existant, on laisse InfiniteLine gérer le drag
                for line in w.marker_lines.values():
                    if line.sceneBoundingRect().contains(pos):
                        return False
                # sinon, on créé un nouveau marker
                t = float(np.clip(vb.mapSceneToView(pos).x(), 0, w.duration))
                w.add_marker(t)
                return True
            return False

        # 2) Sinon, on est en mode region : clic-drag → création/redimensionnement
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.LeftButton:

            pos_scene = event.scenePos()
            vb = w.plot.getViewBox()
            data_x = vb.mapSceneToView(pos_scene).x()
            press_x = float(np.clip(data_x, 0, w.duration))

            # Si on a déjà une région...
            if w.region:
                r0, r1 = w.region.getRegion()

                # On calcule la position en pixels des deux handles
                line0, line1 = w.region.lines
                # boundingRect en coords locales, puis centre, puis en scene
                scene_handle0 = line0.mapToScene(line0.boundingRect()).boundingRect().center().x()
                scene_handle1 = line1.mapToScene(line1.boundingRect()).boundingRect().center().x()
                tol = 5  # tolérance en pixels

                # Si clic SUR un handle (gauche OU droit), on laisse LinearRegionItem gérer le resize
                if abs(pos_scene.x() - scene_handle0) < tol or abs(pos_scene.x() - scene_handle1) < tol:
                    return False

                # Sinon (clic dans le body), on SUPPRIME l'ancienne région
                w.plot.removeItem(w.region)
                w.region = None
                w._dragging = False
                w._creating = False

                # et on supprime aussi le marker (au cas où)
            if w.marker:
                w.plot.removeItem(w.marker)
                w.marker = None

            # À partir d'ici, on sait qu'il n'y a plus de région → on crée une nouvelle
            w._dragging = True
            w._creating = True
            w._press_x = press_x

            w.region = region_cls([press_x, press_x],
                                            brush=pg.mkBrush(255,255,255,40),
                                            pen=pg.mkPen('c', width=1))
            w.region.setBounds([0, w.duration])
            w.region.sigRegionChanged.connect(w.on_region_changed)
            w.region.sigRegionChangeFinished.connect(w.on_region_changed)
            # w.region.sigContextMenuRequested.connect(w._on_region_context_menu)
            w.region._parent = w
            w.plot.addItem(w.region)
            return True

        # 2) Redimensionnement **durant** le drag de création
        elif event.type() == QEvent.GraphicsSceneMouseMove \
            and w._dragging and w._creating \
            and w.region is not None:

            pos = w.plot.getViewBox().mapSceneToView(event.scenePos())
            x   = float(np.clip(pos.x(), 0, w.duration))
            w.region.setRegion([min(w._press_x, x),
                                max(w._press_x, x)])
            return True

        # 3) Fin du drag (Release) → région validée ou simple clic
        elif event.type() == QEvent.GraphicsSceneMouseRelease \
             and event.button() == Qt.MouseButton.LeftButton \
             and w._creating:

            logger.info("Fin du drag")

            pos       = w.plot.getViewBox().mapSceneToView(event.scenePos())
            release_x = float(np.clip(pos.x(), 0, w.duration))
            w._dragging = False
            w._creating = False
            w.on_region_changed()

            # si c’était un clic « sans drag »: on détruit la mini-région et pose un marker
            if abs(release_x - w._press_x) < 1e-3:
                w.plot.removeItem(w.region)
                w.region = None
                w._dragging = False
                w._creating = False
                w._set_marker(release_x)
            # sinon on garde la région telle quelle (handles actifs)
            return True

        # 4) tout le reste passe à la moulinette par défaut
        return False

            # —————————————————————————————————— menu contextuel region ——————————————————————————————————
