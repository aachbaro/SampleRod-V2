# Screenshot Module (Remote)

Objectif : ajouter une fonctionnalité **capture d’écran depuis le téléphone**
sans impacter la version de production (feature isolée, toggle, branche dédiée).

---

## 1) Vue d’ensemble

Le module “Screenshot” est pensé comme un **mini‑sous‑système** parallèle à Sample/Record :

- **Model** : capture, stockage, naming, metadata.
- **Service** : configuration + orchestration (path, écran, notifications).
- **Remote API** : endpoints dédiés (`/screenshots/*`) exposés par `remote_control_service`.
- **UI React** : capture + galerie + actions (rename/delete).
- **UI Desktop (Settings)** : toggle + chemin + écran par défaut.

Le tout est **désactivable** pour éviter d’alourdir la prod.

---

## 2) Arborescence proposée

```
backend/
  models/
    screenshot.py                # capture + metadata (pure logic)
  services/
    screenshot_service.py        # orchestration + settings + signals

frontend/
  settings_gui/
    screenshot_settings.py       # toggle + path + écran par défaut

frontend/remote_ui/src/
  screens/Screenshots.jsx        # écran React dédié
  api/screenshots.js             # wrappers fetch
```

---

## 3) Responsabilités par couche

### Model (`backend/models/screenshot.py`)
Responsabilités :
- récupérer la liste des écrans
- capturer un écran
- écrire sur disque (nommage `IMG_XXXX`)
- stocker metadata (json minimal)
- renommer / supprimer

API minimale suggérée :
```
list_screens() -> [{index, name, size}]
capture(screen_index) -> {id, path, meta}
list_items() -> [meta]
rename(id, new_name) -> meta
delete(id) -> bool
get_path(id) -> path
```

### Service (`backend/services/screenshot_service.py`)
Responsabilités :
- lire les settings (enabled, folder, default screen)
- valider le dossier (create si besoin)
- proxy vers le model
- envoyer notifications
- exposer signaux (si besoin côté UI)

Exemples :
```
capture(screen_index=None)
list_items()
delete(id)
rename(id, new_name)
```

---

## 4) Settings (desktop)

Dans `SettingsService` :
- `screenshot_enabled : bool`
- `screenshot_library_path : str`
- `screenshot_default_screen : int`

UI `screenshot_settings.py` :
```
[x] Activer capture d’écran
Chemin de sauvegarde: <QFileDialog>
Écran par défaut: <ComboBox>
```

---

## 5) Remote Control API

Endpoints (dans `remote_control_service.py`) :
```
GET  /screenshots/list
GET  /screenshots/screens
POST /screenshots/capture        (body: {screen_index})
POST /screenshots/rename         (body: {id, name})
POST /screenshots/delete         (body: {id})
GET  /screenshots/file/<id>      (serve l’image)
```

---

## 6) UI React (remote_ui)

Sections attendues :
- **Boutons capture** : un bouton par écran disponible
- **Galerie** : liste des captures
- **Actions** : rename / delete
- **Preview** : affichage image

Comportement :
- `capture` ajoute l’image dans la liste
- `rename/delete` agit sur le backend

---

## 7) Metadata (fichier index.json)

Structure simple (dans le dossier des screenshots) :
```
[
  {
    "id": 12,
    "filename": "IMG_0012.png",
    "created_at": "2026-02-12T18:21:00",
    "screen_index": 1,
    "width": 1920,
    "height": 1080
  }
]
```

---

## 8) Points à surveiller

- **Permissions Windows** (capture parfois bloquée par l’OS)
- **Multi‑écran** (index stable + nom)
- **Performance** (générer un thumbnail)
- **Nettoyage** (limite max si besoin)
- **Sécurité** (exposition réseau → accès restreint)

---

## 9) Intégration progressive (étapes)

1. Model + capture simple (sans API)
2. Service + settings
3. Remote endpoints
4. UI React
5. Thumbnails + actions avancées

---

Si tu veux, je peux aussi créer un **README_SCREENSHOT_API.md**
avec les schemas d’API et les exemples de payloads. 
