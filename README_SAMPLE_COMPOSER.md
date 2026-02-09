# Sample Composer (Concat / Arrangement) - Spec & Plan

Ce document est une spec (specification) : description claire de ce qu'on veut construire, du comportement attendu, des contraintes, des cas limites, et d'un plan d'implementation par etapes.

## Objectif
Ajouter une nouvelle feature au meme endroit que le `DirectoryWidget`, sous forme d'un Compositeur de samples :
- On demarre avec une composition vide.
- On ajoute des segments (clips) en drag & drop.
- On peut reordonner ces segments.
- L'app calcule un apercu audio concatene (un seul flux audio resultant) et l'affiche en waveform.
- Plus tard : export en fichier, crossfades, etc.

## Ce qu'on a deja (reutilisable)
On a deja un systeme de drag & drop interne base sur `QMimeData` + payload pickled (`pickle`) :
- Depuis le waveform editor (MarkerManager) :
  - MIME `application/x-sample-slice-data`
  - Payload dict pickled avec `audio_data` (numpy float32), `sample_rate`, `name`
  - Fichier : `frontend/sample_gui/marker_manager.py` (`MarkerListWidget.startDrag`)
- Depuis une SampleCard :
  - MIME `application/x-sample-card`
  - Payload dict pickled avec `sample_id`
  - Fichier : `frontend/sample_gui/sample/sample_card_interactions.py`
- Cote reception, `DirectoryWidget` accepte ces MIME types et delegue a `DirectoryService` :
  - UI : `frontend/right_panel/directory/directory_widget.py`
  - Service : `backend/services/directory_service.py`

Le compositeur reprend la meme idee, mais au lieu d'ecrire un fichier dans un dossier, il ajoute un clip a une composition en cours.

## Terminologie
- Clip / Segment : une portion de son (tableau audio + metadonnees).
- Composition : liste ordonnee de clips.
- Format cible : norme interne de la composition (sample rate + nb de canaux).
- Normalisation de format : conversion d'un clip entrant vers le format cible (channels + resample + dtype).

## UX attendue (vision MVP)
Le compositeur a 3 zones principales :
1. Une drop zone (ou la liste elle-meme) qui accepte les drops.
2. Une Clip List compacte :
   - Chaque ligne represente un clip.
   - Drag & drop interne pour changer l'ordre.
   - Actions : supprimer un clip, plus tard rename.
3. Une Waveform Preview du resultat concatene :
   - Lecture simple + loop.
   - Indicateur de duree totale.

Style : minimal, nuances de gris, boutons ronds 24px (comme `waveform_ui.py`).

## Ou l'integrer dans l'app
La zone de droite devient un Right Panel avec 2 modes :
- `Dossiers` (DirectoryWidget)
- `Compositeur` (nouveau)

Implementation UI conseillee :
- `QTabWidget` pour commencer (simple et stable).

## Regles de format (SR / canaux / dtype)
### Regle principale
Le premier clip ajoute initialise le format cible :
- `target_sr`
- `target_channels` (1 ou 2)

Tous les clips suivants sont convertis vers ce format au moment du drop.

### Conversion des canaux
- Mono -> Stereo : dupliquer mono sur L/R.
- Stereo -> Mono : moyenne (L + R) / 2 (MVP).

### Conversion sample rate
On resample vers `target_sr`.
- Recommande : `scipy.signal.resample_poly`.
- Si SciPy indisponible : refuser le clip (log clair).

### Dtype
Format interne recommande : `float32` dans [-1, 1].

## Waveform Preview : reutilisation du Waveform Editor
Mise a jour : on reutilise directement `WaveformWidget` pour le compositeur.
Consequences :
- Rendu identique a l'editeur (enveloppe min/max).
- Playback + loop disponibles.
- Actions destructives (cut/export) desactivees en mode compositeur.
- La selection reste disponible (region + play start).

## Drag & Drop (spec)
### Drops acceptes
- `application/x-sample-slice-data`
  - Recupere `audio_data` + `sample_rate` + `name`.
  - Normalise vers le format cible, puis ajoute un clip.
- `application/x-sample-card`
  - Charge l'audio via `sample_id` (store/service existant).
  - Normalise, puis ajoute un clip entier.

### Reordonnancement
La Clip List accepte un drag interne :
- Drag source : les items de la Clip List
- Drop target : Clip List
- Action : move (pas copy)

## Etapes d'implementation (MVP) - du tenant a l'aboutissant
1. UI Right Panel - Fait
2. ComposerWidget (layout) - Fait
3. ComposerModel - Fait
4. Normalisation audio (SR + canaux) - Fait (SciPy si dispo)
5. Clip List + reorder - Fait
6. Waveform Preview + playback - Fait (via WaveformWidget)
7. Qualite / perf - En cours

## Etat actuel (snapshot)
- OK Drop slices (markers) vers le compositeur.
- OK Format cible initialise par le 1er clip.
- OK Rendu + playback via WaveformWidget (meme rendu que l'editeur).
- OK Liste des clips sous la waveform, avec nom du sample.
- OK Selection d'une slice depuis la liste = region correspondante.
- OK Cut/export bloques (mode compositeur).
- TODO Drop de SampleCard (pas branche).
- TODO Actions par clip (rename, remove via boutons, etc.).

## Resolution de problemes (cas limites)
- SR / channels non homogenes : normaliser au drop.
- Clips tres longs : cache preview + downsample (plus tard).
- Clipping lors du downmix stereo->mono : moyenne (MVP), scaling plus tard.
- Memoire : float32, eviter copies inutiles.

## To-do list (roadmap)
MVP (priorite haute) :
- RightPanel tabs.
- ComposerWidget + ComposerModel.
- Drop slice + drop sample card.
- Normalisation SR/channels (SciPy).
- Clip List reorder + delete.
- Waveform preview + playback simple.

V1.1 :
- Export wav (dossier choisi, naming).
- Crossfade simple entre clips.
- Undo/redo (inspire du waveform editor).

V2 :
- Trim par clip (start/end dans la compo).
- Snap to marker, grille tempo.
- Transitions avancees.

## Liens
- Waveform editor : `README_WAVEFORM_EDITOR.md`
- Remote control : `README_REMOTE_CONTROL.md`
