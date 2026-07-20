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
- **Modules branchés** : **Réserve** et **Waveform** (réutilisent les widgets
  existants tels quels).
- **Routage Réserve → Waveform** : « envoyer au labo » depuis une Réserve ouvre
  chaque fichier dans sa propre instance Waveform.
- **Lanceur** : bouton icône ⧉ en haut-droite de la fenêtre principale ouvre le
  Workspace (construction paresseuse ; l'onglet Atelier classique reste intact).

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
└── workspace_window.py          WorkspaceWindow (centre de contrôle)
```

Point de montage : `frontend/main_window.py` (`_open_modular_workspace`, bouton coin).

---

## 4. Plan par étapes et statut

Ordre issu du doc de conception ; ✅ fait · 🟡 en cours · ⬜ à faire.

| # | Étape                                                        | Statut |
| - | ----------------------------------------------------------- | ------ |
| 1 | Design-core (icônes Tabler, IconButton, tooltips, palette)  | ✅ (barre de titre custom différée) |
| 2 | WindowManager + fenêtre Workspace (create/show/hide/rename) | ✅ (+ duplicate) |
| 3 | Plusieurs Waveforms (fenêtres, état indépendant, restauration) | 🟡 module + multi-instances + routage faits ; **restauration au boot à câbler** |
| 4 | Modèle central d'artefact (id, chemin, métadonnées, lignée) | ⬜ (LabArtifact existe → à formaliser en ArtifactStore) |
| 5 | Drag-and-drop d'artefacts (MIME `application/x-samplerod-artifact`) | ⬜ |
| 6 | Sauvegarde/restauration de session + workspaces nommés      | ⬜ (save/restore en mémoire existe, pas encore persisté QSettings) |
| 7 | Onglets / regroupement d'instances (détachables)            | ⬜ |

### Modules à intégrer

| Module                         | Statut |
| ------------------------------ | ------ |
| Réserve de samples             | ✅ branché |
| Waveform / éditeur de découpe  | ✅ branché |
| Laboratoire de stems           | ⬜ |
| Générateur de breaks           | ⬜ |
| Compositeur                    | ⬜ |
| Bins d'export                  | ⬜ |
| Navigateur d'artefacts         | ⬜ |
| Historique / graphe de transformations | ⬜ |

---

## 5. Comment essayer

1. Lancer l'application normalement (`python app.py`).
2. Cliquer le bouton icône **⧉** en **haut à droite** de la fenêtre principale.
3. La fenêtre **Workspace** s'ouvre ; une **Réserve** apparaît en fenêtre indépendante.
4. Depuis la Réserve, « envoyer au labo » ouvre le(s) fichier(s) en fenêtre(s) Waveform.
5. Dans le Workspace : `+` crée une instance, l'œil affiche/masque, ✎ renomme,
   ⧉ duplique, ✕ ferme. Fermer une fenêtre (croix OS) la masque sans perdre son contenu.

---

## 6. Limites connues / différé

- **Restauration de session au démarrage** : le `WindowManager` sait
  `save_session()` / `restore_session()` (en mémoire) mais ce n'est pas encore
  persisté en QSettings ni rappelé au lancement (étape 6).
- **Barre de titre custom** frameless cohérente : non faite (cadre natif pour l'instant).
- **Artefacts** : le modèle actuel (`frontend/labo/lab_artifact.py`) n'est pas
  encore centralisé en `ArtifactStore` avec lignée (`parent_ids`, `operation`).
- **Drag-and-drop inter-fenêtres** + drag externe (vers Renoise/Tracker) : à faire.
- **Icônes** : jeu inline « style Tabler » pour démarrer. Pour les officielles,
  déposer les `.svg` dans `frontend/ui/assets/icons/` (prioritaires, même
  mécanisme `currentColor`).
- **`separationRequested`** (Waveform → Stems) et `artifactCreated` (→ plateau
  d'artefacts) : hooks prévus, câblés quand ces modules rejoindront l'atelier.

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

---

## 8. Notes techniques

- **Icônes** : `themed_icon(name, size, color)` rend un SVG recoloré (cache +
  invalidation au changement de thème). 2× pour rester net en HiDPI.
- **Tooltips rapides** : `FastTooltipStyle` (QProxyStyle) abaisse
  `SH_ToolTip_WakeUpDelay`, installé une fois sur la `QApplication`.
- **Multi-écran** : `clamp_rect_to_screens` ramène une fenêtre sur un écran
  existant si sa géométrie sauvegardée tombe hors des écrans branchés.
- **Titres auto** : 1ʳᵉ instance = `default_title`, suivantes `default_title N`.
