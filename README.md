# SampleRod - Overview

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
- Waveform Editor: [README_WAVEFORM_EDITOR.md](README_WAVEFORM_EDITOR.md)

## Trucs a faire (backlog)
- Refactor `record_widget.py` (separer UI / logique comme les autres).
- Refactor les fichiers trop gros
- Concateneur de samples
- Modifier l'ui pour le record widget
- ajouter la capture d'ecran
- ajouter le ctrl R pour renommer un sample
- ajouter echape pour annuler le renaming dans le directory widget
- faire un loader pour la fermeture de l'application
- Problème: Lorsque je click gauche sur la waveform pendant le playback apres la barre de lecture en mode loop enabled, ça deplace la tete de lecture apres le marqueur de selection, comme si ça faisait playstart + temps de lecture en cours
- ajouter une animation sur lajout et le retrait de sample dans la liste
- il semble y avoir un probleme sur le sample focus quand je suis entrain d'editer le nom d'un sample, si jen focus un autre il y a deux sample avec la bordure jaune
- peut etre un ajouteur de prefix sur selection, genre la jai une succession de sample qui sont a peu pres pareils, je pourrais les selectionner et mettre un nom commun et leurs nom initiaux apres
- faire une fonction qui prend l'id d'un sample et temmene vers ce sample dans la liste, pour pouvoir double cliquer sur une notif ou un sample dans 


## Faits
- Clic droit sur la waveform pour lancer la lecture a cet endroit.
- Refonte UI du Waveform Editor (ergonomie + outils visibles).
- Refactor `sample_card.py` et `sample_list.py` (alleger + organiser comme Waveform).
- Revoir l'arborescence `frontend/` (regrouper widgets / views / controllers).
- Refonte UI du Directory Widget (lisibilite + actions rapides).
