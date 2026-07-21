# Guide d'épuration / modernisation de l'UI

But : **uniformiser et épurer** toute l'interface de SampleRod avec le design-core
(`frontend/ui/`). Ce guide décrit le pattern appliqué au **Stem Lab** puis au
**module Waveform**, pour qu'il soit reproductible sur les autres éléments
(barre interne de l'éditeur, Break, Compositeur, Bins, Réserve, cartes…).

> Principe : **boutons icône-seule + tooltip explicite**, pas de boutons texte,
> pas de bordures boîteuses, laisser le cadre (fenêtre / onglet) faire le cadrage.

---

## 1. Les briques du design-core (`frontend/ui/`)

| Outil | Rôle |
| ----- | ---- |
| `IconButton(name, *, tooltip, size, variant)` | bouton rond icône-seule, hover fill, theme-aware. `size` = `"s"` (28/16), `"m"` (32/20), `"l"` (40/24). `variant` = `"ghost"` (défaut) / `"primary"`. |
| `themed_icon(name, size, color)` | `QIcon` recoloré par le thème (cache auto). |
| `add_tab_close_button(tabs, index, on_close)` | croix d'onglet propre (IconButton « x ») au lieu du bouton Qt par défaut. |
| `install_fast_tooltips(app)` | tooltips rapides (~250 ms) sur toute l'app. |
| `icons.py` (`_INLINE`) | registre d'icônes Tabler-style. `available_names()` liste les noms. |

Import type : `from frontend.ui import IconButton, add_tab_close_button`.

---

## 2. Recette : migrer un bouton texte → icône

**Avant**
```python
self.slice_button = QPushButton("Créer une slice")
self.slice_button.setObjectName("WaveformToolAction")   # + QSS boîteux
self.slice_button.clicked.connect(self.create_selection_artifact)
```

**Après**
```python
self.slice_button = IconButton(
    "scissors", tooltip="Créer une slice de la sélection", size="s"
)
self.slice_button.clicked.connect(self.create_selection_artifact)
```

Puis **supprimer** le QSS de l'ancien bouton (`QPushButton#...`), et retirer
l'import `QPushButton` s'il n'est plus utilisé. `IconButton` est un `QToolButton` :
`clicked`, `setEnabled`, `setCheckable/setChecked` fonctionnent tels quels.

> Le **tooltip est obligatoire** (il remplace le texte). Formuler l'action, pas
> juste le nom : « Capturer le fichier courant en artefact » plutôt que « Capturer ».

### Choisir l'icône
Prendre un nom existant dans `frontend/ui/icons.py` (`_INLINE`). Icônes déjà
disponibles (extrait) : `plus`, `minus`, `x`, `player-play`, `player-pause`,
`player-stop`, `repeat`, `scissors`, `camera`, `save`, `undo`, `redo`, `pin`,
`folder`, `wave`, `layers`, `music`, `stack`, `box`, `file`, `eye`, `eye-off`,
`pencil`, `copy`, `refresh`, `window`, `square`, `chevron-down/right`…

### Ajouter une icône manquante
Éditer `_INLINE` dans `frontend/ui/icons.py` : corps SVG **24×24**, trait
`currentColor` (le template ajoute `fill="none" stroke="currentColor"`), bouts
ronds. Les éléments pleins déclarent `fill="currentColor" stroke="none"`.
Alternative : déposer le SVG officiel Tabler dans `frontend/ui/assets/icons/<name>.svg`
(prioritaire sur l'inline). Source : https://tabler.io/icons (MIT).

---

## 3. Bordures — épurer (pas de double cadre)

- Une fenêtre de module a **déjà** son cadre (`ModuleWindow` natif, ou l'onglet
  en mode classique). Le widget racine du module ne doit **pas** ajouter sa
  propre bordure par-dessus → double cadre.
- Régler le root en `background: transparent; border: none;` (cf. `WaveformToolWidget._apply_styles`).
- Garder des bordures **subtiles** (`BORDER` / `BORDER_LIGHT`) uniquement sur les
  vraies cards/zones de drop, avec `border-radius` cohérent (8–10 px).
- Couleurs **toujours** via `theme.manager.p.*` (jamais en dur), et re-styler sur
  `theme.manager.themeChanged`.

---

## 4. Onglets — croix propre

```python
tabs.setTabsClosable(False)                     # on gère nous-mêmes
index = tabs.addTab(widget, "titre")
add_tab_close_button(tabs, index, lambda: self._close(widget))  # ferme par widget
```
Fermer **par widget** (via `tabs.indexOf(widget)`), pas par index (les index bougent).

---

## 5. Sliders — épurés

Fond transparent + groove fin (sinon Qt dessine une boîte sombre). Modèle
(`StemTile`) :
```css
QSlider#X { background: transparent; min-height: 16px; }
QSlider#X::groove:horizontal   { height: 3px; background: {BORDER}; border-radius: 1px; }
QSlider#X::sub-page:horizontal { background: {ACCENT}; border-radius: 1px; }
QSlider#X::add-page:horizontal { background: {BORDER}; border-radius: 1px; }
QSlider#X::handle:horizontal   { width: 9px; height: 9px; margin: -3px 0; border-radius: 4px; background: {TEXT}; }
```
Utiliser `frontend.custom_widgets.CustomSlider` (clic direct → `sliderMoved`).

---

## 6. Cards réutilisables

Pour des listes d'éléments audio, réutiliser une **même card** partout (ex :
`StemTile` sert aux pistes séparées, aux items du mixer, et au résultat). Une
seule classe = look uniforme + mini-lecteur (slider) partout.

---

## 7. Checklist par module

- [ ] Boutons texte → `IconButton` + tooltip explicite.
- [ ] Icônes issues du registre (ajouter au besoin, style Tabler).
- [ ] QSS des anciens boutons supprimé ; imports inutiles retirés.
- [ ] Root sans bordure (le cadre vient de la fenêtre/onglet) ; bordures subtiles ailleurs.
- [ ] Onglets fermables → `add_tab_close_button`.
- [ ] Sliders → fond transparent + groove fin.
- [ ] Couleurs via `theme.manager.p` + réaction à `themeChanged`.
- [ ] `py_compile` OK + smoke test offscreen (construction).

---

## 8. Références (déjà faits)

- `frontend/labo/stem_widgets.py` — `StemTile` (card + mini-lecteur), `StemMixerZone`.
- `frontend/labo/stem_separator_tool.py` — header icônes, onglets, drop restreint.
- `frontend/labo/waveform_tool.py` — wrapper : slice/capture en icônes, root épuré.
- `frontend/ui/` — `IconButton`, `icons.py`, `tabs.py`.
- `frontend/sample_gui/waveform/waveform_ui.py` — barre partagée waveform en
  `IconButton` Tabler, avec `HoverIconButton` conservé comme shim de compatibilité.
- `frontend/main_window.py` / `frontend/reserve/reserve_pane.py` /
  `frontend/labo/bins_panel.py` — premiers points visibles de l'Atelier
  harmonisés avec le design-core.

## 9. Candidats suivants (à faire, ex. par Codex)

- **Break generator**, **Compositeur**, **Artefacts** : finir de retirer les
  derniers `QPushButton` texte et les aligner sur `IconButton` + tooltips.
- **Réserve** : continuer le nettoyage des vues internes (`directory_detail`,
  `library_detail`) quand elles restent visibles hors mode unifié.
- **Settings / notifications / activity tray** : appliquer le même pattern sur
  les zones non encore passées au design-core.
