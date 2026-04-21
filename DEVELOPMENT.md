# DEVELOPMENT — workflow de travail sur SampleRod

Projet multi-machines avec une source de vérité unique : **GitHub**.
Tout ce qui n'est pas sur `origin` n'existe pas.

## Les machines

- **PC Windows (dev)** — `C:\Users\adama\Documents\roadToDev\pascuans\samplerod`
  - lieu où tu codes, testes l'app desktop (PyQt + audio), buildes les releases
    Windows via Squirrel
  - point de départ de 95% des commits
- **Tour Linux (prod + dev SSH)** — `pascuans@192.168.1.14:~/roadToDev/pascuans/samplerod`
  - héberge le site marchand `samplerod.pascuans.dev` (Docker)
  - sert aussi à travailler en SSH quand utile (pour les parties serveur)
  - n'est PAS une « autre copie » : c'est un clone Git comme les autres
- **GitHub** — `github.com/aachbaro/SampleRod-V2`
  - source de vérité unique
  - branche principale : `main`
  - branche de dev actuelle : `feature/audio-capture-refactor`

## La règle d'or

> Toute modif = commit = push. Sans exception.

Si tu ne pushes pas, personne (et surtout pas ton autre machine) ne voit tes
changements. Pousser 3 fois par jour est normal.

## Scripts disponibles

Tout est dans `scripts/` (Windows, `.ps1`) ou à la racine du repo (tour, `.sh`).

### Côté Windows (dev)

| Script                          | Ce qu'il fait                                                |
|---------------------------------|--------------------------------------------------------------|
| `.\scripts\sync.ps1`            | `git fetch` + `pull --ff-only`. Refuse si working tree dirty.|
| `.\scripts\cp.ps1 "msg"`        | `add -A` + `commit -m` + `push`. Refuse sur `main`.          |
| `.\scripts\deploy.ps1`          | Push + SSH tour → `./deploy.sh` (pull + rebuild Docker).     |
| `.\scripts\tower-status.ps1`    | État du site sur la tour (git, containers, API, releases).   |
| `.\scripts\tower-logs.ps1`      | Logs du site (`-Follow`, `-Tunnel`, `-Since 10m`).           |
| `.\scripts\publish_release.ps1` | Build Squirrel + upload + bascule `current` via API admin.   |

### Côté tour (prod / ops)

| Script        | Ce qu'il fait                                                       |
|---------------|---------------------------------------------------------------------|
| `./status.sh` | État du site : branche git, containers, `/api/version`, releases.   |
| `./logs.sh`   | Logs du site (`-f`, `--since 10m`, `--tunnel` pour inclure CF).     |
| `./deploy.sh` | Pull + `docker compose up -d --build samplerod-site` + smoke test.  |

## Workflows

### Tu développes sur Windows

```powershell
cd C:\Users\adama\Documents\roadToDev\pascuans\samplerod
.\scripts\sync.ps1                                # pull safe
# ... tu codes, tu testes ...
.\scripts\cp.ps1 "feat(waveform): zoom horizontal au scroll"
```

### Tu déploies le site sur la tour

Depuis Windows, une commande suffit :

```powershell
.\scripts\deploy.ps1                # push + deploy sur la tour
.\scripts\deploy.ps1 -WithTunnel    # inclut le tunnel Cloudflare
```

Ou directement sur la tour en SSH :

```bash
ssh pascuans@192.168.1.14
cd ~/roadToDev/pascuans/samplerod
./deploy.sh
# ou pour inclure le tunnel Cloudflare :
./deploy.sh --with-tunnel
# ou pour déployer depuis une branche spécifique :
./deploy.sh feature/nouveau-truc
```

Le script fait `git pull` → `docker compose up -d --build samplerod-site` →
smoke test `/api/version`.

### Tu veux un état rapide du site

```powershell
.\scripts\tower-status.ps1          # snapshot : git, docker, API, releases
.\scripts\tower-logs.ps1 -Follow    # logs live
.\scripts\tower-logs.ps1 -Since 10m # logs des 10 dernières minutes
.\scripts\tower-logs.ps1 -Tunnel -Follow   # + logs cloudflared
```

### Tu bosses avec Claude (en SSH sur la tour)

Claude code sur la tour, commit + push depuis la tour. Toi, côté Windows, tu
fais `git pull` pour récupérer.

**Avant que Claude commence sur la tour :** commit + push tout ce que tu as
en cours sur Windows. Sinon ça pourrait partir en conflit.

### Tu publies une release Windows

```powershell
# sur Windows, après avoir bumpé VERSION et commité :
$env:SAMPLEROD_ADMIN_TOKEN = "<token du site .env.prod>"
.\scripts\publish_release.ps1 -Notes "changelog court"
```

Le script build un bundle Squirrel, le scp sur la tour dans
`/srv/samplerod/releases/<version>/`, puis