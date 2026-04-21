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
2. [Architecture actuelle](#architecture-actuelle)
3. [État du produit, module par module](#état-du-produit-module-par-module)
4. [Roadmap par phases](#roadmap-par-phases)
5. [Backlog court terme (tickets flottants)](#backlog-court-terme)
6. [Pièges à éviter](#pièges-à-éviter)
7. [Docs spécialisées](#docs-spécialisées)

---

## Vision produit

12 modules fonctionnels, organisés en couches. La progression se fait par
**phases** (voir plus bas) — pas tout en parallèle.

| #   | Module                    | Rôle                                                     |
| --- | ------------------------- | -------------------------------------------------------- |
| 1   | Core audio                | Enregistrement système, lecture, waveform, découpe       |
| 2   | File System Navigator     | Naviguer les dossiers locaux, indexation, DnD timeline   |
| 3   | Break Processing          | Détection de hits, quantize, randomisation cohérente     |
| 4   | Stem Separation           | Demucs (drums / bass / vocals / other)                   |
| 5   | Analyse musicale          | Détection de gamme, BPM, confiance                       |
| 6   | **Sample DNA**            | Chaque sample = objet (key, BPM, type, énergie, durée…)  |
| 7   | Recherche intelligente    | Par nom, key, BPM, type, énergie                         |
| 8   | Suggestions automatiques  | « Samples compatibles avec celui-ci » (rule-based)       |
| 9   | Pattern / Loop Detection  | Segments répétitifs → blocs exploitables                 |
| 10  | Resample Chain            | Pipeline créatif : slice → pitch → reverse → normalize   |
| 11  | Historique / Évolution    | Origine + transformations + versions par sample          |
| 12  | Mode Digging              | Exploration aléatoire intelligente, remise en surface    |

**Ce que SampleRod n'est pas :** un DAW multipiste, un synthé, un looper live,
un lecteur de streaming.

---

## Architecture actuelle

```
samplerod/
├── app.py                      # entry point desktop (PySide6)
├── backend/
│   ├── db.py                   # SQLAlchemy, sqlite:///sample.db
│   ├── models/
│   │   ├── sample.py           # modèle Sample (path/name/duration/created_at)
│   │   ├── SampleLibrary.py
│   │   ├── AppContext.py
│   │   ├── recorder_worker.py
│   │   ├── normalize_worker.py
│   │   ├── integrity_worker.py
│   │   └── screenshot.py
│   └── services/
│       ├── sample_service.py       # CRUD samples + cache + signaux Qt
│       ├── directory_service.py
│       ├── recorder_service.py
│       ├── remote_control_service.py   # FastAPI/WS, sert frontend/remote_ui
│       ├── screenshot_service.py
│       ├── settings_service.py
│       └── notification_service.py
├── frontend/
│   ├── main_window.py          # fenêtre principale (tabs)
│   ├── record_widget.py        # widget flottant d'enregistrement
│   ├── sample_gui/             # liste, cartes, waveform editor
│   ├── right_panel/
│   │   ├── directory/          # file browser (history, preview, DnD)
│   │   └── composer/           # timeline d'assemblage
│   ├── screenshot_gui/
│   ├── settings_gui/
│   ├── remote_ui/              # UI React pour mobile
│   ├── custom_widgets.py
│   ├── notification_widgets.py
│   └── splash.py
├── prototypes/
│   ├── drum_detector/          # analyzer + pattern_generator + UI (isolé)
│   └── scale_detector/         # librosa, détection de gamme (isolé)
├── tools/squirrel/             # toolchain release Windows
├── scripts/                    # build_release.ps1 + publish_release.ps1
├── site/                       # site marchand Django (samplerod.pascuans.dev)
├── SampleRod.spec              # PyInstaller
├── VERSION                     # version courante (ex: 0.1.3)
└── sample.db                   # base locale
```

**Trois couches qu'il faut garder séparées :**

- `backend/models/` = données + logique métier (indépendant de Qt)
- `backend/services/` = orchestration (connaît Qt pour les signaux, pas l'UI)
- `frontend/` = UI pure, consomme les services

**Un pattern précieux à conserver :** les prototypes (`drum_detector`,
`scale_detector`) sont volontairement isolés du runtime principal. Ça permet
d'itérer sur un algo bancal sans casser l'app. Le plan d'intégration tient en
une phrase : **« un proto devient un `backend/services/<nom>_service.py` une
fois son algo stable »**.

---

## État du produit, module par module

Légende : [x] opérationnel · [~] partiel · [ ] à faire

### Module 1 — Core audio [~]
- [x] Enregistrement système (`recorder_service`, `recorder_worker`)
- [x] Lecture + waveform (`sample_gui/waveform`)
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

### Module 3 — Break Processing [~, en proto]
- [x] `prototypes/drum_detector/` : détection transients, classification hits,
      générateur de breaks quantifié
- [ ] Export one-shots (kick / snare / hat par slice)
- [ ] Intégration dans l'app principale (service + UI dédiée)

### Module 4 — Stem Separation [ ]
- Rien en code pour l'instant.
- Cible : Demucs en sous-process (pas d'embedded model à la première passe).
- Contraintes : **pas de YouTube** dans SampleRod ; l'entrée est toujours un
  fichier local.

### Module 5 — Analyse musicale [~, partiel]
- [x] Détection de gamme : `prototypes/scale_detector/` (librosa)
- [ ] Détection BPM : rien
- [ ] Score de confiance exposé à l'UI
- [ ] Intégration : service unifié `analysis_service.py` qui wrappe les deux

### Module 6 — Sample DNA [ ] ← le gros chantier
Actuellement `Sample` stocke seulement :
```python
id, path, name, duration, created_at
```
Il manque les colonnes qui rendent tout le reste possible :
- `key` (string, ex: "C#m") + `key_confidence` (float)
- `bpm` (float) + `bpm_confidence` (float)
- `sample_type` (enum: drum / texture / melodic / vocal / fx / loop / one_shot)
- `energy` (enum low/mid/high ou float RMS normalisé)
- `spectral_profile` (JSON optionnel, plus tard)
- `analyzed_at` (datetime nullable) — pour savoir ce qui reste à analyser

Ça se fait via une migration Alembic (pas encore en place dans le projet —
à ajouter en même temps que ces colonnes).

### Module 7 — Recherche intelligente [ ]
Dépend du module 6. Une fois les colonnes DNA en place :
- barre de recherche existante → extension avec filtres (key / bpm / type /
  énergie)
- requête type : « samples compatibles avec {id} » = même key ± voisins (V/IV),
  BPM ±10%, type ≠ current.

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

### 🔴 Phase 1 — Solidifier (obligatoire)
*Tu es ici.*
- Stabiliser core audio (bugs de lecture loop, export propre)
- Finir le file browser côté « indexation DB »
- Nettoyer les 8 README éparpillés (fait via ce document)
- Unifier les dépendances (tu as 3 fichiers : `requirements.txt`,
  `requirement.txt`, `requirements-release.txt` — garder 2 max)

### 🟠 Phase 2 — Identité produit
- Intégrer le drum_detector comme service (`break_service.py`) + UI dédiée
- Ajouter l'export one-shots automatique
- Intégrer Demucs en sous-process pour la stem separation (queue async)

### 🟡 Phase 3 — Intelligence (Sample DNA)
- Migration SQLAlchemy/Alembic pour ajouter les colonnes DNA
- Intégrer scale_detector comme `analysis_service.py`
- Ajouter la détection BPM (librosa `beat_track` pour commencer)
- Backfill async de la DB existante

### 🟢 Phase 4 — Magie
- Recherche avancée multi-filtres
- Moteur de suggestions rule-based
- UI « samples compatibles avec celui-ci »

### 🔵 Phase 5 — Avancé
- Pattern / loop detection
- Resample chain (pipeline créatif)
- Historique / lineage
- Mode Digging

---

## Backlog court terme

Bugs et petites features à traiter en parallèle de la phase 1 :

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

**Dette tech**
- Refactor `record_widget.py` (séparer UI / logique comme les autres widgets)
- Découper les fichiers trop gros

**Déjà faits (gardé comme trace)**
- Concaténateur de samples ✓
- `Ctrl+R` pour renommer ✓
- Capture d'écran ✓
- Clic droit sur waveform = lecture à cet endroit ✓
- Refonte UI Waveform Editor ✓
- Refactor sample_card + sample_list ✓
- Arborescence `frontend/` regroupée ✓
- Refonte UI Directory Widget ✓

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
   isolés) est bon. On ne migre un proto en service qu'une fois l'algo stable.
5. **Ne pas laisser la DB dériver.** Chaque changement de modèle = migration
   Alembic versionnée. Pas de « drop sample.db et reconstruis ».

---

## Docs spécialisées

Ces README restent utiles comme références de modules. Le présent document
est le point d'entrée ; les suivants entrent dans les détails d'implémentation.

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

*Dernière mise à jour : 21 avril 2026 — version courante : voir `VERSION`.*
