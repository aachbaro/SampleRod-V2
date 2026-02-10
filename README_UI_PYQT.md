# UI PyQt - Guide Pratique (SampleRod)

Ce document explique comment construire et styliser l'UI PyQt dans le projet.
Il est pragmatique: structure des fichiers, conventions, QSS, bordures/rondeur,
et quelques recettes pour garder un rendu propre et coherent.

## Objectif
1. Comprendre ou se trouve l'UI et la logique.
2. Savoir modifier le style sans casser le comportement.
3. Savoir gerer les bordures, la rondeur, les hovers et les selections.

## Structure UI (pattern du projet)
On suit un pattern "UI builder" + "logique":
1. **Widget logique**: orchestre les donnees, les signaux, le comportement.
2. **UI builder**: construit les layouts, cree les widgets, applique le QSS local.
3. **Styles globaux**: quand c'est pertinent, via `frontend/styles/theme.qss`.

Exemples:
1. Waveform editor:
   - logique: `frontend/sample_gui/wave_form.py`
   - UI: `frontend/sample_gui/waveform/waveform_ui.py`
2. Sample card:
   - logique: `frontend/sample_gui/sample/sample_card.py`
   - UI: `frontend/sample_gui/sample/sample_card_ui.py`
3. Directory tool:
   - logique: `frontend/right_panel/directory/directory_widget.py`
   - UI: `frontend/right_panel/directory/directory_ui.py`

## Comment construire une UI propre
1. **ObjectName** sur les widgets clefs pour cibler le QSS.
2. **WA_StyledBackground** sur les widgets "carte" / "row".
3. Layouts simples, marges explicites, alignements clairs.

Exemple minimal:
```python
widget.setObjectName("DirectoryRow")
widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
layout = QHBoxLayout(widget)
layout.setContentsMargins(10, 6, 10, 6)
layout.setSpacing(8)
layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
```

## Styles (QSS) - ou les mettre
Deux approches:
1. **Global**: `frontend/styles/theme.qss` (coherence globale).
2. **Local**: `widget.setStyleSheet(...)` dans le builder.

Regle simple:
1. Global pour les patterns repetes (boutons, labels, champs).
2. Local pour un composant specifique (DirectoryRow, ComposerClipRow, etc).

## Bordures et rondeur (section cle)
### Bordure visible et rondeur propre
La rondeur se fait via `border-radius`. Pour une "chip", utilise un grand rayon:
```css
QWidget#ComposerClipRow {
    background: #1f1f1f;
    border: 1px solid #2a2a2a;
    border-radius: 999px; /* effet pill */
}
```

### Fond qui ne s'affiche pas
Si le fond/bordure ne s'affiche pas:
1. Le widget n'a pas `WA_StyledBackground`.
2. Un parent (QListWidget::item) peint par-dessus.

Correctif:
```python
row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
```
et dans le QSS:
```css
QListWidget#ComposerClipList::item {
    background: transparent;
    border: none;
    margin: 0;
    padding: 0;
}
```

### Bordure seulement au hover / selection
```css
QWidget#ComposerClipRow {
    border: 1px solid transparent;
    background: transparent;
}
QWidget#ComposerClipRow:hover {
    border-color: #3a3a3a;
    background-color: #232323;
}
QWidget#ComposerClipRow[selected="true"] {
    background-color: #2b2b2b;
}
```

### Selection persistante via property
1. Cote Python:
```python
row.setProperty("selected", True)
row.style().unpolish(row)
row.style().polish(row)
```
2. Cote QSS:
```css
QWidget#ComposerClipRow[selected="true"] {
    background-color: #2b2b2b;
}
```

## Alignement vertical (texte et icones)
Si texte/icone est "trop bas":
1. Alignement vertical du layout.
2. Marges verticales trop grandes.
3. `sizeHint` trop petit.

Pattern recommande:
```python
layout.setContentsMargins(10, 6, 10, 6)
layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
```

## Gestion des tooltips
Les tooltips polluent vite une UI dense:
1. Sur mobile ou liste compacte: souvent desactiver (`setToolTip("")`).
2. Sur desktop: garder un tooltip court.

## Animation simple (fade sur hover)
```python
fx = QGraphicsOpacityEffect(widget)
fx.setOpacity(0.0)
widget.setGraphicsEffect(fx)

anim = QPropertyAnimation(fx, b"opacity", widget)
anim.setDuration(140)
anim.setStartValue(0.0)
anim.setEndValue(1.0)
anim.start()
```

## Cas special: QListWidget + itemWidget
Quand on utilise `setItemWidget`:
1. `QListWidget::item` n'applique plus les styles internes.
2. Le rendu vient du widget row.
3. Tu dois forcer la taille via `item.setSizeHint(row.sizeHint())`.

## Recette "row propre" (copiable)
```python
row = QWidget(parent)
row.setObjectName("ComposerClipRow")
row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
row.setMinimumHeight(32)

layout = QHBoxLayout(row)
layout.setContentsMargins(10, 6, 10, 6)
layout.setSpacing(8)
layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

label = QLabel("Nom du clip")
label.setObjectName("ComposerClipLabel")
label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
label.setMinimumWidth(0)
```

## Liste rapide de widgets utiles
1. `QWidget` - conteneur generique
2. `QLabel` - texte / info
3. `QLineEdit` - input simple
4. `QTextEdit` - texte multi-ligne
5. `QPushButton` / `QToolButton` - actions
6. `QListWidget` - listes simples
7. `QTableWidget` - tableaux
8. `QComboBox` - select
9. `QSlider` - slider (volume, temps)
10. `QFrame` - separateur / container visuel
11. `QScrollArea` - contenu scrollable
12. `QSplitter` - panneaux redimensionnables

## Debug UI rapide
1. `print(widget.objectName())` pour verifier le scope QSS.
2. `widget.setStyleSheet("border: 1px solid red;")` pour localiser un widget.
3. Verifier `WA_StyledBackground` si fond/bordure ne s'affiche pas.

---

Si tu veux, je peux lier ce README dans `README.md` principal.
