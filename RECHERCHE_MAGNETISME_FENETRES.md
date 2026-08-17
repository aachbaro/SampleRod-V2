# Recherche — magnétisme et dispositions de fenêtres

Étude préalable, **aucun code de production modifié**. Un prototype jetable a
servi à trancher trois inconnues que la lecture seule ne permettait pas de
lever (§3).

---

## Résumé exécutif

Trois constats commandent tout le reste :

1. **Le registre central existe déjà.** `WindowManager` connaît les instances,
   leurs fenêtres, leur ordre d'empilement et sauvegarde la session. Il ne faut
   **pas** créer un gestionnaire concurrent — il faut lui adjoindre un moteur
   spatial et lui laisser l'autorité sur le cycle de vie.
2. **Aucune fenêtre n'intercepte aujourd'hui son déplacement.** Pas un seul
   `moveEvent`, `resizeEvent` ou `nativeEvent` sur une fenêtre top-level. Tout
   est à construire, mais rien n'est à défaire.
3. **Le snap continu pendant le drag natif est un piège.** J'ai vérifié
   expérimentalement que rappeler `move()` depuis `moveEvent` est ré-entrant.
   Je recommande de **snapper à la fin du déplacement** pour la V1 : c'est du
   Qt pur, sans tremblement par construction, et cela satisfait mieux la
   contrainte « la fenêtre ne doit pas donner l'impression de résister ».

---

## 1. Fichiers et classes concernés

### Les fenêtres

| Classe | Fichier | Base | Rôle |
|---|---|---|---|
| `ModuleWindow` | `frontend/modular/module_window.py` | `QMainWindow` | **Classe de base commune** des 7 modules |
| `WindowManager` | `frontend/modular/window_manager.py` | `QObject` | Registre central des instances et fenêtres |
| `ModuleInstance` | `frontend/modular/instance.py` | dataclass | État sérialisable, **porte la géométrie** |
| `WorkspaceWindow` | `frontend/modular/workspace_window.py` | `QWidget` | Palette de pilotage — **pas** un `ModuleWindow` |
| `BackdropWindow` | `frontend/modular/backdrop.py` | `QWidget` frameless | Aplat plein écran derrière l'atelier |
| `MainWindow` | `frontend/main_window.py` | `QMainWindow` | Mode classique, hors atelier |
| `RecordWidgetWindow` | `frontend/record_widget.py` | `QMainWindow` | Fenêtre d'enregistrement |

**Réponses aux questions 1 à 7**

1. **Quelles classes ?** Les 7 modules (Réserve, Waveform, Stem Lab, Break,
   Compositeur, Bins, Artefacts, + Paramètres) sont tous hébergés par la *même*
   classe `ModuleWindow` ; le widget métier est simplement son `centralWidget`.
   Workspace, Backdrop, MainWindow et RecordWidget sont à part.
2. **Classe de base commune ?** **Oui pour les modules** — `ModuleWindow`. C'est
   le point d'accroche idéal, et il n'existe qu'un seul endroit à instrumenter.
   Attention : `WorkspaceWindow` et `BackdropWindow` n'en héritent pas ; il
   faudra les traiter comme des participants « en lecture seule » (voir §7).
3. **Quel type Qt ?** `ModuleWindow` = `QMainWindow` avec cadre natif de l'OS.
   C'est important : le déplacement se fait par la **barre de titre native**,
   donc par une boucle modale Windows (voir §3).
4. **Où sont créées et conservées les instances ?**
   `WindowManager._build_window()` ([window_manager.py:382](frontend/modular/window_manager.py:382)),
   conservées dans `self._windows: dict[str, ModuleWindow]` et
   `self._instances: dict[str, ModuleInstance]`.
5. **Registre central existant ?** **Oui — `WindowManager`.** Il tient déjà les
   instances, les fenêtres, un `_stack_order` explicite pour l'empilement, une
   liste `_companions` pour les fenêtres hors-module, et un garde anti-récursion
   `_raising`. C'est l'acquis le plus précieux du projet pour cette feature.
6. **Instances multiples d'un même module ?** Gérées par `ModuleType.multi`.
   Les identifiants viennent de `_next_id()` : `f"{module_type}_{n:03d}"`
   (ex. `waveform_004`). `_bump_counter()` réaligne le compteur après une
   restauration pour éviter les collisions. **C'est propre et déjà correct.**
7. **Événements de déplacement déjà interceptés ?** **Aucun.** `ModuleWindow`
   ne définit que `closeEvent` (hide-on-close) et `changeEvent` (activation).
   Aucun `moveEvent`, `resizeEvent`, `nativeEvent` ni `QAbstractNativeEventFilter`
   nulle part sur une fenêtre top-level. Les `eventFilter` existants portent
   tous sur des widgets internes (listes, waveform), sans rapport.

---

## 2. Fonctionnement actuel de la persistance

**Réponses aux questions 8 à 13**

8. **Où ?** [main_window.py:330](frontend/main_window.py:330)
   `_persist_modular_session()` sérialise `WindowManager.save_session()` en JSON
   dans `QSettings("SampleRod", "Main")`, clé **`modular_session_v1`**.
   La persistance est **centralisée et unique** — pas de duplication par module.
9. **Schéma des données :**
   ```json
   {"instances": [{
     "instance_id": "waveform_001", "module_type": "waveform",
     "title": "Waveform", "artifact_ids": [], "visible": true,
     "geometry": {"x": 120, "y": 80, "width": 900, "height": 560},
     "state": { }
   }]}
   ```
   Les coordonnées sont stockées **manuellement** en `{x, y, width, height}`.
   `saveGeometry()`/`restoreGeometry()` de Qt **ne sont pas utilisés** — le seul
   usage de l'API Qt binaire est `splitter.saveState()` dans `labo_widget.py`,
   sans rapport. C'est un choix heureux : un dict lisible est bien plus facile à
   migrer, à inspecter et à étendre qu'un `QByteArray` opaque.
10. **Identifiants :** `_next_id()`, format `{type}_{compteur:03d}`, stable
    entre les sessions car réutilisé tel quel à la restauration.
11. **Multi-écran ?** **Partiellement.** Les coordonnées sont globales (bureau
    virtuel), donc le multi-écran fonctionne implicitement.
    `clamp_rect_to_screens()` ([module_window.py:26](frontend/modular/module_window.py:26))
    parcourt `QGuiApplication.screens()` et exige au moins 96×48 px
    d'intersection avec l'`availableGeometry()` d'un écran. **Mais** aucun
    identifiant d'écran n'est stocké, et aucune notion de facteur d'échelle.
12. **Restauration hors écran ?** Bien géré : si aucun écran ne présente
    d'intersection suffisante, la fenêtre est **recentrée sur l'écran primaire**
    avec sa taille bornée à celle de l'écran. Le cas « second moniteur
    débranché » est déjà traité.
13. **Fréquence d'écriture ?** Sur `instancesChanged`, `instanceUpdated` et
    `aboutToQuit`. **Jamais sur déplacement ou redimensionnement** — la
    géométrie n'est capturée qu'au moment de `hide_instance()`,
    `_on_window_hidden()` ou `save_session()`. Conséquence : déplacer une
    fenêtre puis quitter proprement sauvegarde bien ; **un crash perd les
    positions**. C'est le défaut à corriger en phase 1.

### Deux lacunes relevées au passage

- **`MainWindow` et `WorkspaceWindow` n'ont aucune persistance de géométrie.**
  Elles sont codées en dur : `setGeometry(300, 200, 1200, 600)`
  ([main_window.py:100](frontend/main_window.py:100)) et `resize(320, 620)`
  ([workspace_window.py:147](frontend/modular/workspace_window.py:147)).
  La palette Workspace revient donc à sa taille d'usine à chaque lancement.
- **Aucune configuration DPI** dans le projet (`AA_EnableHighDpiScaling` etc.).
  Sous Qt 6 c'est le bon défaut — le scaling par écran est automatique — mais
  cela signifie que les coordonnées persistées sont en **pixels logiques**,
  ce qui a des conséquences en multi-écran hétérogène (§7).

---

## 3. Contraintes techniques PyQt — vérifiées par prototype

Trois inconnues ne se tranchaient pas à la lecture. Prototype jetable, hors
arborescence du projet.

### A. Rappeler `move()` depuis `moveEvent` est ré-entrant — **confirmé**

```
moveEvent reçus : 2
profondeur max  : 2      (> 1 = ré-entrance réelle)
```

Un snap naïf écrit dans `moveEvent` se rappelle lui-même. Sans verrou, deux
candidats de snap proches produisent une oscillation. **Un garde
`_applying_snap` est obligatoire, pas optionnel.**

> Détail méthodologique : mon premier essai renvoyait 0 `moveEvent`. Qt n'en
> délivre pas à une fenêtre jamais affichée — il faut `show()` avant de
> mesurer. Sans cela j'aurais conclu à tort qu'il n'y a pas de récursion.

### B. Distinguer un déplacement utilisateur d'un déplacement programmé

`event.spontaneous()` vaut `False` pour un `move()` programmé et `True` pour un
déplacement venu du système de fenêtrage. Utilisable, **mais insuffisant seul** :
le drapeau ne dit rien de la *raison* du déplacement (restauration de session,
snap, changement d'écran). Il faut le combiner à un verrou explicite.

### C. L'accroche native est disponible

`QMainWindow.nativeEvent` est bien exposé par PySide6, et `ctypes` décode un
`RECT` sans difficulté. Les messages utiles sont `WM_ENTERSIZEMOVE` (0x0231),
`WM_MOVING` (0x0216) et `WM_EXITSIZEMOVE` (0x0232).

**Le point décisif :** sous Windows, glisser une fenêtre par sa barre de titre
lance une **boucle modale de l'OS**. Pendant cette boucle, l'OS conserve sa
propre position de référence. Appeler `move()` par-dessus revient à lutter
contre elle — d'où les tremblements classiques. `WM_MOVING`, lui, fournit un
`LPRECT` **modifiable avant application** : c'est la seule voie propre pour un
snap *continu*.

### D. Le coût de calcul est négligeable

```
8 fenêtres × 8 arêtes → 3,0 µs par évaluation
```

À comparer aux ~16 ms d'un rafraîchissement. **La performance n'est pas un
sujet ici** ; ce qui coûte, c'est le nombre d'appels à `move()` et les
repeints, pas l'arithmétique.

**Réponses aux questions 17 à 19**

17. **Quelle approche ?** Une combinaison, mais échelonnée :
    `moveEvent` + un `QTimer` d'inactivité suffisent pour une V1 en Qt pur.
    `nativeEvent`/`WM_MOVING` n'est nécessaire que pour un snap *continu*.
18. **Qt standard suffit-il ?** **Oui, si l'on snappe à la fin du déplacement.**
    C'est le cœur de ma recommandation. Le seul manque en Qt pur est la
    notification « le drag est terminé », qu'un timer d'inactivité (~120 ms sans
    `moveEvent`) remplace très correctement.
19. **Limitations du drag natif :** boucle modale de l'OS ; pas d'événement Qt
    « début/fin de déplacement » ; impossible de dévier le déplacement sans
    lutter contre l'OS ; le comportement Aero Snap de Windows (bords d'écran)
    reste prioritaire et peut entrer en concurrence avec notre magnétisme
    d'écran.

---

## 4. Architecture recommandée

### Principe directeur

**Le moteur de décision doit être du Python pur, sans Qt.** C'est ce qui
permet de tester exhaustivement les seuils, l'hystérésis, les conflits de
candidats et les cas limites sans jamais ouvrir de fenêtre. La couche Qt se
réduit alors à « lire des rectangles, appeler `setGeometry` ».

### Découpage proposé — nouveau paquet `frontend/modular/layout/`

```
frontend/modular/layout/
├── geometry.py        # PUR PYTHON, zéro import Qt
│                      #   Rect, snap_to_grid, edges_of, screen_edges
├── snap_engine.py     # PUR PYTHON, zéro import Qt
│                      #   SnapSettings (grille, seuil, espacement)
│                      #   resolve_snap(moving, others, screens) -> SnapResult
├── layout_manager.py  # Couche Qt : observe, décide, applique
│                      #   WorkspaceLayoutManager(QObject)
└── layout_store.py    # Phase 6 : dispositions nommées
```

**Question 14 — meilleur emplacement ?** `frontend/modular/layout/`, à côté du
`window_manager` et non dedans. `window_manager.py` fait déjà 581 lignes et
mélange cycle de vie et câblage inter-modules ; y ajouter la logique spatiale
le rendrait illisible.

**Question 15 — service existant ?** Oui, `WindowManager`. Le
`WorkspaceLayoutManager` s'y **branche** sans le remplacer : il lui demande la
liste des fenêtres et lui rend la géométrie finale à persister. Le
`WindowManager` reste l'unique autorité sur le cycle de vie et la session.

**Question 16 — la classe de base peut-elle informer le gestionnaire ?**
Oui, et c'est le bon design. Deux variantes :

- *(a)* `ModuleWindow` émet un signal `geometryChanged(str instance_id)` depuis
  son `moveEvent`/`resizeEvent` ;
- *(b)* le `LayoutManager` installe un `eventFilter` sur chaque fenêtre.

**Je recommande (a)** : le signal est explicite, se teste sans `QApplication`
avec une fausse fenêtre (l'idiome déjà employé dans
`tests/test_window_stacking.py`), et évite un filtre d'événements global qui
verrait passer tout le trafic de l'application.

### Le contrat d'enregistrement

Conforme à l'esquisse du cahier des charges, avec le `WindowManager` comme
intermédiaire plutôt qu'un appel direct depuis chaque module :

```python
layout_manager.register_window(
    window_id=inst.instance_id,
    window=win,                 # tout objet exposant geometry()/setGeometry()
    module_type=inst.module_type,
    participates=True,          # False pour Backdrop
)
```

L'enregistrement se fait dans `WindowManager._build_window()` et le
désenregistrement dans `close_instance()` — **deux points, pas huit.** Le
gestionnaire ne connaît ainsi rien de Waveform, Stem Lab ou Compositeur : il
ne manipule que des rectangles et des identifiants.

---

## 5. Stratégies possibles

| | Stratégie | Avantages | Inconvénients |
|---|---|---|---|
| **A** | **Snap à la fin du déplacement** (Qt pur + timer d'inactivité) | Aucun tremblement par construction ; portable ; la fenêtre ne « résiste » jamais ; simple à tester | Le calage n'est pas visible pendant le geste |
| **B** | Snap continu via `moveEvent` + `move()` | Retour immédiat | **Lutte contre la boucle modale de l'OS** ; ré-entrance confirmée ; tremblements attendus |
| **C** | Snap continu via `nativeEvent` / `WM_MOVING` | Le plus fluide visuellement ; l'OS applique directement le rectangle corrigé | Win32 uniquement ; `ctypes` ; dépendance à l'API native ; plus difficile à tester |
| **D** | Pas de magnétisme, seulement une commande « Ranger » | Trivial | Ne répond pas au besoin |

**Question 20-21 — quantité de calcul ?** 3 µs par évaluation mesurée. On ne
recalcule que la fenêtre déplacée contre les autres (jamais toutes contre
toutes), avec un cache des rectangles invalidé sur move/resize/show/hide.

**Question 22 — risque de récursion ?** **Oui, confirmé expérimentalement**
(profondeur 2). Garde obligatoire.

**Question 23 — utilisateur vs programmatique ?** `event.spontaneous()` **plus**
un verrou explicite `_applying` posé autour de tout `setGeometry` d'origine
interne, et un second verrou pendant `restore_session()`.

**Question 24 — éviter les oscillations ?** Trois règles cumulatives :
- **un seul candidat retenu par axe** (le plus proche), jamais deux ;
- **hystérésis** : une fois snappée, la fenêtre ne se détache qu'au-delà d'un
  seuil de rupture supérieur au seuil d'accroche (par ex. accroche 12 px,
  rupture 20 px) ;
- **on ne déplace jamais les autres fenêtres** (option A du cahier des charges),
  ce qui supprime par construction les attractions circulaires.

**Question 25 — DPI et écrans hétérogènes ?** Qt 6 gère le scaling par écran
automatiquement et les coordonnées Qt sont en pixels **logiques**. Le vrai piège
est la persistance : un rectangle sauvé sur un écran à 150 % puis restauré sur
un écran à 100 % change de taille apparente. Recommandation : stocker en plus
`screen_name` et la géométrie **relative à l'écran**, et privilégier la
restauration relative quand l'écran nommé est retrouvé. `clamp_rect_to_screens`
reste le filet de sécurité.

---

## 6. Stratégie recommandée

> **Stratégie A pour la V1**, avec une architecture prête pour C.

Raisons, par ordre d'importance :

1. **Elle satisfait la contrainte UX centrale.** Le cahier des charges demande
   que la fenêtre « ne donne pas l'impression de résister constamment ». Un snap
   qui ne s'applique qu'au relâchement ne peut, par construction, jamais donner
   cette impression.
2. **Elle évite le seul vrai risque technique identifié** — la lutte contre la
   boucle modale de l'OS.
3. **Elle est testable sans GUI**, donc vérifiable en profondeur.
4. **Elle n'interdit rien.** Le moteur `resolve_snap()` étant pur, passer plus
   tard au snap continu ne change *que* la couche d'accroche : on remplace le
   timer par `WM_MOVING` et on appelle le même moteur.

Détection de fin de déplacement en Qt pur : un `QTimer` mono-coup relancé à
chaque `moveEvent`, qui déclenche le snap après ~120 ms sans mouvement. C'est
portable, sans `ctypes`, et se substitue très correctement à `WM_EXITSIZEMOVE`.

---

## 7. Risques et cas limites

| Risque | Traitement |
|---|---|
| **Boucle restauration → snap** | Verrou `_suspended` pendant `restore_session()` et `apply_geometry()`. Une position restaurée ne doit **jamais** déclencher de magnétisme. |
| **Ré-entrance `move()` dans `moveEvent`** | Garde `_applying_snap` (risque confirmé par prototype). |
| **Sauvegarde à chaque pixel** | Debounce : persister au plus une fois par ~500 ms, et seulement après snap appliqué — jamais la position intermédiaire. |
| **Oscillation entre deux candidats** | Un candidat par axe + hystérésis (accroche 12 px / rupture 20 px). |
| **Attraction circulaire** | Aucune fenêtre autre que celle déplacée n'est bougée (option A). |
| **Fenêtre maximisée ou minimisée** | Ne jamais snapper si `isMaximized()`, `isMinimized()` ou `isFullScreen()`. |
| **Écran débranché** | Déjà couvert par `clamp_rect_to_screens()`. |
| **DPI hétérogène** | Stocker `screen_name` + géométrie relative ; se replier sur l'absolu. |
| **Aero Snap de Windows** | Le magnétisme d'écran entre en concurrence avec le snap natif des bords. À tester ; prévoir de désactiver notre snap d'écran si le conflit gêne. |
| **`WorkspaceWindow` / `BackdropWindow`** | Ne sont pas des `ModuleWindow`. Le Backdrop doit être **exclu** (il couvre tout l'écran, il attirerait tout). Le Workspace devrait **participer** — ce qui suppose de lui donner d'abord une géométrie persistée (voir phase 1). |
| **Placement volontairement décalé impossible** | Modificateur d'annulation (§ ci-dessous). |

### Modificateur d'annulation

`Alt` est **déconseillé sous Windows** : `Alt+glisser` et `Alt+Espace` sont
réservés par l'OS, et `Alt` seul active la barre de menus. `Ctrl` est plus sûr
et n'entre en conflit avec aucun raccourci actuel du projet (les raccourcis
existants relevés sont `F11` plein écran et les raccourcis internes de la
waveform, tous sur widgets enfants). **Recommandation : `Ctrl` maintenu pendant
le déplacement désactive le magnétisme**, avec l'option d'un réglage.

---

## 8. Plan d'implémentation progressif

### Phase 1 — Centralisation *(aucun changement visible)*
- Créer `frontend/modular/layout/` avec `geometry.py` et `snap_engine.py`
  (purs, testés, mais encore appelés par personne).
- Ajouter `WorkspaceLayoutManager`, enregistré/désenregistré depuis
  `WindowManager._build_window()` / `close_instance()`.
- Ajouter les signaux `geometryChanged` à `ModuleWindow` (émis, non exploités).
- **Corriger la lacune relevée** : persister la géométrie de `WorkspaceWindow`
  (et éventuellement `MainWindow`), aujourd'hui codées en dur.
- Persister la géométrie **au déplacement** (avec debounce), pas seulement à la
  fermeture — corrige la perte de positions en cas de crash.

### Phase 2 — Snap simple au déplacement
- Fin de drag détectée par timer d'inactivité.
- Magnétisme fenêtre↔fenêtre (les 8 relations d'arêtes demandées) et
  fenêtre↔bords d'écran, sur `availableGeometry()`.
- Seuil fixe (12 px), pas encore de réglages, pas de guides, pas de groupes.

### Phase 3 — Grille et paramètres
- Grille (8/10/12/16 px), espacement global (0/6/8/10 px), seuil réglable,
  activation/désactivation, modificateur `Ctrl`.
- Réglages exposés dans `frontend/settings_gui/` (le module Paramètres existe
  déjà dans le catalogue).

### Phase 4 — Redimensionnement
- Étendre le même moteur aux arêtes redimensionnées via `resizeEvent`.
- **Le cahier des charges a raison de prévoir deux phases** : le
  redimensionnement natif est plus délicat car l'arête tirée doit être connue,
  information que Qt ne fournit pas directement. Il faut la déduire en comparant
  l'ancien et le nouveau rectangle.

### Phase 5 — Finition visuelle
- Guides d'alignement. Recommandation : **une fenêtre overlay unique par écran**,
  `FramelessWindowHint | WA_TransparentForMouseEvents | WA_TranslucentBackground`,
  créée une fois et masquée, jamais recréée pendant le geste (sinon
  scintillement). Le `BackdropWindow` existant fournit déjà le modèle.
- Éventuellement, passage au snap continu via `WM_MOVING` si le ressenti le
  justifie — le moteur ne change pas.

### Phase 6 — Dispositions nommées
- `layout_store.py`, distinct de la session automatique.
- **Séparation stricte** : `modular_session_v1` (automatique) et
  `modular_layouts_v1` (volontaire) sont deux clés QSettings différentes.
  L'auto-sauvegarde ne doit jamais écrire dans une disposition nommée.
- Une disposition contient : modules ouverts, instances et leurs ids,
  géométries, écran, état min/max, ordre d'empilement (`_stack_order` existe
  déjà et est directement réutilisable).

---

## 9. Fichiers qui seraient modifiés

**Créés**
- `frontend/modular/layout/__init__.py`
- `frontend/modular/layout/geometry.py` *(pur)*
- `frontend/modular/layout/snap_engine.py` *(pur)*
- `frontend/modular/layout/layout_manager.py`
- `frontend/modular/layout/layout_store.py` *(phase 6)*

**Modifiés**
- `frontend/modular/module_window.py` — signaux `geometryChanged`, `moveEvent`,
  `resizeEvent`, garde de ré-entrance *(phases 1, 2, 4)*
- `frontend/modular/window_manager.py` — enregistrement/désenregistrement,
  verrou pendant `restore_session()` *(phase 1)*
- `frontend/modular/workspace_window.py` — géométrie persistée, participation
  au magnétisme *(phase 1)*
- `frontend/main_window.py` — persistance debouncée de la géométrie *(phase 1)*
- `frontend/modular/instance.py` — champs `screen_name`, état min/max *(phases 1, 6)*
- `frontend/settings_gui/display_settings.py` — réglages du magnétisme *(phase 3)*
- `README.md`, `REFACTOR_MODULAR.md` — documentation

**Non modifiés** — aucun module métier (Waveform, Stem Lab, Compositeur,
Break, Bins, Artefacts). C'est le test de validité de l'architecture : si un
module métier doit changer, le découpage est mauvais.

---

## 10. Proposition de tests

L'essentiel du moteur étant du Python pur, il se teste sans `QApplication`.

**`tests/test_snap_geometry.py`** *(pur, rapide)*
- arrondi sur grille : 8/10/12/16 px, valeurs négatives, exactement à mi-chemin
- les 8 relations d'arêtes demandées, une par test
- l'espacement global s'applique bien (0 / 6 / 8 / 10 px)
- au-delà du seuil, aucun candidat n'est proposé
- deux candidats concurrents : **le plus proche gagne, un seul par axe**
- hystérésis : une fenêtre snappée ne se détache qu'au-delà du seuil de rupture
- bords d'écran à partir d'`availableGeometry` simulée
- un rectangle dégénéré (largeur nulle) ne produit rien

**`tests/test_snap_engine.py`** *(pur)*
- magnétisme désactivé → identité stricte
- fenêtre maximisée/minimisée → jamais de snap
- 8 fenêtres, aucune proche → aucun mouvement
- **non-régression de performance** : 1 000 résolutions sous un seuil large

**`tests/test_layout_manager.py`** *(fausses fenêtres, idiome de
`test_window_stacking.py`)*
- enregistrement/désenregistrement au cycle de vie de l'instance
- **la restauration de session ne déclenche aucun snap** (le risque de boucle)
- **`setGeometry` programmatique ne se re-déclenche pas** (ré-entrance)
- la persistance n'enregistre que la géométrie **après** snap, jamais avant
- debounce : N déplacements rapides → une seule écriture

**`tests/test_layout_store.py`** *(phase 6)*
- l'auto-sauvegarde n'écrase pas une disposition nommée
- aller-retour enregistrer/charger
- disposition référençant un module inconnu → ignorée sans exception

---

## Ce que je recommande de décider avant de coder

1. **`Ctrl` plutôt qu'`Alt`** pour l'annulation temporaire — `Alt` est réservé
   par Windows.
2. **Grille par défaut : 8 px.** Assez fin pour ne jamais se sentir, assez
   grossier pour absorber les décalages d'un pixel ou deux.
3. **Snap à la fin du geste, pas en continu**, pour la V1.
4. **Le Workspace participe, le Backdrop non.**
5. Traiter en phase 1 la persistance manquante de `WorkspaceWindow` : c'est un
   défaut réel, indépendant du magnétisme, et le corriger d'abord évite de bâtir
   sur du sable.
