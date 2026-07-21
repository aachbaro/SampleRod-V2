# Refactor GUI — Atelier modulaire

Suivi du refactor de l'interface de SampleRod vers un **atelier audio modulaire** :
chaque outil devient une fenêtre indépendante, pilotée par un contrôleur central,
avec un système d'artefacts qui circulent d'un module à l'autre.

> Branche de travail : `feature/gui-refactor`
> Approche : **incrémentale et non destructive**. L'ancienne UI (onglet « Atelier »)
> reste fonctionnelle et par défaut tant que la nouvelle n'a pas atteint la parité.

---

## 1. Vision cible

Au lieu d'une seule grande fenêtre contenant tous les outils :

- une **petite fenêtre Workspace** qui sert de centre de contrôle / barre des tâches interne ;
- plusieurs **fenêtres de modules** détachables et redimensionnables ;
- **plusieurs instances** du même module (plusieurs waveforms en parallèle, etc.) ;
- des **artefacts audio** que l'on fait glisser d'un outil à l'autre (non destructif) ;
- un **espace de travail restauré automatiquement** à chaque lancement (multi-workspaces).

Modèle conceptuel :

| Terme          | Définition                                                       |
| -------------- | ---------------------------------------------------------------- |
| **Module**     | un type d'outil (waveform, réserve, stems, break, compositeur…)  |
| **Instance**   | une fenêtre (ou plus tard un onglet) utilisant ce module         |
| **Artefact**   | un objet audio manipulable, transmis entre les outils            |
| **Workspace**  | l'ensemble des instances et de leur disposition                  |
| **WindowManager** | le contrôleur central de l'interface                          |

---

## 2. Décisions d'architecture (verrouillées)

- **Fenêtres indépendantes + WindowManager**, PAS de docking (QDockWidget).
  Chaque instance est une fenêtre top-level Qt sous une même `QApplication`,
  pilotée par un contrôleur central + une fenêtre Workspace compacte.
  → Le docking pourra éventuellement servir plus tard pour l'étape « onglets ».
- **Une instance = une fenêtre** en v1. Le regroupement en onglets par module
  est l'état final (étape 7), pas le point de départ.
- **Cadre de fenêtre natif** en v1 (déplacement/redimensionnement gratuits).
  La barre de titre custom frameless cohérente est un polish ultérieur.
- **Hide-on-close** : la croix masque la fenêtre (contenu conservé), on la
  ré-affiche depuis le Workspace.
- **Icônes Tabler** (SVG monochrome, MIT), interface en niveaux de gris,
  couleurs héritées du thème dark/light existant (`frontend/styles/theme.py`).
- **Plus de boutons texte** : boutons ronds icône-seule + tooltips rapides.

---

## 3. État actuel

### Ce qui fonctionne

- **Design-core** (`frontend/ui/`) : icônes Tabler recolorées par le thème,
  `IconButton` rond avec remplissage au hover, tooltips rapides (~250 ms).
- **Cœur modulaire** (`frontend/modular/`) : `WindowManager` complet
  (create / show / hide / rename / duplicate / close + save/restore de session
  en mémoire), fenêtres `ModuleWindow` (hide-on-close + géométrie avec clamp
  multi-écran), fenêtre **Workspace** listant les instances par catégorie.
- **Modules branchés** : **Réserve**, **Waveform**, **Stem Lab**,
  **Break**, **Compositeur**, **Bins** et **Artefacts**. `Break` et
  `Compositeur` ont maintenant leur propre conteneur modulaire à onglets
  (plusieurs fichiers / plusieurs compositions), avec session restaurée.
  Routage Waveform → Stems, Artefacts → Waveform et Bins → Réserve.
- **Réserve → Waveform** : « envoyer au labo » **ou glisser-déposer** (depuis la
  Réserve ou un fichier externe) ouvre chaque fichier dans un **onglet** du module
  Waveform (réutilise une fenêtre existante ; le module est cible de drop, même vide).
- **Fenêtres natives** : les modules utilisent de nouveau le **cadre OS natif**
  (déplacement, redimensionnement, croix native), tout en gardant le
  comportement **hide-on-close**.
- **Onglets par fichier** : le module Waveform a un onglet par fichier (bouton
  `+` pour ouvrir, onglets fermables et déplaçables).
- **Workspace** : les actions de chaque ligne n'apparaissent qu'**au survol**.
- **Deux modes au même niveau, mémorisés** : bouton icône ⧉ (haut-droite) →
  atelier modulaire ; bouton toggle du Workspace → retour au classique. Le
  **dernier mode est restauré au lancement** (QSettings `modular_ui_mode`).
  **Fermer l'orchestrateur (croix du Workspace) ferme l'application** (comme
  fermer la fenêtre classique). Les deux affichages ne sont jamais visibles
  en même temps.
- **Focus groupé** : activer une fenêtre remonte tout le groupe de fenêtres
  visibles + le Workspace au premier plan, comme si c'était une seule fenêtre
  (le modulaire sert à organiser l'espace, pas à disperser les fenêtres).
- **Session modulaire mémorisée** : le dernier mode est restauré au lancement,
  et les instances modulaires sont de nouveau sauvegardées/restaurées via
  `QSettings` (`modular_session_v1`).
- **Artefacts centralisés** : le Labo classique et l'atelier modulaire passent
  maintenant par un même `LabArtifactStore` ; un artefact produit par Waveform
  ou Stem Lab peut apparaître dans le plateau classique et dans une fenêtre
  modulaire `Artefacts`.
- **Lignée minimale d'artefact** : `LabArtifact` embarque maintenant
  `parent_ids` + `operation`, et le drag d'artefact diffuse aussi un MIME
  dédié `application/x-samplerod-artifact` pour préparer les échanges
  inter-fenêtres.
- **Stem Lab refondu** (ergonomique) : la file d'attente est remplacée par des
  **onglets** (un par fichier). Chaque onglet montre les **4 pistes séparées**
  (tuiles draggables avec **mini-lecteur** : play/pause + slider de position) et
  un **mixer** en dessous (glisser des stems → preview du mix → tuile de mix
  draggable ailleurs + envoi artefact). Le drop qui lance la séparation n'est
  accepté que dans la zone du haut ; croix d'onglet = IconButton propre.
- **Fond global optionnel** (backdrop) : un aplat plein-écran se pose derrière
  l'atelier pour masquer le bureau / les autres applis. Toggle depuis le
  Workspace (bouton □), mémorisé (QSettings), et intégré au focus groupé.

### Arborescence des nouveaux fichiers

```
frontend/ui/                     ← design-core réutilisable
├── icons.py                     registre d'icônes Tabler + themed_icon()
├── icon_button.py               IconButton (rond, hover fill, theme-aware)
├── fast_tooltip.py              install_fast_tooltips() (délai réduit)
└── assets/icons/                (optionnel) SVG Tabler officiels déposés ici

frontend/modular/                ← atelier modulaire
├── instance.py                  ModuleInstance (état sérialisable)
├── module_window.py             ModuleWindow (hide-on-close + géométrie)
├── module_registry.py           ModuleType / ModuleRegistry (catalogue)
├── window_manager.py            WindowManager (contrôleur) + ModuleContext
├── modules_setup.py             enregistrement des modules concrets
├── artifact_module.py           navigateur modulaire des artefacts
├── waveform_module.py           WaveformModule (conteneur à onglets, 1/fichier)
├── break_module.py              BreakModule (conteneur à onglets, 1/fichier)
├── composer_module.py           ComposerModule (conteneur à onglets, 1/compo)
└── workspace_window.py          WorkspaceWindow (centre de contrôle)

frontend/labo/
├── lab_artifact.py              fiche d'un artefact temporaire
├── artifact_store.py            registre partagé des artefacts du Labo
└── artifact_tray.py             vue liste / preview / save / open
```

Point de montage : `frontend/main_window.py` (`_enter_modular_mode`, bouton coin).

---

## 4. Plan par étapes et statut

Ordre issu du doc de conception ; ✅ fait · 🟡 en cours · ⬜ à faire.

| # | Étape                                                        | Statut |
| - | ----------------------------------------------------------- | ------ |
| 1 | Design-core (icônes Tabler, IconButton, tooltips, palette)  | ✅ (barre de titre custom différée) |
| 2 | WindowManager + fenêtre Workspace (create/show/hide/rename) | ✅ (+ duplicate) |
| 3 | Plusieurs Waveforms (fenêtres, état indépendant, restauration) | ✅ module + multi-instances + routage + restauration de session |
| 4 | Modèle central d'artefact (id, chemin, métadonnées, lignée) | 🟡 `LabArtifactStore` en place ; lignée / store global final encore à enrichir |
| 5 | Drag-and-drop d'artefacts (MIME `application/x-samplerod-artifact`) | ⬜ |
| 6 | Sauvegarde/restauration de session + workspaces nommés      | 🟡 mode mémorisé ✅ · session modulaire restaurée ✅ · workspaces nommés ⬜ |
| 7 | Onglets par fichier (module) ✅ · regroupement/détachement d'instances ⬜ | 🟡 |

### Modules à intégrer

| Module                         | Statut |
| ------------------------------ | ------ |
| Réserve de samples             | ✅ branché |
| Waveform / éditeur de découpe  | ✅ branché |
| Laboratoire de stems           | ✅ branché (routage Waveform→Stems) |
| Navigateur d'artefacts         | ✅ branché |
| Générateur de breaks           | ✅ branché |
| Compositeur                    | ✅ branché |
| Bins d'export                  | ✅ branché |
| Historique / graphe de transformations | ⬜ |

---

## 5. Comment essayer

1. Lancer l'application normalement (`python app.py`).
2. Cliquer le bouton icône **⧉** en **haut à droite** : bascule vers l'atelier
   modulaire (l'affichage classique se masque). La fenêtre **Workspace** s'ouvre,
   une **Réserve** apparaît en fenêtre indépendante.
3. Depuis la Réserve, « envoyer au labo » ouvre le(s) fichier(s) en fenêtre(s) Waveform.
4. Créer une slice ou capturer un fichier dans Waveform : une fenêtre
   **Artefacts** peut apparaître automatiquement pour exposer le résultat.
5. Dans le Workspace : `+` crée une instance, l'œil affiche/masque, ✎ renomme,
   ⧉ duplique, ✕ ferme. Fermer une fenêtre (croix OS) la masque sans perdre son contenu.
6. Cliquer n'importe quelle fenêtre remonte tout le groupe au premier plan.
7. Le bouton retour du Workspace (ou fermer le Workspace) revient à l'affichage classique.

---

## 6. Limites connues / différé

- **Session** : les fenêtres sont restaurées, mais il n'y a encore ni
  **workspaces nommés**, ni choix explicite entre plusieurs sessions.
- **Artefacts** : `LabArtifactStore` centralise déjà le flux courant, mais il
  n'embarque pas encore la **lignée** complète (`parent_ids`, `operation`) ni
  un historique transverse de transformations.
- **Drag-and-drop inter-fenêtres** + drag externe (vers Renoise/Tracker) : à faire.
- **Icônes** : jeu inline « style Tabler » pour démarrer. Pour les officielles,
  déposer les `.svg` dans `frontend/ui/assets/icons/` (prioritaires, même
  mécanisme `currentColor`).
- **Bins** reste le principal module encore à approfondir côté session/outillage
  modulaire ; Break et Compositeur disposent maintenant de leur coque à onglets.

---

## 7. Ajouter un module

1. Le widget de l'outil doit être un `QWidget` autonome prenant ce dont il a besoin
   depuis le contexte (`app_context`, éventuellement `directory_service`).
2. Écrire une factory `def _xxx_factory(ctx): return MonWidget(ctx.app_context)`
   dans `frontend/modular/modules_setup.py`.
3. L'enregistrer via un `ModuleType` (type_id, label, catégorie, icône, factory,
   default_title).
4. Câbler ses signaux inter-modules dans `WindowManager._connect_module_signals`
   (dispatch par `inst.module_type`).
5. (Optionnel) Pour restaurer son contenu en session, exposer `save_state() -> dict`
   et `restore_state(dict)` sur le widget (ex : Waveform mémorise son fichier).

---

## 8. Notes techniques

- **Icônes** : `themed_icon(name, size, color)` rend un SVG recoloré (cache +
  invalidation au changement de thème). 2× pour rester net en HiDPI.
- **Tooltips rapides** : `FastTooltipStyle` (QProxyStyle) abaisse
  `SH_ToolTip_WakeUpDelay`, installé une fois sur la `QApplication`.
- **Multi-écran** : `clamp_rect_to_screens` ramène une fenêtre sur un écran
  existant si sa géométrie sauvegardée tombe hors des écrans branchés.
- **Titres auto** : 1ʳᵉ instance = `default_title`, suivantes `default_title N`.
- **Fond global** : `BackdropWindow` (aplat au ton du thème, pas un vrai flou —
  le flou acrylique Windows est trop fragile). Remonté en premier par
  `raise_group` (sous les fenêtres SampleRod, au-dessus des autres applis).
- **Nettoyage à la fermeture** : un module peut exposer `cleanup()` ; le
  `WindowManager` l'appelle sur `close_instance`, et `WaveformModule` l'appelle à
  la fermeture d'un onglet — évite le crash du callback sounddevice sur un
  éditeur détruit.

---

## 9. Journal du refactor

Suivi chronologique des lots livrés (checkpoints poussés sur `feature/gui-refactor`).
À maintenir à chaque push pour garder un tracking clair (côté Claude et côté Codex).

### Checkpoint — atelier modulaire + Stem Lab ergonomique + fond global
- **Socle** : design-core (icônes Tabler, `IconButton`, tooltips rapides),
  `WindowManager`, fenêtre `Workspace`, `ModuleWindow` (cadre natif, hide-on-close,
  géométrie multi-écran).
- **Modules** : Réserve, Waveform (onglets/fichier), Stem Lab, Artefacts.
- **Routages** : Réserve→Waveform, Waveform→Stems.
- **Modes** : toggle classique/modulaire mémorisé ; croix du Workspace = quitter
  l'app (nettoyage complet des services) ; pas de flash de la fenêtre classique au
  lancement en modulaire (`MainWindow.start()`).
- **Focus groupé** : activer une fenêtre remonte tout le groupe.
- **Session** : instances + géométrie + fichier Waveform restaurés.
- **Stem Lab refondu** : onglets, zone 4 stems + mixer, drag stems/mix, mini-lecteur
  (slider de position + play/pause), croix d'onglet propres, drop restreint à la
  zone du haut, tailles d'éléments fixes (mixer stable).
- **Fond global** (backdrop) togglé depuis le Workspace, mémorisé.
- **Fix** : crash à la fermeture d'un onglet Waveform en lecture (arrêt du flux
  sounddevice via `cleanup()` avant destruction).
- **(Parallèle Codex)** : `LabArtifactStore` central + module Artefacts, flags
  `ModuleType` (workspace_creatable / renamable / duplicable / closable).

### Modernisation UI — module Waveform + guide de pattern
- **Wrapper Waveform épuré** : boutons texte « Créer une slice » / « Capturer »
  → `IconButton` (scissors / camera) + tooltips ; root sans bordure (fini le
  double cadre avec la fenêtre) ; QSS des anciens boutons supprimé.
- **Icônes ajoutées** au registre pour les prochaines barres : `scissors`,
  `camera`, `save`, `undo`, `redo`, `player-stop`, `repeat`, `pin`.
- **Guide** : [UI_MODERNIZATION.md](UI_MODERNIZATION.md) décrit le pattern
  d'épuration (boutons→icônes, bordures, onglets, sliders, cards) pour que Codex
  l'applique aux autres éléments (barre interne de l'éditeur, Break, Compositeur…).

### Retouches UI (Stem Lab + onglets)
- **Sliders épurés** : fond transparent + groove fin (plus de boîte sombre bizarre).
- **Croix d'onglet uniformes** : IconButton « x » propre partout (Waveform **et**
  Stem Lab) via le helper réutilisable `frontend/ui/tabs.py::add_tab_close_button`
  (fini les croix rouges par défaut de Qt).
- **Mixer uniformisé** : les items du mixer utilisent les **mêmes cards `StemTile`**
  (avec mini-lecteur) que les pistes séparées, au lieu de chips plats.

### Fix — drop dans le module Waveform
- Dropper une slice/fichier sur l'éditeur d'un onglet **n'écrase plus** l'onglet
  courant. Dans le module, le drop-remplace de l'éditeur est désactivé
  (`WaveformToolWidget.set_drop_replace_enabled(False)`) ; les drops remontent au
  module → **nouvel onglet** (ou focus si le fichier est déjà ouvert). Le
  comportement classique (remplacer) reste inchangé hors module.

### Checkpoint — uniformisation UI partagée + modules restants branchés
- **Waveform partagé** : la barre interne de `frontend/sample_gui/waveform/waveform_ui.py`
  utilise maintenant les icônes Tabler du design-core ; `HoverIconButton` reste
  disponible comme shim de compatibilité pour le compositeur et les sample cards.
- **Atelier visible plus cohérent** : coin haut-droit de `MainWindow`,
  boutons d'action de la `Reserve` et ajout des `Bins` passés en `IconButton`.
- **Modules restants branchés** : `Break`, `Compositeur` et `Bins` sont
  enregistrés dans `modules_setup.py` et utilisables depuis le Workspace.
- **Pont Bins → Réserve** : le `WindowManager` sait maintenant ouvrir un dossier
  dans une Réserve modulaire et rafraîchir/retirer les paths déplacés.
- **Artefacts** : `LabArtifactStore` sait attacher/résoudre le MIME
  `application/x-samplerod-artifact` et la lignée minimale (`operation`) est
  alimentée par Waveform, Break et Stem Mixer.

### Checkpoint — Break/Compositeur modulaires avec persistance
- **BreakModule** : nouveau conteneur à onglets inspiré de `WaveformModule`
  (`frontend/modular/break_module.py`). Un fichier = un onglet, dédup par
  chemin, croix custom, bouton `+`, drop audio sur le module et restauration
  des marqueurs manuels par onglet.
- **BreakWidget** : API additive minimale pour le mode modulaire
  (`current_path`, `set_markers`, `cleanup`, `set_drop_replace_enabled`) afin
  de conserver l'usage classique intact tout en laissant les drops remonter au
  module quand il est tabbé.
- **ComposerModule** : nouveau conteneur à onglets pour compositions
  indépendantes (`frontend/modular/composer_module.py`). Drop sur la barre
  d'onglets = nouvelle composition ; drop dans le contenu = comportement natif
  du `SampleComposerWidget`.
- **Session Compositeur** : persistance des clips via snapshot par onglet. Les
  clips "fichier source entier" réutilisent leur path ; les clips non
  reconstructibles directement sont matérialisés dans
  `%TEMP%/SampleRod/composer_clips` pour restaurer la composition sans perte.
- **Factories** : `frontend/modular/modules_setup.py` renvoie maintenant
  `BreakModule` et `ComposerModule` au lieu des widgets bruts, ce qui branche
  automatiquement `save_state` / `restore_state` dans le `WindowManager`.

### Réserve — sample cards compactes (en cours, Claude)
- **SampleCard 3 → 2 lignes** : ligne 1 = `[checkbox] [nom] … [gamme] [⋮]`, ligne 2 =
  `[play] [slider] [temps]`. Actions (normaliser/waveform/renommer/déplacer/archiver/
  supprimer) regroupées dans un **menu ⋮** (IconButton `dots-vertical`). Date, id,
  dossier, durée, gamme, état → **tooltip** reconstruit au survol. Objets conservés
  comme porteurs de données (aucune casse des contrôleurs). Badge **gamme** masqué par
  défaut, gouverné par le flag QSettings `reserve/show_key_badge`.
- **Toggle gamme** : bouton œil dans le chrome Réserve (`ReservePrefs` singleton +
  signal ; les cartes se re-évaluent à la volée). Fix : le label d'état « Normal »
  qui flottait par-dessus la carte → porteurs de données dans un conteneur masqué.
- **Reste** : épuration fine du chrome Réserve (déjà bien avancée par Codex) et
  refonte de la vue **Indexé** (désuète/incohérente).

### À suivre
- Polir l'UI de **Break / Compositeur / Artefacts** pour finir d'éliminer les
  derniers boutons texte et anciens patterns visuels.
- Enrichir la **lignée d'artefacts** (chaînage parent→enfant réel entre artefacts,
  pas seulement l'opération de sortie).
- **Workspaces nommés** multiples.
- Barre de titre custom / regroupement d'instances en onglets détachables (étape 7).
