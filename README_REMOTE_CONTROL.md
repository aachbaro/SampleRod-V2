# Remote Control (App + UI)

Ce document explique la fonction de **controle distant** ajoutee a l'application :
un petit serveur HTTP local qui expose une API et sert une page React utilisable
depuis un telephone sur le meme reseau.

**Objectif**
- Lancer/arreter l'enregistrement depuis un navigateur (mobile).
- Garder l'UI principale intacte (deuxieme frontend).
- Avoir un demarrage automatique avec l'app.

**Resume rapide**
- Serveur unique (API + fichiers statiques) dans `backend/services/remote_control_service.py`
- UI React dans `frontend/remote_ui/` (build auto si `dist/` absent ou vieux)
- Toggle et statut dans l'onglet **Parametres > Controle distant**
- QR code pour ouvrir l'URL LAN directement sur le telephone

---

**Architecture**
- `AppContext` demarre le serveur HTTP au lancement et l'arrete au shutdown.
- `RemoteControlService` gere:
  - API JSON (start/stop/status/libraries)
  - fichiers statiques React (SPA)
  - build automatique si necessaire
- `RemoteControlSettingsWidget` affiche l'etat, l'URL LAN et un QR code.
- `RecorderService` emet un signal `recordingStateChanged` pour synchroniser l'UI
  (y compris le RecordWidget) quand un start/stop vient du remote.

---

**Composants principaux**
- Service HTTP: `backend/services/remote_control_service.py`
- Integrations:
  - `backend/models/AppContext.py` (start/stop)
  - `backend/services/settings_service.py` (QSettings)
  - `frontend/settings_gui/remote_control_settings.py` (UI + QR)
  - `frontend/record_widget.py` (signal de recording)
- Frontend React: `frontend/remote_ui/`

---

**Endpoints API**
- `GET /health` -> etat du service
- `GET /record/status` -> `{ is_recording, retro_enabled, pre_seconds }`
- `GET /libraries` -> `{ libraries: [ {id, path, position} ] }`
- `POST /record/start` -> body JSON:
  - `library_id` (obligatoire si pas de path)
  - `retro_time` (secondes, optionnel)
- `POST /record/stop`

---

**UI React (frontend/remote_ui)**
- Un bouton toggle Start/Stop
- Choix rapide du `retro_time`: 0s / 10s / 20s
- Affiche:
  - etat recording
  - retro selection
  - buffer max (pre_seconds du serveur)
- Le polling `GET /record/status` est fait toutes les 1s.
- La selection retro dans React est locale et ne modifie pas celle du RecordWidget.

---

**Build et service des fichiers React**
- Dossier source: `frontend/remote_ui/`
- Build output: `frontend/remote_ui/dist/`
- Le serveur tente un build si:
  - `dist/` absent
  - `src/` plus recent que `dist/`
- Le build est ignore si `npm` n'est pas dans le PATH.

---

**UI Settings (Parametres > Controle distant)**
- Toggle ON/OFF (persiste dans QSettings)
- Affiche:
  - Etat du serveur
  - Host/port d'ecoute
  - URL LAN pour le telephone
  - URL locale
  - QR code si `qrcode` + `pillow` sont installes

---

**Configuration**
Variables d'environnement optionnelles:
- `REMOTE_CONTROL_ENABLED` (default: `1`)
- `REMOTE_CONTROL_HOST` (default: `0.0.0.0`)
- `REMOTE_CONTROL_PORT` (default: `8765`)
- `REMOTE_CONTROL_CORS` (default: `*`)
- `REMOTE_CONTROL_TOKEN` (optionnel, pas utilise pour l'instant)

QSettings utilises:
- `remote_control/enabled`
- `remote_control/port`

---

**Installation / Demarrage**
1. Creer/activer le venv:
```
python -m venv venv
.\venv\Scripts\Activate.ps1
```
2. QR code (optionnel):
```
python -m pip install qrcode[pil]
```
3. Installer Node.js (si besoin), puis:
```
cd frontend/remote_ui
npm install
npm run build
cd ..\..
```
4. Lancer l'app:
```
python app.py
```

---

**Troubleshooting**
- `WinError 2` sur `npm`:
  - Node.js non installe ou non dans le PATH.
  - Solution: installer Node.js et relancer le terminal.
- Le QR est "bruite":
  - Corrige via conversion PNG en memoire (deja corrige).
  - Verifier que `qrcode` et `pillow` sont bien installes.
- Le telephone n'accede pas a l'URL:
  - Etre sur le meme Wi-Fi.
  - Autoriser le port dans le firewall.
  - Utiliser l'URL LAN affichee dans les settings.

---

**Notes importantes**
- Le buffer max (pre_seconds) limite le retro_time effectif.
- Le choix retro_time du RecordWidget et celui du remote sont independants.
- Le RecordWidget se synchronise desormais via un signal
  `recordingStateChanged` emis par `RecorderService`.

---

**Prochaines etapes possibles**
- Ajouter un champ "Port" editable dans l'UI settings.
- Ajouter un bouton "Copier URL".
- Ajouter un WebSocket pour etat temps reel (sans polling).
- Ajouter un petit ecran de pairing ou PIN si besoin de securite.
