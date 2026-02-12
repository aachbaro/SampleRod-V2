# Deploiement (Squirrel + PyInstaller)

Ce document decrit le flux de deploiement Windows actuellement mis en place pour SampleRod.

## Vue d'ensemble

Le build produit :
- un exe PyInstaller (pour tests rapides)
- une release Squirrel (pour installation + auto‑update)

Le flux utilise :
- `scripts/setup_squirrel.ps1` pour telecharger les outils
- `scripts/build_release.ps1` pour packager l'application
- `scripts/serve_updates.ps1` pour servir les updates en HTTP local

## Prerequis

- Python + venv active
- Node.js / npm (pour `frontend/remote_ui`)
- Acces aux commandes :
  - `python`
  - `npm`
  - `pyinstaller` (installe dans le venv)

### Installer PyInstaller

```powershell
python -m pip install pyinstaller
```

## Installation des outils Squirrel

```powershell
.\scripts\setup_squirrel.ps1 -Force
```

Cela installe dans `tools\` :
- `nuget.exe`
- `Squirrel.exe` + `Update.exe`
- `template.wxs` + outils WiX
- `7z.exe` + `7z.dll`

## Build release Squirrel

```powershell
.\scripts\build_release.ps1
```

Le script :
1. build le React `frontend/remote_ui`
2. build l'exe PyInstaller
3. pack en `.nupkg`
4. genere les releases Squirrel

Sortie :
```
C:\SampleRod\updates\
  Setup.exe
  RELEASES
  SampleRod-<version>-full.nupkg
```

## Versioning

Squirrel ne met a jour que si la version change.

**Avant chaque release :**
```powershell
Set-Content VERSION 0.1.1
.\scripts\build_release.ps1
```

## Installation (client)

L'utilisateur installe via :
```
C:\SampleRod\updates\Setup.exe
```

L'app est installee dans :
```
%LOCALAPPDATA%\SampleRod\app-<version>\
```

## Auto‑update

L'app lance `Update.exe --update <feed>` au demarrage (version packagée).

### Feed par defaut
```
file:///C:/SampleRod/updates
```

### Override
Env var :
```
SAMPLEROD_UPDATE_FEED=https://tonsite.com/updates/
```

QSettings (optionnel) :
```
update_feed = "https://tonsite.com/updates/"
```

### Desactiver l'auto‑update
```
SAMPLEROD_DISABLE_UPDATE=1
```

## Servir les updates en local (HTTP)

```powershell
.\scripts\serve_updates.ps1
```

Par defaut :
```
http://<IP_HOTE>:8000/
```

## Tester sur autre session / PC

### USB
Copier le dossier `C:\SampleRod\updates` sur la cle.
Feed :
```
file:///E:/updates
```

### Autre session Windows
Copier dans `C:\Users\Public\SampleRodUpdates` :
```powershell
robocopy "C:\SampleRod\updates" "$env:PUBLIC\SampleRodUpdates" /MIR
```

### VM
Possible via :
- partage de dossier
- serveur HTTP local

## Logs

Les logs sont ecrits dans :
```
%LOCALAPPDATA%\SampleRod\logs\app.log
```

Override possible :
```
SAMPLEROD_LOG_PATH=C:\temp\samplerod.log
```

## Debug exe rapide (sans Squirrel)

Pour tester vite un changement UI :
```powershell
pyinstaller --noconsole --onedir --name SampleRod --add-data "frontend\remote_ui\dist;frontend\remote_ui\dist" app.py
.\dist\SampleRod\SampleRod.exe
```

## Depannage (erreurs connues)

### Update.exe / template.wxs / 7z.dll manquants
Relancer :
```powershell
.\scripts\setup_squirrel.ps1 -Force
```

### Worker recorder KO en exe
L'app appelle `mp.freeze_support()` et `spawn`.  
Un statut est visible dans Audio Settings :
```
Recorder worker: OK/KO
```

### Rendu UI different entre dev / exe
Cause frequente : layout/sizeHint (pas DPI).
Tester avec l'exe PyInstaller avant de refaire un build Squirrel complet.

---

Si tu veux, on peut ajouter un script unique `release.ps1` qui bump la version + build + copie sur un share.
