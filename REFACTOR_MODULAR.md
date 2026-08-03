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
├── flow_layout.py               FlowLayout / make_flow_container (flex wrap)
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
- **Bins** : la présentation est passée aux chips adaptatifs (`FlowLayout`),
  mais le module n'a pas encore de `save_state`/`restore_state` propre — il
  s'appuie toujours sur la liste globale en `QSettings`.

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

### Checkpoint — Labo / Artefacts / Indexe
- **Indexe compacté** : la liste indexée retire la colonne `RMS` pour gagner de
  la place, conserve le RMS dans le panneau de détail, et affiche désormais le
  **poids directement en Mo** dans la table.
- **Déplacements plus fluides** : le `move()` du `SampleService` bascule le
  déplacement disque+base dans un worker en arrière-plan. Les drops depuis
  `Indexe`, les bins et les autres entrées suivies ne devraient donc plus
  figer l'atelier pendant le `shutil.move()`.
- **Waveform renommable** : le nom du fichier courant dans `WaveformToolWidget`
  devient un point d’entrée de renommage par **double-clic** ; le renommage
  passe par `SampleService.rename_by_path()` pour propager le changement au reste
  de l’application quand le fichier est indexé.
- **Artefacts plus ouverts** : le plateau d’artefacts accepte maintenant les
  **drops manuels** (fichiers externes, samples de la Réserve, slices, autres
  artefacts résolus en chemin audio) pour créer rapidement des entrées dans le
  `LabArtifactStore`.
- **Artefacts renommables** : double-clic sur le nom ou action de menu
  contextuel → renommage de l’artefact ; si l’artefact pointe sur un vrai fichier,
  le chemin est renommé aussi et le store met à jour ses références.

### Bins — chips adaptatifs (27 juillet 2026)
- **Nouvelle brique design-core** : `frontend/ui/flow_layout.py` (`FlowLayout` +
  `make_flow_container`) donne l'effet `flex-wrap` du CSS — une liste s'affiche
  en colonne dans un panneau étroit et en lignes/grille dès que la fenêtre du
  module s'élargit, sans code de bascule.
- **`BinBubble` → `BinChip`** : les grosses bulles rondes (94 px, titre « BIN »
  répété + nom affiché deux fois) laissent la place à un chip 128×52 portant
  **un seul texte**, le nom du bin, élidé sur deux lignes max. Le reste
  (chemin, geste) passe en tooltip.
- **Chrome épuré** : sous-titre « Tri rapide sans afficher le contenu »
  supprimé, titre interne réduit à un label discret et **masqué dans le module**
  (`set_title_visible(False)`) puisque la barre de titre de la fenêtre le dit
  déjà. Fond du panneau transparent : plus de double cadre.
- **Panneau fluide** : plus de `setMaximumWidth` interne — c'est l'hôte qui
  borne (colonne fixe côté Labo classique, fenêtre libre côté module).
- **Gestes ajoutés** : double-clic sur un chip = ouvrir dans la Réserve ;
  déposer un **dossier** sur le panneau crée directement un bin (l'état vide
  affiche cet indice, seul texte restant quand il n'y a aucun bin).
- **Couverture** : `tests/test_labo_bins.py` vérifie le reflow colonne→lignes
  et la détection du drop de dossier.

### Générateur de break — grille compacte (27 juillet 2026)
- **Grille 6 lignes → 3** (`Anc` / `Lock` / `Hit`) : `Vel`, `Src` et `FX`
  passent en **tooltip** de la case du hit. Cellules carrées de 34 px, hauteur
  de bloc divisée par ~3.
- **Gestes** : clic gauche sur un hit = le jouer seul (déjà présent, désormais
  documenté dans le tooltip de la table) ; **clic droit** = menu avec « Voir la
  slice N dans Decoupage » — bascule d'onglet, sélection de la slice, waveform
  recadrée et jouée, ligne amenée dans le champ de vision. C'est le chemin
  rapide pour corriger une classification fausse puis regénérer.
- **Signal** : `BreakGeneratorPanel.sliceInspectRequested(int)` →
  `BreakWidget._inspect_slice_in_decoupage` → `BreakHitsTableController._inspect_slice`.
- **Ligne d'aide** réduite à l'état courant (ancres / locks / boucle) ; le mode
  d'emploi vit dans le tooltip de la table.
- **Contrôles** : `icon_qss_url()` (nouveau, dans `frontend/ui/icons.py`) rend
  les chevrons des combos et spins, invisibles depuis qu'ils étaient stylés en
  QSS ; la molette est réactivée sur ces contrôles (le panneau n'est pas dans
  un `QScrollArea`, donc pas de conflit) ; BPM et bars élargis.
- **Couverture** : `tests/test_break_generator_grid.py`.

### Break — classification manuelle persistante (27 juillet 2026)
- **Le problème** : `reanalyze_from_markers` et `analyze_file` re-classent
  *tous* les hits, puis `_apply_analysis_result(persist=True)` écrasait le
  cache. Toute correction faite à la main disparaissait au moindre
  redécoupage — d'où l'obligation de tout refaire à chaque fois.
- **Le calque** : `DrumAnalysisService` gagne un magasin de corrections séparé
  du cache d'analyse (`~/.samplerod/break_labels/<hash>.json`) —
  `load_manual_labels` / `set_manual_label` / `clear_manual_labels` /
  `apply_manual_labels`. C'est de la **donnée utilisateur**, pas un résultat
  dérivé : elle survit donc à l'invalidation du cache (mtime, version).
- **Clé = position, pas index** : les index sont renumérotés dès qu'on ajoute
  ou retire un marqueur. Le recollement se fait par proximité temporelle
  (`MANUAL_LABEL_TOLERANCE_S = 25 ms`), ce qui absorbe la dérive d'un
  redécoupage sans contaminer un hit voisin.
- **Application** : `_apply_analysis_result` repose le calque après *chaque*
  analyse, sur les slices **et** sur les `transient_hits` du prototype (c'est
  ce que lit le générateur). Le statut annonce combien de corrections ont été
  restaurées.
- **Sortie de secours** : bouton `⟲` dans la barre `Découpage`, affiché
  seulement quand des corrections existent, pour revenir à l'automatique.
- **Couverture** : `tests/test_break_manual_labels.py` (renumérotage, dérive
  de position, hit trop éloigné, double correction, reset, prototype).

### Fix — analyse de break perdue au redémarrage (27 juillet 2026)
- **Symptôme** : au relancement de l'app, plus de liste de slices ni de
  classification ; il fallait relancer une analyse.
- **Ce n'était pas le cache** : `load_cached()` renvoie bien le résultat (109
  slices vérifiées sur un fichier réel), et `open_file()` seul restaure
  correctement. Le coupable est la séquence de `BreakModule.restore_state` :
  `open_file(path)` **puis** `set_markers(markers)`. Le second appel tombe dans
  `_apply_pending_markers()`, qui faisait un `_clear_analysis()`
  inconditionnel — juste après que le loader ait restauré l'analyse.
- **Correctif** : `_markers_match_analysis()` compare les marqueurs de session
  aux débuts de slices (tolérance 1 ms). S'ils correspondent, ils sont déjà
  posés par `_apply_markers_to_waveform` : on ne touche pas à l'analyse. Sinon
  le comportement historique reste (slices invalidées, message de re-analyse).
- **Couverture** : `tests/test_break_session_restore.py`.

### Fix — empilement des fenêtres (27 juillet 2026)
- **Symptôme** : cliquer une fenêtre en faisait remonter plusieurs, et la
  Réserve repassait derrière toutes les autres.
- **Cause** : `raise_group()` parcourait `self._instances` (ordre de
  **création**) et remontait chaque fenêtre. La première instance créée — la
  Réserve — se retrouvait donc systématiquement au fond du groupe. Aucun
  traitement particulier pour la Réserve : juste l'ancienneté.
- **Correctif** : le `WindowManager` tient un `_stack_order` (bas → haut) mis à
  jour à chaque activation et à chaque affichage, et `raise_group()` remonte
  les modules dans cet ordre. Les fenêtres compagnes (Workspace) gardent leur
  place au-dessus des modules, la fenêtre active reste remontée en dernier.
- **Couverture** : `tests/test_window_stacking.py`.

### Break — source éditée + édition incrémentale des slices (27 juillet 2026)
- **Source matérialisée** : `BreakAnalysisController._resolve_working_path()`
  écrit la waveform affichée dans `%TEMP%/SampleRod/break_edits/` dès qu'elle
  diverge du fichier (comparaison frames / samplerate / canaux), en **float32**
  — le fichier alimente aussi la quantize, le rendu et le drag des slices, le
  défaut WAV 16 bits aurait dégradé la matière exportée. `_current_path` reste
  l'identité affichée et sauvegardée en session ; `_working_path` est la source
  analysée, et `_matches_path` accepte les deux.
  *Piège rencontré* : `waveform_data` est déjà en `(n_samples, channels)` — la
  transposer faisait échouer silencieusement l'écriture, donc l'analyse
  retombait sur l'original.
- **`analyzer.classify_segment()`** (nouveau, dans le prototype) : classe UN
  segment en réutilisant exactement le chemin de mesure de
  `_detect_transient_hits`, sans détection d'onsets ni estimation de tempo.
- **Trois éditions incrémentales** dans `DrumAnalysisService` :
  `merge_slice_into_previous()` (supprimer = fusionner avec la voisine de
  gauche, qui garde sa classe), `split_slice_at()` (poser un marqueur = couper
  et reclasser les deux moitiés) et `move_slice_boundary()` (déplacer un
  marqueur = recaler les deux frontières et reclasser). Toutes renumérotent les
  slices et resynchronisent `prototype_result.transient_hits`, que lit le
  générateur.
- **Signaux waveform** : `markerAdded(float)` et `markerMoved(float, float)`.
  `markerAdded` n'est émis que sur les poses **manuelles** (`_record_history`),
  pour que la projection d'une analyse ou une restauration de session ne
  déclenche pas de redécoupage en boucle.
- **Couverture** : `tests/test_break_edited_source.py` (7),
  `tests/test_break_slice_edits.py` (15).

### Générateur — BPM live sur la preview (27 juillet 2026)
- **Pourquoi pas un simple repitch** : `render_break_pattern` replace les hits
  sur la grille du tempo demandé sans les transposer. Rejouer le clip existant
  plus vite (façon platine) aurait donné un résultat **différent de l'artefact
  exporté** — l'invariant tenu ici est « la preview est toujours ce que
  *Rendre artefact* produirait au BPM courant ».
- **Mécanique** : `target_bpm_spin.valueChanged` arme un `QTimer` single-shot
  de 200 ms (pas de re-rendu par cran de molette). À son échéance,
  `_apply_live_bpm()` relance `render_break_pattern` en mode `preview` avec
  `_active_preview_request` — l'extrait qui joue réellement, donc une boucle
  sur les steps 5-8 revient sur 5-8 et pas sur le pattern entier.
- **Continuité** : `_on_preview_settings_changed` ne coupe pas la lecture
  (`stop_if_playing=False`), le clip courant tourne pendant le calcul et la
  bascule se fait à l'arrivée du nouveau rendu.
- **Coalescing** : si le service rend déjà quelque chose, la demande est
  marquée `_live_bpm_pending` et rejouée en fin de rendu
  (`_resume_pending_live_bpm`) au lieu d'empiler des workers.
- **Priorité à l'artefact** : `_render_pattern_artifact()` annule le timer et
  le pending. Effet de bord assumé : le bouton `Rendre artefact` est désactivé
  le temps d'un re-rendu de preview (`_render_busy`), donc un bref clignotement
  quand on tourne le BPM.
- **Couverture** : `tests/test_break_generator_live_bpm.py` (10).

### Waveform — drag de la sélection directement depuis le tracé (27 juillet 2026)
- **Geste** : Ctrl+double-clic (ou Ctrl+clic en mode marqueur) crée la région
  entre deux marqueurs ; si le bouton reste enfoncé et que la souris dépasse
  `QApplication.startDragDistance()`, on part en `QDrag`. Relâcher sans bouger
  désarme — le clic simple garde son comportement.
- **Une seule source de vérité pour la slice** : `MarkerManager` expose
  `selection_payload()`, utilisé à la fois par la ligne « Sélection » de la
  liste et par le drag depuis la waveform. Impossible que les deux gestes
  divergent.
- **MIME inchangé** (`application/x-sample-slice-data`, pickle) : tous les
  consommateurs existants (Bins, Break, Stems, Waveform modulaire) acceptent
  ce drag sans modification.
- **Couverture** : `tests/test_waveform_selection_drag.py` (9).

### Générateur — sélection de plage sur les numéros de step (27 juillet 2026)
- **Geste** : `PatternHeaderSelector` (filtre d'événements sur le viewport de
  l'en-tête) remplace `sectionClicked`. Press/move/release gérés à la main →
  glissement possible ; relâcher sans avoir bougé retombe sur le comportement
  d'origine (jouer depuis ce step). Le sens du glissement est normalisé.
- **Menu clic-droit sur la sélection** : jouer en boucle · verrouiller /
  déverrouiller la plage (garde le contenu au prochain `Generer`) · ancrer sur
  le type / retirer les ancres · exporter la plage en artefact. Un clic droit
  hors de la sélection recadre d'abord sur ce seul step.
- **`STEP_LABEL_TO_ANCHOR`** : le vocabulaire des ancres est plus grossier que
  celui des labels (`hat` couvre `closed_hat`/`open_hat`, `ghost` couvre les
  fantômes). Sans cette table, ancrer un `closed_hat` échouait silencieusement.
- **Export de plage** : mode de rendu `artifact_range`. Le service ne sait
  rendre que le pattern entier ; la plage est ensuite découpée avec **le même
  calcul de bornes que la preview en boucle**, donc ce qu'on a entendu est ce
  qu'on exporte. L'artefact porte `start_step`/`end_step` dans ses métadonnées.
- **Correctif de flux** : `_mark_generation_constraint_changed()` remplace
  `_mark_pattern_dirty()` sur les 4 chemins ancre/verrou. Ces gestes sont des
  contraintes pour le *prochain* Generate — ils ne touchent ni l'audio courant
  ni la signature de rendu. Les marquer « dirty » bloquait preview et export,
  donc cassait l'enchaînement « je fige la plage, puis je l'exporte ».
- **Couverture** : `tests/test_break_pattern_selection.py` (14).

### Générateur — playhead + grille non tronquée (27 juillet 2026)
- **Grille coupée** : `PATTERN_TABLE_HEIGHT` ne laissait pas la place à la
  barre de défilement horizontale, donc un pattern de 32 steps était tronqué
  net à droite sans moyen d'atteindre la fin. La hauteur réserve maintenant
  `PATTERN_HSCROLL_HEIGHT`, et le défilement passe en `ScrollPerPixel` pour
  suivre le playhead sans à-coups. Vérifié à 900 px de large : les 32 steps
  sont atteignables et les 3 lignes restent entières.
- **Playhead** : `pygame.mixer.music.get_pos()` → seconde écoulée → numéro de
  step, replié modulo la durée du clip (`get_pos()` ne repart pas de zéro à
  chaque tour de boucle). L'origine vient de `_active_preview_request`, donc
  une boucle sur les steps 9-12 illumine bien 9-12 et pas 1-4.
- **Coût maîtrisé** : timer à 40 ms, et `set_playhead_step()` ne touche que
  deux cellules — il mémorise les pinceaux d'origine de la cellule éclairée
  pour les restaurer ensuite, au lieu de rappeler
  `_refresh_pattern_visual_state()` (qui repeint les 32 colonnes).
  Ce dernier invalide le playhead mémorisé pour éviter de restaurer des
  couleurs périmées.
- **Couverture** : `tests/test_break_pattern_playhead.py` (12).

### Waveform — découpage au tempo (27 juillet 2026)
- **Deux fichiers neufs** : `waveform_grid.py` (calcul pur, testable sans Qt)
  et `waveform_grid_panel.py` (popup ancré au bouton de la barre d'outils).
- **Modèle** : un step = une double-croche, `(60 / bpm) / 4` — la même
  convention que le générateur de break, pour que les deux outils parlent le
  même langage. Deux paramètres seulement : BPM et steps par tranche, avec des
  raccourcis 1 temps / 1 mesure / 2 mesures / 4 mesures.
- **Point de départ** : le marqueur posé avant le curseur, sinon le curseur
  lui-même, sinon zéro. C'est le geste visé — poser un marqueur sur le premier
  temps puis extrapoler.
- **Non destructif** : la grille *fusionne* avec les marqueurs existants
  (tolérance 2 ms pour ne pas empiler deux marqueurs indissociables à la
  souris), et tout est poussé en **un seul bloc d'historique** — un `Ctrl+Z`
  retire la grille entière, pas un marqueur à la fois.
- **Garde-fou** : `max_markers` (4096) empêche qu'un tempo absurde sur un long
  enregistrement fige l'interface.
- **Aperçu avant pose** : le popup annonce le nombre de marqueurs et la durée
  d'une tranche, et désactive le bouton s'il n'y a rien à découper.
- **Couverture** : `tests/test_waveform_tempo_grid.py` (19).

### Fix — fuite de fichiers temporaires (27 juillet 2026)
- **Constat** : `%TEMP%/SampleRod/` contenait 381 Mo — 602 WAV dans
  `break_pattern`, 286 dans `break_pattern_segments`, 12 dans `break_preview`.
  Tous nommés par UUID, donc jamais réutilisés, et jamais supprimés. Le BPM en
  direct (un rendu par pause de molette) et l'export de plage accélèrent le
  remplissage.
- **`backend/services/temp_workspace.py`** : `temp_dir()` / `prune_temp_dir()`
  / `prune_all_workspaces()`. Politique = garder les N plus récents par
  dossier (budget par dossier) + purge au-delà de 7 jours. `protect=` met à
  l'abri le fichier en cours de lecture ; les erreurs de suppression sont
  ignorées (sous Windows un WAV encore ouvert refuse de partir, on retentera).
- **Points de branchement** : balayage au démarrage dans `app.py`, plus un
  élagage dans les trois chemins d'écriture les plus chauds
  (`_pattern_render_temp_path`, `_preview_temp_path`,
  `_extract_preview_segment`) et dans la matérialisation de waveform éditée.
- **Effet mesuré** : 830 fichiers supprimés, 381 Mo → 55 Mo.
- **Couverture** : `tests/test_temp_workspace.py` (9).

### Perf — pose de marqueurs, et grille réglable en direct (27 juillet 2026)
- **Mesure d'abord** : poser 213 marqueurs prenait **7,0 s**, en croissance
  quadratique. Trois causes cumulées, dans l'ordre d'importance :
  1. `ViewBox.updateAutoRange` → `childrenBounds` reparcourait les bornes de
     **tous** les items du plot à chaque `addItem` (4,3 s des 4,5 s au profil,
     45 000 appels à `transformAngle`). Or une `InfiniteLine` verticale n'a
     aucune étendue à cadrer → `add_plot_item_once(..., ignore_bounds=True)`.
  2. `refresh_marker_list()` **recopiait tout l'audio** en tranches float32
     (`data[s0:s1].astype`) pour chaque item, à chaque appel — des payloads que
     personne ne lit tant qu'on ne glisse pas. Les items ne portent plus que
     `s0`/`s1` ; `materialize_slice_payload()` découpe au moment du drag.
  3. La liste était reconstruite **deux fois par marqueur** (`add_marker` le
     faisait déjà, l'appelant repassait derrière) → `batch_updates()`.
- **Résultat mesuré** : 7 000 ms → **219 ms** pour 213 marqueurs.
- **Grille en direct** (`waveform_grid_session.py`) : tant que la session est
  ouverte, changer un réglage **remplace** la grille au lieu de l'empiler.
  Deux chemins selon le coût : décalage → translation des lignes existantes
  (~26 ms, tient au drag d'un slider) ; BPM/tranche → re-pose (~270 ms, à la
  validation). Les marqueurs posés à la main ne sont jamais repris.
- **`bpm_from_span()`** : déduit le tempo d'une sélection dont on affirme le
  nombre de steps (`bpm = 15 × steps / durée`). Plus fiable que de deviner à
  l'oreille ; on subdivise ensuite sans que la grille décroche.
- Au passage : `on_marker_moved` retrouvait sa ligne par un scan O(n) du
  dictionnaire à chaque pixel de drag — il lit maintenant `line.old_pos`.
- **Ancrage bilatéral** : `grid_marker_times(extend_before=True)` fait rayonner
  la grille **des deux côtés** du point de départ. Conséquence de conception :
  le décalage **ré-ancre** la grille au lieu de translater une grille de base —
  sinon un marqueur sortait par le bord sans jamais revenir. Et
  `shift_markers()` **retire** un marqueur qui sort du fichier au lieu de le
  rabattre sur la borne (`np.clip` en empilait plusieurs sur 0 et laissait des
  lignes orphelines dans le plot). Le chemin rapide ne s'applique que si le
  nombre de marqueurs est inchangé ; sinon on repose franchement.
- **Couverture** : `tests/test_waveform_grid_live.py` (40), dont trois verrous
  de performance et un fil-piège qui échoue si un refresh découpe l'audio.

### À suivre
- Polir l'UI de **Break / Compositeur / Artefacts** pour finir d'éliminer les
  derniers boutons texte et anciens patterns visuels.
- Enrichir la **lignée d'artefacts** (chaînage parent→enfant réel entre artefacts,
  pas seulement l'opération de sortie).
- **Workspaces nommés** multiples.
- Barre de titre custom / regroupement d'instances en onglets détachables (étape 7).
