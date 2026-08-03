# SampleRod

> Transformer n'importe quel son en matière musicale exploitable.

SampleRod n'est **pas un DAW**, pas un éditeur multipiste, pas un générateur IA.
C'est un atelier pour **capturer, découper, transformer et organiser du son**
— avec à terme une couche d'intelligence (Sample DNA + suggestions) qui fait
émerger des combinaisons que tu n'aurais pas trouvées seul.

- App desktop Python / PyQt (PySide6)
- Base SQLite locale (SQLAlchemy)
- Distribution Windows via Squirrel
- Site marchand + licences + feed de mise à jour : `./site/`
  (voir [site/README.md](site/README.md))

---

## Sommaire

1. [Vision produit](#vision-produit)
2. [Historique de chantier](#historique-de-chantier)
3. [Architecture actuelle](#architecture-actuelle)
4. [État du produit, module par module](#état-du-produit-module-par-module)
5. [Roadmap par phases](#roadmap-par-phases)
6. [Backlog court terme (tickets flottants)](#backlog-court-terme)
7. [Pièges à éviter](#pièges-à-éviter)
8. [Docs spécialisées](#docs-spécialisées)

---

## Vision produit

12 modules fonctionnels, organisés en couches. La progression se fait par
**phases** (voir plus bas) — pas tout en parallèle.

| #   | Module                   | Rôle                                                    |
| --- | ------------------------ | ------------------------------------------------------- |
| 1   | Core audio               | Enregistrement système, lecture, waveform, découpe      |
| 2   | File System Navigator    | Naviguer les dossiers locaux, indexation, DnD timeline  |
| 3   | Break Processing         | Détection de hits, quantize, randomisation cohérente    |
| 4   | Stem Separation          | Demucs (drums / bass / vocals / other)                  |
| 5   | Analyse musicale         | Détection de gamme, BPM, confiance                      |
| 6   | **Sample DNA**           | Chaque sample = objet (key, BPM, type, énergie, durée…) |
| 7   | Recherche intelligente   | Par nom, key, BPM, type, énergie                        |
| 8   | Suggestions automatiques | « Samples compatibles avec celui-ci » (rule-based)      |
| 9   | Pattern / Loop Detection | Segments répétitifs → blocs exploitables                |
| 10  | Resample Chain           | Pipeline créatif : slice → pitch → reverse → normalize  |
| 11  | Historique / Évolution   | Origine + transformations + versions par sample         |
| 12  | Mode Digging             | Exploration aléatoire intelligente, remise en surface   |

**Ce que SampleRod n'est pas :** un DAW multipiste, un synthé, un looper live,
un lecteur de streaming.

---

## Architecture produit : Atelier

SampleRod est organisé comme un atelier en deux espaces principaux :

### Réserve

Espace où l'on stocke et explore la matière sonore :

- historique d'enregistrement
- navigation dans les fichiers (filesystem réel)
- bibliothèque indexée
- recherche et filtres (futur)

La Réserve est la source de toute matière utilisée dans l'application.

### Labo

Espace de transformation :

- waveform editor
- break processing + générateur de patterns
- stem separation
- compositeur d'assemblage
- resample chain (futur)

Le Labo permet de transformer la matière.

### Flux de matière

Les éléments générés dans le Labo (stems, one-shots, loops, etc.)
ne sont pas des produits finaux.

Ils deviennent des artefacts réutilisables, qui peuvent être :

- réinjectés dans la Réserve
- retravaillés dans le Labo

Le Labo classique et l'atelier modulaire partagent maintenant un même
registre d'artefacts temporaires (`LabArtifactStore`) :

- un outil du Labo produit un `LabArtifact`
- l'artefact apparaît dans le plateau classique
- le même artefact peut aussi être consulté depuis le module modulaire
  `Artefacts`
- une sauvegarde transforme cet artefact temporaire en vrai fichier réutilisable

SampleRod fonctionne comme un cycle :
Réserve → Labo → Réserve

---

## Historique de chantier

**Règle importante :** à chaque changement notable de structure, de flux
produit, d'UI ou de service central, **mettre à jour cette section dans le
README le jour même**. Ce journal sert de mémoire courte du projet ; il doit
rester plus concret et plus rapide à relire qu'un diff Git.

### 27 juillet 2026

- Le design-core gagne une brique de mise en page : `frontend/ui/flow_layout.py`
  (`FlowLayout` / `make_flow_container`) reproduit l'effet `flex-wrap` du CSS —
  une liste passe seule de la colonne à la grille selon la largeur disponible.
- Les **Bins** sont refondus dessus : les bulles rondes répétitives (titre
  « BIN » + nom affiché deux fois) deviennent des chips minimalistes portant un
  seul texte, et le panneau se réorganise en lignes dès que la fenêtre du module
  s'élargit. Ajout du double-clic → Réserve et du drop de dossier → nouveau bin.
  Détail dans [REFACTOR_MODULAR.md](REFACTOR_MODULAR.md) et
  [UI_MODERNIZATION.md](UI_MODERNIZATION.md) (§6 bis).
- Le **générateur de break** perd sa grille de pattern à 6 lignes : vélocité,
  slice source et FX passent en tooltip de la case du hit, la grille devient
  carrée et compacte (34 px par step, 3 lignes au lieu de 6). Clic gauche sur
  un hit = le jouer seul, clic droit = ouvrir sa slice dans l'onglet
  `Découpage` pour corriger une classification douteuse avant de regénérer.
- Les combos et spins du générateur retrouvent des flèches visibles (rendues
  depuis le registre d'icônes via le nouveau `icon_qss_url`) et acceptent de
  nouveau la **molette** ; les champs BPM / bars sont élargis pour ne plus
  rogner leur valeur.
- **L'analyse d'un break est de nouveau restaurée au démarrage.** Le cache
  disque fonctionnait, mais `BreakModule.restore_state` reposait les marqueurs
  de session juste après — et poser des marqueurs déclenche `_clear_analysis()`
  (« Marqueurs restaurés. Relance l'analyse… »). Les marqueurs sauvegardés
  *sont* le découpage de l'analyse restaurée : quand ils correspondent, ils
  sont déjà posés et on ne touche plus à l'analyse. Un marqueur réellement
  déplacé invalide toujours les slices, comme avant.
- **Focus groupé : la Réserve ne retombe plus derrière tout le monde.**
  `raise_group()` réempilait les fenêtres dans leur ordre de **création**, donc
  la plus ancienne instance — la Réserve, toujours créée en premier — repassait
  au fond à chaque clic ailleurs. Le `WindowManager` mémorise désormais un
  ordre d'empilement mis à jour à chaque activation. Aucun comportement
  spécifique à la Réserve : elle était juste la plus vieille.
- **Défilement latéral proportionnel au zoom.** Shift+molette avançait d'un
  dixième de la durée du *fichier*, quel que soit le zoom : une fois zoomé sur
  une fenêtre de 0,5 s dans un fichier de 30 s, chaque cran sautait 3 s, soit
  six fenêtres d'un coup. Le pas suit maintenant la fenêtre visible (un
  dixième), donc la même sensation à tous les niveaux de zoom.
- **Grille au tempo réglable en direct.** Le point de départ est un point
  d'**ancrage**, pas un début : la grille rayonne des deux côtés et découpe
  tout le fichier. On peut donc se caler sur un passage franc en plein milieu
  du morceau, au lieu d'avoir à identifier le tout premier temps — justement
  l'endroit le moins lisible d'un enregistrement. Le panneau pose la grille
  tout de suite, puis se règle sous les yeux : un slider décale **toute** la
  grille d'un bloc, la longueur de tranche se change à la volée, et
  « Caler sur la sélection » déduit le BPM d'un passage dont on affirme le
  nombre de steps. Valider fige, Annuler retire tout. La pose de 213 marqueurs
  est passée de **7,0 s à 0,22 s** ; un décalage coûte 26 ms, d'où le direct.
- **Ménage des fichiers de travail temporaires** (`backend/services/temp_workspace.py`).
  Chaque rendu de pattern, aperçu, segment de preview et waveform éditée
  écrivait un WAV nommé par UUID que **rien ne supprimait jamais** : 602
  fichiers dans `break_pattern`, 286 dans `break_pattern_segments`, 381 Mo au
  total sur une machine de dev. Un balayage au démarrage ne garde que les plus
  récents de chaque dossier (plus une purge au-delà de 7 jours), et les
  chemins d'écriture les plus chauds s'élaguent au passage. Le fichier en
  cours de lecture est protégé.
- **Découpage au tempo dans l'éditeur waveform.** Nouveau bouton `▦` : on pose
  un marqueur sur le premier temps, on choisit un **BPM** et une **longueur de
  tranche en steps** (1 step = une double-croche, 16 = une mesure — mêmes
  conventions que le générateur de break), et la grille de marqueurs est
  extrapolée jusqu'à la fin. Le popup annonce le nombre de marqueurs et la
  durée d'une tranche **avant** de poser quoi que ce soit. Objectif : recouper
  un morceau à tempo stable en patterns, puis les recomposer dans le
  Compositeur. Les marqueurs existants sont conservés (fusion sans doublon) et
  toute la grille s'annule en un seul `Ctrl+Z`.
- **Playhead façon séquenceur dans le générateur.** Le step en cours de lecture
  s'illumine pendant la preview, et la grille défile pour le garder visible. Le
  coût est négligeable : un timer à 25 im/s qui ne repeint que les deux
  cellules concernées (celle qu'on quitte, celle qu'on éclaire), en restaurant
  les pinceaux d'origine — aucun recalcul de la grille. L'origine suit le clip
  réellement joué (pattern entier, plage bouclée, lecture depuis un step).
- **La grille du pattern n'est plus coupée à droite.** Un pattern de 2 bars
  (32 steps) dépassait la largeur de la fenêtre sans que la barre de défilement
  puisse s'afficher, faute de hauteur. La table réserve désormais sa place.
- **Sélection d'une plage de steps au glisser sur les numéros du pattern.**
  Glisser sur l'en-tête sélectionne une portion du break et la joue en boucle
  (le clic simple garde son rôle : jouer depuis ce step). Clic droit sur la
  sélection → **verrouiller** (garde le contenu exact au prochain `Generer`),
  **ancrer sur le type** (fige la famille du coup, pas la source), ou
  **exporter la plage en artefact**. Effet de bord corrigé au passage : poser
  un verrou ou une ancre ne marque plus le pattern « à regénérer » — ça ne
  change pas son audio, et ça bloquait l'enchaînement figer → exporter.
- **Ctrl+double-clic puis glisser = drag de la slice, depuis la waveform.**
  Le geste sélectionnait déjà la zone entre deux marqueurs ; garder le bouton
  enfoncé et bouger part maintenant en drag, exactement comme depuis la liste
  de marqueurs. Le payload MIME `application/x-sample-slice-data` est construit
  par un `selection_payload()` désormais partagé entre les deux chemins, donc
  les deux gestes produisent la même slice au bit près.
- **Le BPM du générateur suit la preview en cours de lecture.** Le tempo est
  *cuit* dans le rendu : rejouer le même fichier plus vite pitcherait tout le
  break et ne correspondrait plus à ce que « Rendre artefact » produit. Le
  changement de BPM déclenche donc un **re-rendu court** (debounce 200 ms), la
  boucle en cours continuant de tourner jusqu'à ce que le nouveau clip soit
  prêt — et il relance exactement le même extrait (pattern entier, plage de
  boucle, hit isolé). Le rendu d'artefact reste prioritaire et annule un
  re-rendu de preview en attente.
- **Vue `Indexe` : le détail passe sous la table.** Il occupait une colonne de
  droite de ~460 px pour ne servir qu'à écouter le sample sélectionné. La table
  récupère toute la largeur ; en dessous, une bande compacte = nom + statut,
  chemin, une ligne de métadonnées (les deux élidées avec le texte complet en
  tooltip), puis la `SampleCard` avec son slider. Les deux boutons « Ouvrir le
  dossier source » / « Ouvrir dans la waveform » sont retirés : ils doublonnent
  le menu contextuel de la table et le double-clic.
- **Le Break analyse enfin la waveform affichée, pas le fichier d'origine.**
  Les éditions de waveform (coupe…) ne vivent qu'en mémoire, alors que
  l'analyse, la quantize, le rendu de pattern et le drag d'une slice relisent
  tous l'audio depuis le chemin source — couper la moitié d'un break sortait
  donc des slices hors de ce qu'on voit. La waveform éditée est désormais
  **matérialisée** dans `%TEMP%/SampleRod/break_edits/` (en float32, pour ne
  pas dégrader la matière exportée) et sert de source de travail à toute la
  chaîne. Le fichier ouvert reste l'identité affichée et sauvegardée en session.
- **La liste de slices s'édite sans re-analyse complète.** Supprimer une slice
  la **fusionne** avec la précédente, qui reprend son territoire et garde sa
  classe (fini le trou). Poser un marqueur **coupe la slice concernée en deux
  et détecte le type de chaque moitié**, à sa place dans la liste. Déplacer un
  marqueur **recale les deux frontières voisines** et reclasse les slices
  touchées, donc la sélection jouée depuis la liste suit le nouveau découpage.
  Ces trois gestes s'appuient sur un nouveau point d'entrée
  `analyzer.classify_segment()` qui mesure un segment isolé.
- **Les corrections de classe des hits sont maintenant persistantes.** Une
  analyse (ou un simple redécoupage) re-classait tous les hits et écrasait le
  travail manuel : `DrumAnalysisService` mémorise désormais ces corrections à
  part du cache d'analyse, dans `~/.samplerod/break_labels/`, **indexées par la
  position du hit** et non par son index — elles survivent donc au
  renumérotage, aux re-analyses et aux sessions. Un bouton `⟲` dans la barre
  `Découpage` (visible seulement s'il y a des corrections) permet de revenir à
  la classification automatique.

### 23 juillet 2026

- Les déplacements de samples suivis en base passent maintenant par un chemin
  asynchrone dans `backend/services/sample_service.py` : le `move()` ne bloque
  plus le thread UI pendant le `shutil.move`, ce qui doit lisser les glisser-
  déposer depuis la vue `Indexe`, les bins et les autres outils de la Réserve.
- Correctif de démarrage : `frontend/labo/artifact_tray.py` importe maintenant
  explicitement `QEvent`, ce qui supprime le crash qui empêchait l’ouverture de
  la première fenêtre de l’Atelier au lancement.
- La vue `Indexe` expose maintenant une vraie colonne `Date`, alimentée par
  `created_at`, avec tri chronologique natif via l’en-tête pour passer du plus
  récent au plus vieux sans quitter la bibliothèque indexée.
- La vue `Indexe` traite maintenant aussi les ajouts, changements de durée et
  fins d’analyse en **mode incrémental**, et décale le rebuild de navigation en
  debounce. Le but est de supprimer les freezes visibles lors des enregistrements
  ou des mises à jour simples pendant que l’index est ouvert.

### 21 juillet 2026

- Ergonomie de la vue `Historique` renforcée : le header de `SampleListWidget`
  perd son bouton d'import parasite, les contrôles passent sur les icônes
  Tabler et le menu `...` des cartes expose maintenant les raccourcis utiles
  (`Ctrl+R`, `Ctrl+D`, `Ctrl+Shift+D`, `Ctrl+Right`).
- La navigation clavier de l'historique devient pilotable sans souris :
  flèches haut/bas pour changer le focus, flèches gauche/droite pour seek de
  1 seconde, `Space` pour play/stop, `Shift+Space` pour relancer depuis le
  début, `Ctrl+Right` pour ouvrir dans la waveform du Labo.
- Le header visuel de l'historique est maintenant masqué dans la Réserve :
  plus de mini-boutons parasites au-dessus des cartes, et après suppression
  d'un sample le focus repart automatiquement sur l'entrée suivante pour garder
  un flux de navigation continu.
- Les anciennes actions flottantes des `SampleCard` historiques sont désormais
  masquées explicitement pour éviter toute icône empilée.
- La vue `Indexe` converge maintenant vers `Historique` : preview clavier
  identique (haut/bas, gauche/droite, `Space`, `Shift+Space`), menu contextuel
  avec raccourcis visibles, actions de détail simplifiées autour de la
  waveform, et preview card compacte avec un vrai espace entre bouton play et
  slider.
- La vue `Indexe` expose maintenant une vraie colonne `Gamme` et un filtre de
  gamme dédié, alimenté dynamiquement par les samples visibles du scope
  courant, avec accès rapide `Filtrer par ...` depuis le menu contextuel.
- La vue `Indexe` affiche maintenant le poids de chaque sample et un cumul
  `visible` / `total indexé`, calculés en arrière-plan pour garder une
  navigation fluide même sur une grosse librairie.
- La suppression clavier (`Ctrl+D`) dans la vue `Indexe` passe maintenant par
  un chemin direct côté `LibraryWidget` avec arrêt audio explicite et refresh
  de sélection moins réentrant, pour éviter les gels au moment du delete.
- La vue `Indexe` supprime maintenant une ligne de façon optimiste puis
  diffère/coalesce le rebuild complet (navigation + table + détail), pour
  éviter le gros freeze que provoquait un refresh synchrone après delete.
- Le chemin de suppression de la Réserve est maintenant instrumenté avec des
  logs de perf (`SampleService`, `Indexe`, `Historique`, `Dossiers`) pour
  localiser plus vite les freezes restants après delete.
- Les `SampleCard` de l'historique exportent maintenant aussi une URL fichier
  dans leur drag : un glisser vers le bureau ou l'explorateur Windows copie
  donc le sample, sans perdre le MIME interne déjà utilisé par le Labo.
- Les réglages sont maintenant extraits dans `frontend/settings_gui/settings_panel.py`
  pour être réutilisés à la fois dans l'onglet classique et comme vrai module
  `Paramètres` du workspace modulaire ; le bouton du `Workspace` ouvre donc
  désormais un module fermable, au lieu de renvoyer vers l'ancienne fenêtre.

- Les modules modulaires **Break** et **Compositeur** ne sont plus de simples
  widgets bruts : `frontend/modular/break_module.py` et
  `frontend/modular/composer_module.py` ajoutent maintenant une vraie coque à
  onglets, avec croix custom, bouton `+` et persistance de session.
- Le module **Break** mémorise désormais les fichiers ouverts **et** leurs
  marqueurs manuels d'un onglet à l'autre ; `BreakWidget` expose pour cela une
  petite API additive (`current_path`, `set_markers`, `cleanup`,
  `set_drop_replace_enabled`) sans casser l'usage classique du Labo.
- Le module **Compositeur** mémorise désormais plusieurs compositions en
  parallèle. Les clips provenant d'un fichier source entier réutilisent leur
  chemin original ; les clips non reconstructibles proprement (slice draggée,
  silence, état audio matérialisé) sont sauvegardés sous forme de WAV
  temporaires dans `%TEMP%/SampleRod/composer_clips` pour restaurer la session.
- Le drop ciblé du Compositeur est maintenant cadré : drop sur le **contenu**
  d'un onglet = ajout normal à la composition courante ; drop sur la **barre
  d'onglets** = création d'une nouvelle composition alimentée avec les fichiers
  déposés.

### 20 juillet 2026

- Modernisation du socle UI partagé : la barre interne du waveform passe aux
  icônes Tabler (`frontend/sample_gui/waveform/waveform_ui.py`) et
  `HoverIconButton` devient un shim de compatibilité sans dépendance directe à
  `qtawesome`, ce qui garde le classique, le compositeur et les sample cards alignés.
- Uniformisation visible des contrôles Atelier : coin haut-droit de
  `frontend/main_window.py`, actions de filtre de `frontend/reserve/reserve_pane.py`
  et ajout des Bins migrés vers `IconButton`.
- Les modules modulaires **Break**, **Compositeur** et **Bins** sont maintenant
  enregistrés dans `frontend/modular/modules_setup.py` et reconnectés au
  `WindowManager` pour les ponts utiles avec la Réserve.
- Les artefacts du Labo gagnent une première lignée légère
  (`parent_ids`, `operation`) dans `frontend/labo/lab_artifact.py`.
- Le drag and drop d’artefact transporte maintenant un MIME dédié
  `application/x-samplerod-artifact` en plus du fichier, ce qui prépare les
  échanges inter-fenêtres sans casser les drops existants.
- Centralisation du flux d'artefacts du Labo via `frontend/labo/artifact_store.py`
  (`LabArtifactStore`) partagé entre atelier classique et modulaire.
- Le plateau d'artefacts du Labo classique n'est plus une poche d'état locale :
  `artifact_tray.py` relaie désormais save/open/remove vers le store central.
- Ajout du module modulaire `Artefacts` (`frontend/modular/artifact_module.py`)
  branché au `WindowManager`.
- Le module `Artefacts` est désormais **singleton, stable et non supprimable** :
  une seule instance, masquable mais ni duplicable ni fermable définitivement.
- Support du drag and drop de **slices / sélection waveform** vers les outils
  audio du Labo : `Waveform`, `Break`, `Stems` et `Waveform` modulaire.
- Le pipeline de drop audio sait maintenant convertir une slice dragguée en WAV
  temporaire au moment du drop, sans créer de fichier parasite au simple hover.

### 24 avril 2026

- Refonte de l'architecture produit autour du modèle `Réserve → Labo → Réserve`.
- Intégration du Break Processing dans le Labo avec UI complète.
- Intégration de la Stem Separation asynchrone avec suivi de tâches.
- Détection de gamme intégrée au flux principal et exposition de `dominant_note`.

## Architecture actuelle

```
samplerod/
├── app.py                          # entry point desktop (PySide6)
├── backend/
│   ├── db.py                       # SQLAlchemy, sqlite:///sample.db
│   ├── models/
│   │   ├── sample.py               # Sample (+ dominant_note, analyzed_at)
│   │   ├── SampleLibrary.py
│   │   ├── AppContext.py
│   │   ├── recorder_worker.py
│   │   ├── normalize_worker.py
│   │   ├── integrity_worker.py
│   │   └── screenshot.py
│   └── services/
│       ├── sample_service.py           # CRUD samples + cache + signaux Qt
│       ├── directory_service.py
│       ├── recorder_service.py
│       ├── remote_control_service.py   # FastAPI/WS, sert frontend/remote_ui
│       ├── screenshot_service.py
│       ├── settings_service.py
│       ├── notification_service.py
│       ├── library_service.py          # gestion des bibliothèques externes
│       ├── audio_metadata.py           # lecture metadata audio (durée, samplerate)
│       ├── drum_analysis_service.py    # détection transients, classification hits
│       ├── scale_analysis_service.py   # détection de gamme (librosa)
│       └── stem_separator_service.py   # séparation de stems (Demucs)
├── frontend/
│   ├── main_window.py              # fenêtre principale
│   ├── record_widget.py            # widget flottant d'enregistrement
│   ├── record_widget_ui.py
│   ├── custom_widgets.py
│   ├── notification_widgets.py
│   ├── splash.py
│   ├── styles/
│   │   └── theme.py                # feuille de style globale
│   ├── activity/                   # système de tâches de fond
│   │   ├── activity_service.py
│   │   └── activity_tray.py        # barre de progression flottante
│   ├── workspace/
│   │   └── atelier_widget.py       # layout principal Réserve / Labo
│   ├── reserve/                    # espace Réserve
│   │   ├── reserve_pane.py
│   │   ├── reserve_actions.py
│   │   └── reserve_entry.py
│   ├── labo/                       # espace Labo (module complet)
│   │   ├── labo_widget.py          # conteneur tabs : Waveform / Break / Stems / Compositeur
│   │   ├── waveform_tool.py        # waveform editor du Labo
│   │   ├── waveform_tool_dnd.py    # drag & drop vers le Labo
│   │   ├── break_widget.py         # analyseur audio + découpeur + annotation hits
│   │   ├── break_panel.py          # panneau de contrôle break
│   │   ├── break_generator_panel.py # générateur de patterns (knobs + 4 onglets)
│   │   ├── stem_separator_tool.py  # interface séparation de stems
│   │   ├── artifact_tray.py        # barre d'artefacts générés
│   │   ├── artifact_store.py       # registre partagé des artefacts du Labo
│   │   ├── bins_panel.py           # bacs de rangement des slices
│   │   ├── lab_artifact.py         # modèle d'artefact Labo
│   │   └── audio_drop.py           # zone de dépôt audio
│   ├── modular/                    # atelier modulaire (refactor incrémental)
│   │   ├── window_manager.py       # orchestration des fenêtres/modules
│   │   ├── workspace_window.py     # centre de contrôle modulaire
│   │   ├── waveform_module.py      # conteneur à onglets pour plusieurs waveforms
│   │   ├── break_module.py         # conteneur à onglets pour plusieurs breaks
│   │   ├── composer_module.py      # conteneur à onglets pour plusieurs compositions
│   │   ├── artifact_module.py      # navigateur modulaire des artefacts
│   │   └── modules_setup.py        # registre des modules disponibles
│   ├── ui/                         # design-core partagé du refactor modulaire
│   │   ├── icons.py
│   │   ├── icon_button.py
│   │   ├── flow_layout.py          # FlowLayout (colonne <-> grille, flex wrap)
│   │   └── fast_tooltip.py
│   ├── library_gui/                # gestion des bibliothèques
│   │   ├── library_widget.py
│   │   ├── library_detail.py
│   │   └── library_ui.py
│   ├── sample_gui/                 # liste, cartes, waveform editor Réserve
│   │   ├── wave_form.py
│   │   ├── marker_manager.py
│   │   ├── sample/                 # refactorisé en sous-modules
│   │   │   ├── sample_card.py + _actions / _interactions / _move
│   │   │   ├── sample_card_playback / _selection / _status / _ui / _waveform
│   │   │   └── sample_list.py + _cards / _dragdrop / _import / _normalize
│   │   │       + _pagination / _selection / _service / _ui
│   │   └── waveform/               # refactorisé en sous-modules
│   │       ├── waveform_ui.py + _loader / _markers / _playback / _renderer
│   │       └── _interactions / _navigation / _region / _save / _shortcuts
│   │           + history_stack / waveform_history / waveform_plot_helpers
│   ├── right_panel/
│   │   ├── tab_bar.py
│   │   ├── tools_panel.py
│   │   ├── directory/              # file browser (history, preview, DnD)
│   │   └── composer/               # timeline d'assemblage
│   ├── screenshot_gui/
│   ├── settings_gui/               # audio / display / libraries / remote / screenshot
│   └── remote_ui/                  # UI React pour mobile
├── prototypes/
│   ├── drum_detector/              # référence algo (migré → drum_analysis_service)
│   └── scale_detector/             # référence algo (migré → scale_analysis_service)
├── tools/squirrel/                 # toolchain release Windows
├── scripts/                        # build_release.ps1 + publish_release.ps1
├── site/                           # site marchand Django (samplerod.pascuans.dev)
├── SampleRod.spec                  # PyInstaller
├── VERSION                         # 0.1.3
└── sample.db                       # base locale
```

**Trois couches qu'il faut garder séparées :**

- `backend/models/` = données + logique métier (indépendant de Qt)
- `backend/services/` = orchestration (connaît Qt pour les signaux, pas l'UI)
- `frontend/` = UI pure, consomme les services

**Refactor en cours à garder lisible :**

- l'onglet `Atelier` classique reste la référence fonctionnelle
- `frontend/modular/` prépare l'atelier multi-fenêtres, sans casser le flux existant
- les artefacts du Labo ne vivent plus seulement dans un widget local :
  `artifact_store.py` sert de point de partage entre classique et modulaire

**Un pattern précieux à conserver :** les prototypes (`drum_detector`,
`scale_detector`) sont volontairement conservés comme référence algorithmique,
même une fois leur code migré en service. Le plan d'intégration tient en
une phrase : **« un proto devient un `backend/services/<nom>_service.py` une
fois son algo stable »** — c'est fait pour les deux.

---

## État du produit, module par module

Légende : [x] opérationnel · [~] partiel · [ ] à faire

### Module 1 — Core audio [~]

- [x] Enregistrement système (`recorder_service`, `recorder_worker`)
- [x] Lecture + waveform (`sample_gui/waveform` — refactorisé en sous-modules)
- [x] Découpe / sélection sur waveform
- [x] Normalisation (`normalize_worker`)
- [x] Assemblage basique (`right_panel/composer`)
- [ ] Export propre (formats, métadonnées, cible)
- [ ] Bugs connus de lecture en mode loop (voir backlog)

### Module 2 — File System Navigator [~]

- [x] `right_panel/directory/` — navigation, history, preview, DnD
- [x] Drag & drop vers la composer timeline
- [ ] Indexation persistante (scan dossier → DB)
- [ ] Lien avec les futurs attributs Sample DNA

### Module 3 — Break Processing [x]

- [x] `drum_analysis_service.py` : détection transients, classification hits,
      quantize, reanalyse depuis marqueurs manuels
- [x] `labo/break_widget.py` : UI complète (waveform annotée, bacs de hits,
      déclencher analyse depuis marqueurs sans découpe auto)
- [x] `labo/break_generator_panel.py` : générateur de patterns (4 onglets :
      Groove / Variations / Pitch / Rendu, knobs, preview en boucle)
- [x] Corrections manuelles de classification persistantes
      (`~/.samplerod/break_labels/`, réappliquées après chaque analyse)
- [x] Édition incrémentale du découpage (fusion / split / déplacement de
      frontière) sans re-analyse complète
- [x] `labo/bins_panel.py` : rangement et lecture des slices par type (kick / snare / hat…)
- [x] `labo/artifact_tray.py` : barre d'artefacts produits par le Labo
- [ ] Export one-shots individuel vers la Réserve (UI non finalisée)

### Module 4 — Stem Separation [~]

- [x] `stem_separator_service.py` : séparation Demucs en sous-process (queue async)
- [x] `labo/stem_separator_tool.py` : UI de lancement + suivi progression
- [x] `frontend/activity/` : système ActivityService + ActivityTrayWidget pour
      toutes les tâches de fond longues (stems, analyse, etc.)
- [x] Les stems tombent dans le flux d'artefacts partagé du Labo
- [ ] Réinjection automatique des stems dans la Réserve

### Module 5 — Analyse musicale [~]

- [x] `scale_analysis_service.py` : détection de gamme (librosa), intégré dans l'app
- [x] Badge de tonalité sur les sample cards (`dominant_note` affiché)
- [x] Filtre « Compatible avec » dans la liste de samples
- [ ] Détection BPM
- [ ] Score de confiance exposé à l'UI
- [ ] Service unifié `analysis_service.py` qui wrappe gamme + BPM + énergie

### Module 6 — Sample DNA [~] ← chantier en cours

Le modèle `Sample` stocke maintenant :

```python
id, path, name, duration, created_at, analyzed_at, dominant_note
```

Il manque encore les colonnes suivantes pour compléter le DNA :

- `key_confidence` (float)
- `bpm` (float) + `bpm_confidence` (float)
- `sample_type` (enum: drum / texture / melodic / vocal / fx / loop / one_shot)
- `energy` (enum low/mid/high ou float RMS normalisé)
- `spectral_profile` (JSON optionnel, plus tard)

**Important :** les migrations Alembic ne sont pas encore en place.
Les colonnes actuelles (`analyzed_at`, `dominant_note`) ont été ajoutées
manuellement. Toute nouvelle colonne DNA doit s'accompagner d'une migration
versionnée — c'est le moment d'installer Alembic.

### Module 7 — Recherche intelligente [~]

- [x] Filtre « Compatible avec » (même `dominant_note`) sur la liste principale
- [ ] Filtres multi-critères (BPM, type, énergie) — dépend du module 6 complet

### Module 8 — Suggestions automatiques [ ]

Règles simples au départ, pas d'IA :

- sample sélectionné → top N samples de la DB qui matchent key + BPM
- si type = drum → propose des textures matchées
- si type = melodic → propose des breaks à ce tempo

### Module 9 — Pattern / Loop Detection [ ]

Phase avancée. Utilise les hits du drum_detector pour repérer les cycles
répétitifs dans un long enregistrement et les exporter comme loops.

### Module 10 — Resample Chain [ ]

Stack d'actions sur un sample : slice → pitch → reverse → normalize → export.
UI type « liste d'étapes réorganisable », pas un graphe de nodes.

### Module 11 — Historique / Évolution [ ]

Table annexe `SampleLineage` (parent_id, transformation, created_at, params).
Permet de remonter de n'importe quel sample jusqu'à sa source.

### Module 12 — Mode Digging [ ]

Vue alternative à la liste : propose des combinaisons aléatoires cohérentes,
ressort des samples oubliés depuis > 30 jours. Nécessite Sample DNA.

### Infra & release [x]

- [x] Build Windows via PyInstaller + Squirrel (`scripts/build_release.ps1`)
- [x] Script de publication `scripts/publish_release.ps1`
- [x] Site marchand Django (Stripe, OIDC, feed tokenisé, `/api/admin/publish`)
- [x] Tunnel Cloudflare `samplerod.pascuans.dev`

### Remote control [x]

- [x] `backend/services/remote_control_service.py` + `frontend/remote_ui/`
      (React/Vite) — pilotage mobile de l'enregistrement.

---

## Roadmap par phases

**Principe :** on ne passe à une phase qu'une fois la précédente propre.
Pas d'intelligence par-dessus une base bancale.

### ✅ Phase 1 — Solidifier (terminée)

- Core audio stabilisé (waveform refactorisée en sous-modules)
- File browser `right_panel/directory/` complet
- README unifié (ce document)
- `record_widget` refactorisé (UI / logique séparées)

### ✅ Phase 2 — Identité produit (terminée)

- `drum_analysis_service.py` intégré depuis le prototype
- UI Break complète dans `frontend/labo/` (break_widget, bins_panel, generator)
- `stem_separator_service.py` + `stem_separator_tool.py` (Demucs async)
- `activity_service.py` + `activity_tray.py` pour toutes les tâches longues

### 🟠 Phase 3 — Intelligence (Sample DNA) — en cours

_Tu es ici._

- [x] `scale_analysis_service.py` intégré (détection gamme)
- [x] `dominant_note` stocké en DB, badge dans l'UI
- [x] Filtre « Compatible avec » (même tonalité)
- [ ] Migrations Alembic à mettre en place (colonne par colonne, versionnées)
- [ ] Détection BPM (`librosa.beat_track`)
- [ ] Colonnes DNA restantes : `bpm`, `sample_type`, `energy`, `key_confidence`
- [ ] Backfill async de la DB existante

### 🟡 Phase 4 — Magie

- Recherche avancée multi-filtres (key / BPM / type / énergie)
- Moteur de suggestions rule-based
- UI « samples compatibles avec celui-ci »

### 🔵 Phase 5 — Avancé

- Pattern / loop detection
- Resample chain (pipeline créatif)
- Historique / lineage
- Mode Digging

---

## Backlog court terme

Bugs et petites features à traiter :

**UX / bugs**

- Lecture loop : le clic gauche sur la waveform après la barre en mode loop
  replace la tête au mauvais endroit (décalage = temps de lecture en cours)
- Double bordure jaune quand on renomme un sample et on en focus un autre
- Échap pour annuler le renaming dans directory widget
- Boutons des items du directory widget toujours visibles (overlay sur nom)
- Animation sur ajout / retrait d'un sample dans la liste
- Loader à la fermeture de l'application

**Fonctionnalités rapides**

- Préfixeur par sélection multiple (nom commun + nom initial)
- Fonction `goto_sample(id)` → scroll + focus dans la liste
  (utile pour les notifs et les liens remote)
- Export one-shots depuis les bacs Break vers la Réserve
- Réinjection automatique des stems dans la Réserve après séparation

**Dette tech**

- Le renderer de waveform plante sur un fichier **mono**
  (`waveform_data[i0:i1, idx]` avec `idx=1` sur un seul canal) — repéré en
  passant, non corrigé.

- Mettre en place Alembic (migrations versionnées) — obligatoire avant
  d'ajouter de nouvelles colonnes DNA
- Ajouter `bpm` et `sample_type` au modèle Sample (avec migration Alembic)

**Déjà faits (gardé comme trace)**

- Concaténateur de samples ✓
- `Ctrl+R` pour renommer ✓
- Capture d'écran ✓
- Clic droit sur waveform = lecture à cet endroit ✓
- Refonte UI Waveform Editor ✓
- Refactor sample_card + sample_list ✓
- Arborescence `frontend/` regroupée ✓
- Refonte UI Directory Widget ✓
- Break Processing intégré (service + UI complète dans Labo) ✓
- Stem Separation avec Demucs async ✓
- Détection de gamme intégrée + badge dominant_note ✓
- Filtre « Compatible avec » (même tonalité) ✓
- ActivityService + ActivityTrayWidget (tâches de fond) ✓
- KnobWidget personnalisé (potentiomètres sans scroll molette) ✓
- Générateur de patterns Break (4 onglets, preview en boucle) ✓
- `record_widget` refactorisé (UI / logique séparées) ✓
- Drag & drop externe des `SampleCard` vers Windows/Explorateur (historique + index) ✓
- Indexe: toggle persistant de la navigation + renommage allégé sans rebuild complet ✓
- Labo: renommage du fichier courant depuis Waveform + drop manuel et renommage des artefacts ✓
- Indexe: colonne RMS retirée, poids affiché en Mo pour une lecture plus dense ✓

---

## Pièges à éviter

1. **Ne pas glisser vers un DAW.** Multipiste, MIDI, mix — ça n'a rien à faire
   dans SampleRod. Si un jour c'est nécessaire, c'est un autre produit.
2. **Ne pas faire l'intelligence avant le DNA.** Une suggestion bâtie sur une
   détection de key fausse 40% du temps, ça détruit la confiance dans le
   produit. Sample DNA = fondation non-négociable de la phase 4+.
3. **Ne pas ouvrir 4 features en parallèle.** Finir == tester en conditions
   réelles + intégrer dans le flux utilisateur. Une feature pas finie est de la
   dette, pas un acquis.
4. **Ne pas coupler les prototypes à l'app.** Le pattern actuel (prototypes
   isolés comme référence) est bon. On ne migre un proto en service qu'une fois
   l'algo stable.
5. **Ne pas laisser la DB dériver.** Chaque changement de modèle = migration
   Alembic versionnée. Pas de « drop sample.db et reconstruis ». Alembic est
   prioritaire avant toute nouvelle colonne DNA.

---

## Docs spécialisées

Ces README restent utiles comme références de modules. Le présent document
est le point d'entrée ; les suivants entrent dans les détails d'implémentation.

- [REFACTOR_MODULAR.md](REFACTOR_MODULAR.md) — état du chantier atelier modulaire
- [site/README.md](site/README.md) — le site marchand (Stripe, OIDC, feed)
- [README_WAVEFORM_EDITOR.md](README_WAVEFORM_EDITOR.md)
- [README_SAMPLE_COMPOSER.md](README_SAMPLE_COMPOSER.md)
- [README_REMOTE_CONTROL.md](README_REMOTE_CONTROL.md)
- [README_SCREENSHOT_MODULE.md](README_SCREENSHOT_MODULE.md)
- [README_DRAG_DROP.md](README_DRAG_DROP.md)
- [README_UI_PYQT.md](README_UI_PYQT.md)
- [README_DEPLOYMENT.md](README_DEPLOYMENT.md)
- [prototypes/drum_detector/README.md](prototypes/drum_detector/README.md)
- [prototypes/scale_detector/README.md](prototypes/scale_detector/README.md)
- [VERIFICATION_SILENCE.md](VERIFICATION_SILENCE.md)

---

_Dernière mise à jour : 27 juillet 2026 — version courante : voir `VERSION`._
