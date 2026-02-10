# Drag & Drop — Architecture (SampleRod)

Ce document explique en detail comment fonctionne le drag & drop dans l'application,
quels fichiers sont impliques, quels MIME types sont utilises, et comment debugguer
les problemes.

## Vue d'ensemble
Le DnD est **interne a l'app** (PyQt) et s'appuie sur `QDrag` + `QMimeData` avec
des payloads **pickled**.

Deux flux principaux :
1. **Drop d'une SampleCard** (sample entier)
2. **Drop d'une Slice** (segment extrait depuis le MarkerManager)

Il existe un 3e flux distinct : **import de fichiers externes** (drag depuis l'explorateur)
utilise par la SampleList.

---

## 1) Drag source : SampleCard (sample entier)
**Fichier** : `frontend/sample_gui/sample/sample_card_interactions.py`

**Point d'entree** :
- `SampleCardInteractions.mouse_move(...)`
- Quand la distance de drag depasse `QApplication.startDragDistance()` :
  - `SampleCardInteractions._start_drag()`

**MIME**
- `application/x-sample-card`

**Payload (pickle dict)**
```python
{"sample_id": <int>}
```

**Logs utiles**
- `[sample_card_dnd] [SampleCard] drag start`
- `[sample_card_dnd] [SampleCard] drag end (result=...)`

---

## 2) Drag source : Slice (segment audio)
Source unique : **MarkerManager** (liste de markers)
**Fichier** : `frontend/sample_gui/marker_manager.py`

**Point d'entree** :
- `MarkerListWidget.startDrag(...)`

**MIME**
- `application/x-sample-slice-data`

**Payload (pickle dict)**
```python
{
  "audio_data": np.ndarray (float32),
  "sample_rate": int,
  "name": str
}
```

**Logs**
- `[marker_manager] [MarkerManager] drag start`
- `[marker_manager] [MarkerManager] drag end`

## 3) Drop target : Directory Tool
**Fichier** : `frontend/right_panel/directory/directory_list_widget.py`

**Point d'entree** :
- `DirectoryListWidget.dragEnterEvent / dragMoveEvent / dropEvent`

**Logique de validation**
- Delegue a `frontend/right_panel/directory/directory_dnd.py`

**Traitement final**
- `backend/services/directory_service.py` (sauvegarde slice ou copie sample)

**MIME supportes**
- `application/x-sample-card`
- `application/x-sample-slice-data`

---

## 4) Drop target : Sample Composer
**Fichiers**
- `frontend/right_panel/composer/composer_widget.py`
- `frontend/right_panel/composer/composer_clip_list.py`
- `frontend/right_panel/composer/composer_dnd.py`
- `frontend/right_panel/composer/composer_model.py`

**Point d'entree**
Deux chemins :
1. Drop sur la **liste** (ClipList) -> `ComposerClipListWidget.dropEvent`
2. Drop sur le **widget complet** -> `SampleComposerWidget._handle_drag_event`

**MIME supportes**
- `application/x-sample-card`
- `application/x-sample-slice-data`

**Traitement**
- `composer_dnd.parse_slice_mime` / `parse_sample_card_mime`
- Ajout dans le `ComposerModel` (normalisation SR/canaux)

---

## 5) Drag externe (explorateur)
**Fichier** : `frontend/sample_gui/sample/sample_list_dragdrop.py`

**MIME**
- `event.mimeData().hasUrls()` (fichiers locaux)

**But**
Importer des fichiers audio externes directement dans la liste.

---

## Logs de debug utiles
- `sample_card_dnd`
- `marker_manager`
- `directory_list_widget`
- `directory_dnd`
- `sample_composer_widget`
- `sample_composer_clip_list`
- `sample_composer_dnd`

**Interpretation rapide**
- `drag start` puis `drag end (IgnoreAction)` :
  aucun drop target n'a accepte la drop.
- Aucun log de drop :
  l'event ne touche pas la zone cible (hit‑test / widget qui capte l'event).

---

## Checklist pour debugger un drop qui ne fonctionne pas
1. **Source**
   - Le `drag start` est-il logge ?
2. **Target**
   - `dragEnter` / `drop` arrivent-ils au widget cible ?
3. **MIME**
   - Le format est-il correct (sample-card ou slice) ?
4. **Conteneur**
   - Le drop cible est-il bien dans la zone survolee ?

---

## Fichiers impliques (liste rapide)
Sources:
- `frontend/sample_gui/sample/sample_card_interactions.py`
- `frontend/sample_gui/marker_manager.py`

Targets:
- `frontend/right_panel/directory/directory_list_widget.py`
- `frontend/right_panel/directory/directory_dnd.py`
- `frontend/right_panel/composer/composer_widget.py`
- `frontend/right_panel/composer/composer_clip_list.py`
- `frontend/right_panel/composer/composer_dnd.py`

Backend:
- `backend/services/directory_service.py`
- `frontend/right_panel/composer/composer_model.py`

---

## Notes de securite
Les payloads passent par `pickle`. C'est acceptable **uniquement**
parce que le drag & drop est interne a l'app.
Ne jamais accepter ces MIME depuis une source externe non fiable.
