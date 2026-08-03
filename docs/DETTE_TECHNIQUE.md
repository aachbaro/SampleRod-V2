# Dette technique — SampleRod

Problemes connus, constates mais non traites. Chaque entree note ce qui est
**verifie** et ce qui ne l'est pas, pour ne pas conclure au-dela des faits.

---

## DT-1 — Trois bindings Qt coexistent dans le venv

**Statut** : ouvert
**Constate le** : 3 aout 2026
**Impact mesure** : 4 erreurs sur 19 dans `tests/test_waveform_tempo_grid.py`

Le venv contient simultanement PyQt5 (5.15.11), PyQt6 (6.8.1) et PySide6
(6.10.2). L'application utilise **PySide6** partout (230 imports) ; PyQt5 et
PyQt6 ne sont utilises par aucun code applicatif.

Quand `pyqtgraph` est importe **avant** PySide6, il selectionne seul un binding
et charge ses DLL Qt. L'import PySide6 qui suit echoue alors :

```
ImportError: DLL load failed while importing QtCore:
The specified procedure could not be found.
```

Minimum reproductible, independant du code du projet :

```python
import pyqtgraph as pg
from PySide6.QtCore import Qt   # echoue
```

`frontend/sample_gui/waveform/waveform_markers.py` presente cet ordre
d'import (pyqtgraph ligne 34, PySide6 ligne 35). **Cet ordre est identique dans
l'historique commite** : le probleme preexiste au refactor GUI, il n'en est pas
une regression.

Les fichiers de test qui importent PySide6 en tete passent ; ceux qui importent
le module applicatif en premier echouent.

**Pistes non evaluees** : retirer PyQt5 et PyQt6 du venv ; fixer le binding via
`QT_API` / `pyqtgraph.setConfigOption` ; imposer l'ordre d'import.
`requirements.txt` est par ailleurs obsolete — il liste PyQt5 et PyQt6, pas
PySide6.

---

## DT-2 — `test_drum_preview` non valide

**Statut** : ouvert, cause inconnue
**Constate le** : 3 aout 2026

Le fichier `tests/test_drum_preview.py` n'a pas pu etre valide. Sur environ 74
tests, la sortie montre une erreur (`E`) parmi les points de progression.

Le fichier depasse 9 minutes d'execution et a ete interrompu avant d'avoir pu
recuperer la trace complete. **La nature et la gravite de l'erreur ne sont donc
pas connues** — ce n'est ni un echec confirme comme benin, ni un echec confirme
comme bloquant.

Ce qui est etabli :

- 32 des 35 fichiers de tests passent ;
- ce fichier est lent, vraisemblablement parce qu'il execute de l'analyse audio
  reelle ;
- aucune conclusion n'est tiree sur l'impact fonctionnel.

**Prochaine etape** : relancer le fichier seul avec un delai suffisant et
capturer la trace, avant toute interpretation.

---

## DT-3 — Renderer waveform sur fichier mono

**Statut** : ouvert, repere en passant
**Constate le** : 27 juillet 2026

Le renderer de waveform plante sur un fichier **mono** :
`waveform_data[i0:i1, idx]` avec `idx=1` sur un seul canal. Repere lors du
refactor, non corrige.
