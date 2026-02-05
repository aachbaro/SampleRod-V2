# Sample Composer (Concat / Arrangement) — Spec & Plan

Ce document est une **spec** (spécification) : une description claire de ce qu’on veut construire, du comportement attendu, des contraintes, des cas limites, et d’un plan d’implémentation par étapes. L’objectif est de pouvoir développer vite sans perdre la cohérence de l’architecture.

## Objectif
Ajouter une nouvelle feature au même endroit que le `DirectoryWidget`, sous forme d’un **Compositeur de samples** :
- On démarre avec une **composition vide**.
- On **ajoute des segments (clips)** en drag & drop.
- On peut **réordonner** ces segments.
- L’app calcule un **aperçu audio concaténé** (un seul flux audio résultant) et l’affiche en waveform.
- Plus tard : export en fichier, crossfades, etc.

## Ce qu’on a déjà (réutilisable)
On a déjà un système de drag & drop interne basé sur `QMimeData` + payload picklé (`pickle`) :
- Depuis le waveform editor (MarkerManager) :
  - MIME `application/x-sample-slice-data`
  - Payload dict picklé avec `audio_data` (numpy float32), `sample_rate`, `name`
  - Fichier : `frontend/sample_gui/marker_manager.py` (`MarkerListWidget.startDrag`)
- Depuis une SampleCard :
  - MIME `application/x-sample-card`
  - Payload dict picklé avec `sample_id`
  - Fichier : `frontend/sample_gui/sample/sample_card_interactions.py`
- Côté réception, `DirectoryWidget` accepte ces MIME types et délègue à `DirectoryService` :
  - UI : `frontend/right_panel/directory/directory_widget.py`
  - Service : `backend/services/directory_service.py`

Le compositeur peut reprendre exactement la même idée, mais au lieu d’écrire un fichier dans un dossier, il **ajoute un clip** à une “composition en cours”.

## Terminologie
- **Clip / Segment** : une portion de son (un tableau audio + métadonnées).
- **Composition** : liste ordonnée de clips.
- **Format cible** : la “norme” interne de la composition (sample rate + nb de canaux).
- **Normalisation de format** : conversion d’un clip entrant vers le format cible (channels + resample + dtype).

## UX attendue (vision MVP)
Le compositeur a 3 zones principales :
1. Une **drop zone** (ou la liste elle-même) qui accepte les drops.
2. Une **Clip List** compacte (style “marker column” possible) :
   - Chaque ligne représente un clip.
   - Drag & drop interne pour **changer l’ordre**.
   - Actions : supprimer un clip, éventuellement rename “clip label”.
3. Une **Waveform Preview** du résultat concaténé :
   - Zoom / pan + lecture simple (idéalement).
   - Un indicateur de durée totale.

Le tout doit rester cohérent avec le style actuel : minimal, nuances de gris, boutons ronds 24px (comme `waveform_ui.py`).

## Où l’intégrer dans l’app
La zone de droite (actuellement “DirectoryWidget”) devient un **Right Panel** avec 2 modes :
- `Dossiers` (DirectoryWidget)
- `Compositeur` (nouveau)

Implémentation UI conseillée :
- `QTabWidget` pour commencer (simple et stable).
- Option plus “minimal UI” plus tard : `QStackedWidget` + 2 boutons.

## Règles de format (SR / canaux / dtype)
### Règle principale
Le **premier clip** ajouté initialise le **format cible** de la composition :
- `target_sr`
- `target_channels` (1 ou 2)

Tous les clips suivants sont **convertis** vers ce format cible au moment du drop.

### Conversion des canaux
- Mono → Stéréo : dupliquer `mono` sur L/R.
- Stéréo → Mono : moyenne `(L + R) / 2` (MVP).
- (Plus tard) permettre 5.1 etc si besoin, mais hors scope.

### Conversion de sample rate
On resample vers `target_sr`.

Implémentation recommandée (installée via `pip install scipy`) :
- `scipy.signal.resample_poly` (bonne qualité, rapide).
- Si SciPy indisponible : fallback “refuser le clip” avec un log clair.

### Dtype
Format interne recommandé :
- `float32` dans `[-1, 1]`

À l’export (plus tard), on choisira le format de sortie (wav int16/float32…).

## Données / Modèle (proposition)
### Clip
Champs minimum pour le MVP :
- `clip_id` (int)
- `label` (str)
- `audio` (np.ndarray float32, shape `(n,)` mono ou `(n,2)` stéréo)
- `sr` (int) après conversion
- `source` (dict) : infos provenance (sample_id, nom fichier, marker time…)
- `duration_s` (float) dérivé

### Composition
Champs minimum :
- `target_sr: int | None`
- `target_channels: int | None`
- `clips: list[Clip]`

Comportements :
- `add_clip(...)` ajoute + normalise + invalide le cache preview.
- `move_clip(from_idx, to_idx)` réordonne + invalide le cache.
- `remove_clip(idx)` supprime + invalide le cache.
- `render_preview()` renvoie la concat (avec cache).

## “Waveform Preview” : réutilisation du Waveform Editor (stratégie)
On a deux voies, la spec propose d’y aller progressivement.

### Option A (MVP pragmatique recommandé)
Créer un widget “preview” plus simple qui :
- Affiche le tableau concaténé.
- Lecture simple.
- Réutilise seulement des helpers (rendu / plot helpers) si possible.

Avantage : on évite de toucher trop vite au Waveform Editor complet.

### Option B (objectif long-terme)
Introduire une abstraction “source audio” dans le waveform editor :
- “fichier” (actuel)
- “buffer en mémoire” (compositeur)

But : partager au maximum `zoom`, `playback`, `render`, etc. avec `README_WAVEFORM_EDITOR.md`.

## Drag & Drop (spécification)
### Drops acceptés
Le compositeur accepte :
- `application/x-sample-slice-data`
  - On récupère directement `audio_data` + `sample_rate` + `name`.
  - On normalise vers le format cible, puis on ajoute un clip.
- `application/x-sample-card`
  - On charge l’audio du sample via `sample_id` (store/service existant).
  - On normalise, puis on ajoute un clip “entier”.

### Réordonnancement
La Clip List doit accepter un drag interne (MVP) :
- Drag source : les items de la Clip List
- Drop target : Clip List
- Action : move (pas copy)

## Étapes d’implémentation (MVP) — du tenant à l’aboutissant
1. **UI Right Panel**
   - Tenant : on a `DirectoryWidget` déjà en place.
   - Aboutissant : `RightPanel` avec 2 tabs (`Dossiers` / `Compositeur`) sans casser l’existant.
2. **ComposerWidget (squelette)**
   - Tenant : une page vide “Compositeur”.
   - Aboutissant : un layout avec drop zone + clip list + waveform preview placeholder.
3. **ComposerService / ComposerModel**
   - Tenant : aucune logique centrale.
   - Aboutissant : une classe qui stocke `Composition`, expose `add_clip_from_mime(mime)` et émet des signaux “composition changed”.
4. **Normalisation audio**
   - Tenant : des clips entrants peuvent être en mono/stéréo et SR divers.
   - Aboutissant : clips ajoutés toujours en `target_sr/target_channels`, float32.
5. **Clip List + reorder**
   - Tenant : affichage statique.
   - Aboutissant : ajout de clips + drag reorder interne + suppression.
6. **Waveform Preview**
   - Tenant : pas de rendu.
   - Aboutissant : affichage d’un plot représentant la concat + lecture simple.
7. **Qualité / perf**
   - Tenant : concat recalculée à chaque petite action peut devenir lourde.
   - Aboutissant : cache preview + recalcul uniquement sur “dirty”, logs clairs en dev.

## Résolution de problèmes (cas limites)
- **SR / channels non homogènes** :
  - Résolution : normaliser au drop (resample + convert channels).
- **Clips très longs** :
  - Résolution : cache concat + éventuellement downsample pour preview (plus tard).
- **Risques de clipping lors du downmix stéréo→mono** :
  - Résolution MVP : moyenne.
  - Plus tard : scaling -3 dB ou limiter.
- **Mémoire** :
  - Résolution : garder en float32, éviter des copies inutiles, concat via `np.concatenate` uniquement quand nécessaire.
- **UX drag** :
  - Résolution : feedback visuel (placeholder, surbrillance), accepter uniquement les MIME connus, log clair sinon.

## To-do list (roadmap)
MVP (priorité haute) :
- `RightPanel` tabs.
- `ComposerWidget` + `ComposerService/Model`.
- Drop slice + drop sample card.
- Normalisation SR/channels (SciPy).
- Clip List reorder + delete.
- Waveform preview + playback simple.

V1.1 :
- Export wav (dossier choisi, naming).
- Crossfade simple entre clips (optionnel).
- Undo/redo (inspiré du waveform editor).

V2 :
- Trim par clip (start/end dans la compo).
- “Snap to marker”, grille tempo, etc.
- Transitions avancées.

## Liens
- Waveform editor : `README_WAVEFORM_EDITOR.md`
- Remote control : `README_REMOTE_CONTROL.md`
