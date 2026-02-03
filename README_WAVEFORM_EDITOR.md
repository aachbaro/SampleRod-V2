# Waveform Editor - Guide d'utilisation

Ce document explique comment fonctionne l'editeur de waveform, les gestes
disponibles, et la difference entre **region**, **markers** et **curseur de depart**.

## Vue d'ensemble
L'editeur de waveform sert a :
- lire un sample (play/pause/stop/loop),
- selectionner une region,
- placer des markers,
- couper ou exporter un segment,
- glisser-deposer un segment vers d'autres widgets.

## Elements visuels
- **Read head (ligne rouge)** : position courante de lecture.
- **Region (zone selectionnee)** : selection active, avec poignées.
- **Curseur de depart (ligne bleue pointillee)** : point de lecture sans region.
- **Markers (lignes jaunes)** : repères fixes, affiches dans la liste.

## Gestes souris
- **Clic gauche + glisser** : cree une region.
- **Clic gauche simple** : annule la region et place le curseur de depart.
- **Maj + glisser** : deplace toute la region (sans changer sa taille).
- **Ctrl + double-clic** : cree une region entre le marker precedent et suivant.
- **Ctrl + clic (mode marker)** : meme comportement que Ctrl + double-clic.
- **Clic molette** : place le curseur de depart et lance la lecture.

## Mode Marker
Active via le bouton "marker" (icone map-marker) :
- **Clic gauche** : ajoute un marker.
- **Glisser un marker** : deplace le marker.
- **Double-clic sur un marker** : supprime le marker.

## Liste des markers
Quand il y a des markers, la liste apparait :
- **Clic sur un item** : selectionne la region entre ce marker et le suivant.
- **Double-clic sur un item** : supprime le marker.

## Menu contextuel sur la region (clic droit)
Sur une region active :
- **Cut** : coupe la region de la waveform.
- **Export Selection** : exporte la region dans un nouveau WAV.
- **Drag Selection** : prepare un drag & drop du segment.
- **Add markers at edges** : pose des markers aux bords de la region.

## Playback
Boutons :
- Play (depuis le debut ou la region)
- Pause / Resume
- Stop
- Loop ON/OFF

## Raccourcis (si actifs)
Les tooltips donnent la reference :
- **Ctrl + Space** : Play
- **Space** : Pause/Resume
- **Alt + Space** : Stop
- **Ctrl + X** : Cut (region)
- **Ctrl + E** : Export (region)
- **Ctrl + Shift + G** : Add markers at edges

## Export / sauvegarde
- **Save** : overwrite ou copie (dialog).
- **Export Selection** : cree un nouveau fichier WAV dans le meme dossier,
  ajoute le sample a la librairie.

## Notes
- Si une region existe, le play se base sur `play_start` / `play_end`.
- Si aucune region n'existe, le play part du curseur de depart.
- Le rendu de waveform est calcule en fonction du zoom pour rester fluide.

