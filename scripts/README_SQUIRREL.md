# Squirrel (dev local) — Setup rapide

Ce repo utilise Squirrel pour produire un **installer Windows** + **auto-update**.

## Prérequis
1. `nuget.exe`
2. `Squirrel.exe` (Squirrel.Windows)

Place-les ici :
- `tools\nuget\nuget.exe`
- `tools\squirrel\Squirrel.exe`

## Installation automatique
```powershell
.\scripts\setup_squirrel.ps1
```
Optionnel:
```powershell
.\scripts\setup_squirrel.ps1 -Force
```

## Build release
Depuis la racine du repo :
```powershell
.\scripts\build_release.ps1
```

Par défaut, les releases sont générées dans :
```
C:\SampleRod\updates
```

## Auto-update (dev local)
L'app cherche `Update.exe` (Squirrel) et lance :
```
Update.exe --update file:///C:/SampleRod/updates
```

Tu peux surcharger le feed avec :
```
setx SAMPLEROD_UPDATE_FEED "file:///C:/SampleRod/updates"
```

## Versioning
Le numéro de version est lu depuis le fichier :
```
VERSION
```

Change ce fichier avant de relancer un build.
