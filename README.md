# RoadToDev - Overview

Ce document decrit l'objectif du projet, son architecture generale, et une
liste des prochaines evolutions a faire. Il sert de point d'entree pour
comprendre l'ensemble avant d'aller dans les README specialises.

## Objectif du projet
Application audio desktop avec:
- enregistrement rapide (retro recording),
- gestion de librairies et de samples,
- edition/lecture (waveform),
- interface principale + interface remote (mobile).

## Architecture (vue d'ensemble)
### Backend (Python)
- `backend/models/` : modeles et logique metier (samples, recorder, contexte).
- `backend/services/` : services d'orchestration (settings, recorder, samples,
  notifications, remote control).
- `backend/db.py` : base de donnees SQLAlchemy.

### Frontend (PyQt)
- `frontend/main_window.py` : fenetre principale (tabs, settings).
- `frontend/record_widget.py` : widget flottant d'enregistrement.
- `frontend/sample_gui/` : liste, cartes, waveform editor.
- `frontend/settings_gui/` : pages de configuration.

### Frontend Remote (React)
- `frontend/remote_ui/` : UI mobile, servie par le serveur remote.

## Documentation liee
- Remote Control: [README_REMOTE_CONTROL.md](README_REMOTE_CONTROL.md)

## Trucs a faire (backlog)
- Refonte UI du Waveform Editor (ergonomie + outils visibles).
- Refonte UI du Directory Widget (lisibilite + actions rapides).
- Refactor les fichiers trop gros
- Concateneur de samples
- 

## Faits
- Clic droit sur la waveform pour lancer la lecture a cet endroit.