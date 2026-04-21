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

## Workflows

### Tu développes sur Windows

```powershell
cd C:\Users\adama\Documents\roadToDev\pascuans\samplerod
git pull                      # toujours avant de commencer
# ... tu codes, tu testes ...
git add -A
git commit -m "feat(waveform): zoom horizontal au scroll"
git push
```

### Tu déploies le site sur la tour

Le site vit sur la branche GitHub courante. Pour déployer :

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
`/srv/samplerod/releases/<version>/`, puis appelle l'API admin du site pour
basculer `current`. Les utilisateurs verront la maj à leur prochain démarrage.

## Conventions de commits

Pas de règle stricte, mais prefix à la Conventional Commits :
- `feat(scope):` nouvelle feature
- `fix(scope):` bug fix
- `docs:` doc uniquement
- `chore:` maintenance (deps, build, CI)
- `wip:` work in progress (à rebaser plus tard)

Le scope est un sous-dossier ou un module : `waveform`, `site`, `drum_detector`…

## Branches

- `main` — toujours green, jamais de commit direct
- `feature/<nom>` — branches de dev, mergées dans main via PR
- `wip/<nom>` — expérimentations, peuvent être supprimées

## Pièges évités par ce setup

**Deux copies qui divergent.** Impossible si tu pousses après chaque modif.

**Secrets dans le repo.** `site/.env.prod` est dans `.gitignore`. Ne le
retire jamais.

**Line endings CRLF/LF.** Connu, pas géré pour l'instant. Si tu vois du bruit
dans `git status`, fais `git checkout -- <fichier>` pour les fichiers qui
n'ont que des changements de CRLF. On ajoutera un `.gitattributes` propre plus
tard si ça devient pénible.

**Perdre la connexion SSH de la tour à GitHub.** La clé SSH dédiée est dans
`~/.ssh/github_samplerod` sur la tour, configurée dans `~/.ssh/config`. Si
elle disparaît, régénère et réajoute la pubkey sur https://github.com/settings/keys.

## Apps desktop (PixelMP4 et autres)

Même principe exactement :
1. Un repo par app sur GitHub (ou monorepo `pascuans` si tu préfères un jour)
2. Tu codes sur Windows (seul endroit où tu peux tester l'UI + audio/video)
3. Tu push
4. La tour pull si nécessaire pour servir des releases via le même pattern

Le site `samplerod.pascuans.dev` est un template reproductible : tu peux faire
`pixelmp4.pascuans.dev` en copiant le dossier `site/` et en adaptant les
secrets + Stripe + tunnel.
