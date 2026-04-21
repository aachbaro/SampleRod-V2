# samplerod.pascuans.dev — site de vente & mises à jour de SampleRod

Site web qui vend SampleRod (25 € via Stripe), sert l'installeur aux clients
authentifiés et diffuse les mises à jour consommées par le mécanisme Squirrel
déjà embarqué dans l'app.

Le site est prévu pour être déployé à `https://samplerod.pascuans.dev`, hébergé
sur la tour `pascuans-MS-7B22` en cohérence avec `fragment` et `auth-server`.

---

## 1. Objectif et portée

### Ce que le site doit faire

1. **Vitrine publique** : page d'accueil qui décrit SampleRod, une capture, un
   bouton « Acheter 25 € ».
2. **Authentification** : login OIDC via `auth.pascuans.dev` (même SSO que
   fragment et extrabeam).
3. **Paiement** : Stripe Checkout (paiement unique, 25 €, TVA désactivée pour
   l'instant). Webhook Stripe → marque la licence comme « payée » pour le
   compte OIDC connecté.
4. **Téléchargement initial** : après paiement, le compte a accès à
   `Setup.exe` (bundle Squirrel de la dernière version).
5. **Flux de mises à jour** : expose un feed Squirrel
   (`RELEASES` + `.nupkg`) consommé par `Update.exe --update <feed>` déjà
   déclenché au lancement de SampleRod (`app.py` lignes 115-135). Chaque
   nouvelle publication poussée sur le serveur déclenche automatiquement une
   proposition de mise à jour dans l'app au prochain démarrage.
6. **Pilotage des releases** : un script lancé par Adam depuis sa machine de
   dev Windows pousse un build Squirrel fraîchement releasifié vers le
   serveur et le site en fait le nouveau feed actif.

### Hors scope (v1)

- Portages macOS / Linux (Squirrel est Windows-only, SampleRod ne cible que
  Windows pour l'instant).
- Licences nominatives à clés (pour l'instant : une licence = un compte OIDC,
  pas de clé alphanumérique à recopier).
- Remboursement automatique, facturation nominative, multi-devises.
- Tableau de bord « mes achats » riche (v1 : liste simple des achats et bouton
  re-télécharger).

---

## 2. Emplacement dans le dépôt

```
samplerod/
├── app.py                # déjà existant (client PyQt + hook Squirrel)
├── scripts/
│   ├── build_release.ps1 # déjà existant (PyInstaller + nuget + Squirrel)
│   ├── serve_updates.ps1 # déjà existant (petit http.server local)
│   └── publish_release.ps1  # NOUVEAU : pousse le feed vers la tour
├── site/                 # NOUVEAU — dossier du présent README
│   ├── README.md
│   ├── backend/          # projet Django
│   ├── templates/
│   ├── static/
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   ├── Dockerfile
│   ├── .env.example
│   ├── .env.prod.example
│   ├── start-prod.sh
│   └── stop-prod.sh
└── VERSION               # déjà existant, consommé par build_release.ps1
```

Le site vit dans `samplerod/site/` pour rester dans le même dépôt git que
l'app — le versionnage site/app reste cohérent et les changements de schéma
Squirrel (par ex. dossier du bundle) sont modifiables d'un seul coup.

---

## 3. Architecture d'ensemble

```
  Machine de dev Adam (Windows)
  ┌───────────────────────────────────┐
  │ build_release.ps1                 │
  │   → C:\SampleRod\updates\         │
  │       RELEASES                    │
  │       SampleRod-<v>-full.nupkg    │
  │       SampleRod-<v>-delta.nupkg   │
  │       Setup.exe                   │
  │ publish_release.ps1               │
  │   → rsync/scp vers la tour        │
  └───────────────┬───────────────────┘
                  │  ssh
                  ▼
  Tour pascuans-MS-7B22 (Ubuntu)
  ┌───────────────────────────────────────────────────┐
  │ /srv/samplerod/releases/                          │
  │   RELEASES                                        │
  │   SampleRod-*.nupkg, Setup.exe                    │
  │        ▲                                          │
  │        │ bind-mount read-only                     │
  │ ┌──────┴────────────────────┐                     │
  │ │ samplerod-site (Django)   │  port 8003          │
  │ │  - Landing, login OIDC    │ ──────────┐         │
  │ │  - Stripe Checkout        │           │         │
  │ │  - /releases/<token>/...  │           │         │
  │ │  - /download              │           │         │
  │ │  - /api/version           │           ▼         │
  │ └───────────────────────────┘   auth-server:9000  │
  │        ▲                         (auth.pascuans.dev)
  │        │                                          │
  │ cloudflared (samplerod.pascuans.dev → 127.0.0.1:8003)
  └───────────────────────────────────────────────────┘

  Client SampleRod (Windows, installé)
  ┌───────────────────────────────────┐
  │ Update.exe --update               │
  │   https://samplerod.pascuans.dev/ │
  │     releases/<token>/             │
  │ → GET RELEASES                    │
  │ → télécharge delta si dispo       │
  │ → propose la maj dans l'app       │
  └───────────────────────────────────┘
```

---

## 4. Parcours utilisateur

### 4.1 Premier achat

1. Visiteur arrive sur `samplerod.pascuans.dev`.
2. Clique sur « Acheter 25 € » → redirection `/auth/login` → OIDC
   auth.pascuans.dev → retour avec le `sub` OIDC.
3. Côté serveur, création/trouvaille d'un `SamplerodUser(sub, email)`.
4. Création d'une `CheckoutSession` Stripe (prix fixe 25 €, mode `payment`).
5. Redirect vers la page hébergée Stripe.
6. Stripe webhook `checkout.session.completed` → création
   `License(user, stripe_session_id, update_token=<random>, paid_at=now())`.
7. Stripe redirige sur `/checkout/success?session_id=...` → la page vérifie
   la licence en base et affiche :
   - bouton **Télécharger SampleRod (Setup.exe)**
   - le **feed URL personnel** à copier-coller ou à installer via un
     `.reg` fourni (voir §7).

### 4.2 Client déjà licencié

- Connexion OIDC → page `/account` → liste des achats, bouton re-télécharger,
  feed URL, bouton « régénérer le token » (révoque l'ancien).

### 4.3 Mise à jour sur le poste client

Rien à faire côté utilisateur. Au prochain lancement de SampleRod :

1. `app.py` détecte la présence de `Update.exe` (preuve qu'on est dans un
   bundle Squirrel installé).
2. Il lance `Update.exe --update <SAMPLEROD_UPDATE_FEED>`.
3. Squirrel télécharge `RELEASES`, compare les versions, récupère le delta
   et prépare la nouvelle version.
4. L'app continue à tourner en parallèle — la maj est appliquée au prochain
   redémarrage (comportement Squirrel natif).

**À ajouter dans `app.py` côté client** (hors scope du site mais listé ici
pour cohérence) : petit toast `PySide6` qui informe l'utilisateur quand
Squirrel a préparé une nouvelle version (`--check-for-update` retourne JSON
exploitable). Non-bloquant pour la v1 du site.

---

## 5. Modèle de licence et système de tokens de feed

### 5.1 Modèle de données

```python
class SamplerodUser(models.Model):
    oidc_sub = models.UUIDField(unique=True)   # sub immuable d'auth.pascuans.dev
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

class License(models.Model):
    user = models.ForeignKey(SamplerodUser, on_delete=models.CASCADE)
    stripe_session_id = models.CharField(max_length=255, unique=True)
    stripe_payment_intent = models.CharField(max_length=255, blank=True)
    amount_paid_cents = models.IntegerField()             # 2500
    currency = models.CharField(max_length=8)             # eur
    update_token = models.CharField(max_length=48, unique=True)  # secrets.token_urlsafe(32)
    paid_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)

class Release(models.Model):
    version = models.CharField(max_length=32)             # ex. "0.1.4"
    released_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
```

### 5.2 Feed Squirrel sécurisé

Squirrel.Windows ne gère pas d'en-tête d'authentification, mais il suit les
URLs arbitraires. On injecte donc le secret **dans l'URL** :

```
https://samplerod.pascuans.dev/releases/<update_token>/RELEASES
https://samplerod.pascuans.dev/releases/<update_token>/SampleRod-0.1.4-full.nupkg
```

Côté Django :

```python
# urls.py
path("releases/<str:token>/<path:filename>", views.serve_release)
```

```python
def serve_release(request, token, filename):
    lic = get_object_or_404(License, update_token=token, revoked_at__isnull=True, paid_at__isnull=False)
    safe = safe_join(RELEASES_DIR, filename)
    return FileResponse(open(safe, "rb"))
```

Si l'utilisateur révoque son token (bouton « régénérer » sur `/account`), la
requête renvoie 404 et l'app client ne trouve plus de maj. Trade-off assumé :
pas de vraie DRM, on protège contre le partage *url public* mais pas contre
un utilisateur qui redistribue son nupkg — acceptable pour un produit à 25 €.

### 5.3 Feed « latest » pour la page download

Pour que la page `/download` serve toujours le `Setup.exe` courant, on
maintient un symlink sur disque :

```
/srv/samplerod/releases/current/Setup.exe  →  /srv/samplerod/releases/0.1.4/Setup.exe
```

`publish_release.ps1` met à jour ce symlink après rsync.

---

## 6. Intégration `auth.pascuans.dev`

### 6.1 Enregistrer un nouveau client OIDC

Étendre `auth-server/oidc_provider/management/commands/create_oauth_apps.py`
pour ajouter :

```python
{
    "name": "samplerod",
    "client_id": "samplerod-web",
    "redirect_uris": settings.SAMPLEROD_REDIRECT_URIS,
},
```

Ajouter dans `auth-server/config/settings.py` :

```python
SAMPLEROD_REDIRECT_URIS = env.list(
    "SAMPLEROD_REDIRECT_URIS",
    default=[
        "http://127.0.0.1:8003/auth/callback",
        "https://samplerod.pascuans.dev/auth/callback",
    ],
)
```

Et dans `auth-server/.env.prod` :

```
SAMPLEROD_REDIRECT_URIS=http://127.0.0.1:8003/auth/callback,https://samplerod.pascuans.dev/auth/callback
POST_LOGOUT_REDIRECT_HOSTS=127.0.0.1,localhost,auth.pascuans.dev,fragment.pascuans.dev,extrabeam.pascuans.dev,samplerod.pascuans.dev
```

Puis :

```bash
docker compose -f docker-compose.prod.yml exec auth-server python manage.py create_oauth_apps
```

Récupérer le `client_secret` imprimé par la commande → le mettre dans
`site/.env.prod`.

### 6.2 Côté site

Dépendance `authlib`. Endpoints Django :

- `/auth/login` → redirige vers `https://auth.pascuans.dev/oauth/authorize`
- `/auth/callback` → échange le code, récupère `userinfo`, crée/retrouve
  `SamplerodUser`, login Django.
- `/auth/logout` → logout local + redirect vers
  `https://auth.pascuans.dev/oauth/logout`.

Le flow est **Authorization Code + PKCE**, identique à `fragment`.

---

## 7. Intégration Stripe

### 7.1 Compte et produit

- Compte Stripe d'Adam (clés à fournir dans `.env.prod`).
- Produit unique créé côté Stripe dashboard :
  - Nom : « SampleRod — licence perpétuelle »
  - Prix : 25,00 € EUR
  - Mode : one-time (`payment`)
  - Price ID à stocker dans `STRIPE_PRICE_ID`.

### 7.2 Variables d'env

```
STRIPE_PUBLIC_KEY=pk_live_xxx
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_ID=price_xxx
SITE_URL=https://samplerod.pascuans.dev
```

### 7.3 Flow technique

- `POST /checkout` → crée la `CheckoutSession`
  (`client_reference_id=user.oidc_sub`), renvoie l'URL Stripe.
- `POST /webhooks/stripe` → vérifie la signature, traite
  `checkout.session.completed` et `payment_intent.payment_failed`.
- Sur `completed` : si le `sub` référencé n'a pas déjà une `License` pour
  cette session, on la crée avec un `update_token` neuf et on marque
  `paid_at`.
- Idempotence : clé `stripe_session_id` unique.

### 7.4 Mode test

On tourne en `STRIPE_LIVE=false` en dev avec les clés `sk_test_...`. Le
`.env.example` contient des placeholders. Les clés live ne sont jamais
committées — seul `.env.prod` (non versionné, dans `.gitignore`) les porte.

---

## 8. Système de mise à jour détaillé

### 8.1 Publication d'une nouvelle version (côté Adam)

Nouveau script `samplerod/scripts/publish_release.ps1` :

```powershell
param(
  [string]$Version = $(Get-Content VERSION),
  [string]$UpdateFeed = "C:\SampleRod\updates",
  [string]$RemoteUser = "pascuans",
  [string]$RemoteHost = "192.168.1.14",   # ou pascuans.dev via tunnel ssh
  [string]$RemoteDir  = "/srv/samplerod/releases"
)

$ErrorActionPreference = "Stop"

# 1. Build Squirrel local
.\scripts\build_release.ps1 -Version $Version -UpdateFeed $UpdateFeed

# 2. rsync (via OpenSSH Windows) vers la tour, dans /srv/samplerod/releases/<version>/
$remotePath = "${RemoteUser}@${RemoteHost}:${RemoteDir}/${Version}/"
ssh ${RemoteUser}@${RemoteHost} "mkdir -p ${RemoteDir}/${Version}"
scp "${UpdateFeed}\*" $remotePath

# 3. Appelle un endpoint admin qui met à jour le symlink current/
#    et insère une entrée Release en base
$adminToken = $env:SAMPLEROD_ADMIN_TOKEN
Invoke-RestMethod -Uri "https://samplerod.pascuans.dev/api/admin/publish" `
  -Method Post `
  -Headers @{ Authorization = "Bearer $adminToken" } `
  -ContentType "application/json" `
  -Body (@{ version = $Version } | ConvertTo-Json)

Write-Host "OK -> version $Version publiée"
```

L'endpoint Django `/api/admin/publish` :

- vérifie le header `Authorization: Bearer ...` contre `SAMPLEROD_ADMIN_TOKEN`
- vérifie que `/srv/samplerod/releases/<version>/RELEASES` existe
- met à jour le symlink `current/` de façon atomique (`ln -sfn ... tmp && mv`)
- passe toutes les `Release.is_current` à `False`, crée une nouvelle
  `Release(version=..., is_current=True)`
- renvoie `200 OK`

### 8.2 Consommation côté client

`app.py` déjà cablé. Il suffit que `SAMPLEROD_UPDATE_FEED` pointe sur
`https://samplerod.pascuans.dev/releases/<update_token>/`.

Deux mécanismes pour installer le token :

1. **Manuel** (MVP) : sur `/account`, le site affiche une commande `setx` à
   coller dans un cmd Windows. Bouton « copier » à côté.
2. **Automatique** (itération suivante) : téléchargement d'un
   `install-samplerod-feed.reg` qui pose la clé `update_feed` dans
   `HKCU\Software\SampleRod\Main` — ce que lit déjà la fallback
   QSettings dans `app.py`.

### 8.3 Notification dans l'app (amélioration client)

Hors scope site, mais à prévoir : utiliser
`Update.exe --check-for-update <feed>` qui renvoie un JSON
(`{"currentVersion":"0.1.3","futureVersion":"0.1.4",...}`). Si les deux
versions diffèrent, `app.py` peut afficher un toast PyQt « Mise à jour
disponible — sera installée à la prochaine fermeture ».

---

## 9. Stack technique

| Couche | Choix |
| --- | --- |
| Backend | Django 5 + Authlib (cohérence avec auth-server et fragment) |
| Frontend | Templates Django + Tailwind via CDN (pas de SPA, le site est minimal) |
| Stripe | `stripe-python` officiel + Checkout hosted |
| DB | SQLite via volume Docker (cohérent avec `auth-server` en prod) |
| Serveur HTTP | `gunicorn` derrière `whitenoise` pour les statics |
| Reverse proxy | Cloudflare Tunnel (`cloudflared`) + hostname `samplerod.pascuans.dev` |
| Port interne | `8003` (8001 pris par auth-server, 8002 réservé extrabeam) |
| Orchestration | Docker Compose (prod + dev) |

`requirements.txt` cible :

```
Django>=5.0,<6
django-environ
Authlib>=1.3
stripe>=8
gunicorn
whitenoise
```

---

## 10. Variables d'environnement

### `site/.env.example` (dev)

```
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=change-me
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

SITE_URL=http://127.0.0.1:8003

OIDC_ISSUER=http://127.0.0.1:8001
OIDC_CLIENT_ID=samplerod-web
OIDC_CLIENT_SECRET=change-me
OIDC_REDIRECT_URI=http://127.0.0.1:8003/auth/callback
OIDC_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:8003/

STRIPE_PUBLIC_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_ID=price_xxx

RELEASES_DIR=./releases-dev
SAMPLEROD_ADMIN_TOKEN=dev-admin-token
```

### `site/.env.prod.example`

Identique, avec `DJANGO_DEBUG=0`, `SITE_URL=https://samplerod.pascuans.dev`,
`OIDC_ISSUER=https://auth.pascuans.dev`, clés Stripe `live`, et
`RELEASES_DIR=/app/releases` (volume Docker monté sur
`/srv/samplerod/releases` côté hôte).

---

## 11. Déploiement

### 11.1 Layout hôte

```
/srv/samplerod/
  releases/              # contenu Squirrel (bind-mount RO dans le conteneur)
    current -> 0.1.4/    # symlink géré par publish_release
    0.1.3/
      RELEASES
      Setup.exe
      SampleRod-0.1.3-full.nupkg
    0.1.4/
      ...
  data/                  # SQLite persistant
    samplerod-site.sqlite3
```

### 11.2 Cloudflare Tunnel

Nouvelle entrée dans la config `cloudflared` (même pattern que
`fragment` et `auth-server`) qui mappe :

```
samplerod.pascuans.dev → http://samplerod-site:8003
```

Le service `cloudflared` du compose se connecte au même tunnel Cloudflare
partagé, par token.

### 11.3 Compose prod

`docker-compose.prod.yml` :

- service `samplerod-site` : image buildée depuis `site/Dockerfile`, port
  interne 8003, volumes `/srv/samplerod/releases:ro` et
  `/srv/samplerod/data:rw`.
- service `cloudflared` : profile `tunnel`, token via env.

Scripts fournis :

- `site/start-prod.sh [--with-tunnel]`
- `site/stop-prod.sh`

Cohérents avec ce que font `fragment` et `auth-server`.

---

## 12. Check-list de mise en production

1. [ ] Créer le compte Stripe et le produit 25 €, récupérer `price_id`.
2. [ ] Créer le webhook Stripe pointant sur
       `https://samplerod.pascuans.dev/webhooks/stripe` (événements :
       `checkout.session.completed`, `payment_intent.payment_failed`).
3. [ ] Ajouter `samplerod-web` dans `auth-server` (commande
       `create_oauth_apps`) et récupérer le `client_secret`.
4. [ ] Créer l'entrée DNS + tunnel Cloudflare pour
       `samplerod.pascuans.dev`.
5. [ ] `mkdir -p /srv/samplerod/releases /srv/samplerod/data`.
6. [ ] Remplir `site/.env.prod` avec toutes les vraies valeurs.
7. [ ] Première publication : `publish_release.ps1` depuis la machine dev
       avec la version courante (0.1.3).
8. [ ] Test end-to-end : acheter avec une carte test, vérifier que la
       licence se crée, que `/download` sert le Setup, que le feed
       personnel renvoie bien `RELEASES` sur le token et 404 sur un token
       bidon.
9. [ ] Passer Stripe en mode live.

---

## 13. Décisions prises (à valider par Adam)

Ces choix sont inscrits par défaut ; dis-moi si tu veux en changer avant
que je code.

1. **Stack : Django**, pas FastAPI / Next.js — pour rester homogène avec
   `fragment` et `auth-server` et réutiliser ton écosystème Docker.
2. **Paiement : one-shot 25 €**, licence à vie avec mises à jour illimitées.
   (Alternative rejetée : abo annuel, beaucoup plus de friction pour un
   outil perso à petit prix.)
3. **DB : SQLite** dans un volume Docker. Un Postgres dédié est surdimensionné
   pour le volume attendu.
4. **Sécurisation du feed Squirrel : token dans l'URL**, régénérable par
   l'utilisateur. Pas de DRM sur les nupkg eux-mêmes.
5. **Publication : rsync depuis la machine dev** + endpoint admin pour
   basculer le symlink. Alternative rejetée : upload via S3 / CI, inutile
   pour un dev solo.
6. **Setup.exe non personnalisé**. On ne packe pas le token dans
   l'installer — il est affiché sur `/account` après login. Rend les
   builds déterministes.
7. **Windows uniquement** en v1.

---

## 14. Ce qui est attendu de toi (Adam)

Avant la mise en prod, j'aurai besoin de :

- les clés Stripe test puis live (`pk_*`, `sk_*`, `whsec_*`, `price_id`).
- le feu vert sur les décisions du §13 (ou un override).
- le token Cloudflare Tunnel pour samplerod (ou confirmation qu'on réutilise
  celui de fragment/auth-server).
- un mot de passe admin à l'initialisation Django (super-user pour
  inspecter `License` en cas de souci).

Tout le reste est codable sans toi.
