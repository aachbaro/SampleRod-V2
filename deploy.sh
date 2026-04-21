#!/usr/bin/env bash
#
# deploy.sh — pull + rebuild + restart du site marchand sur la tour.
#
# Usage :
#   ./deploy.sh              # pull main + rebuild samplerod-site
#   ./deploy.sh feature/x    # pull d'une branche spécifique
#   ./deploy.sh --with-tunnel  # inclut le service cloudflared (profile tunnel)
#
# Hypothèses :
# - on est dans le repo samplerod (à la racine ou depuis n'importe quel sous-dossier)
# - .env.prod est présent dans site/ (JAMAIS commité)
# - le Docker daemon tourne
#
set -euo pipefail

# --- résolution de la racine du repo ---
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  echo "✗ pas dans un repo git, aborted" >&2
  exit 1
fi
cd "${REPO_ROOT}"

# --- args ---
BRANCH=""
WITH_TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --with-tunnel) WITH_TUNNEL=1 ;;
    -*) echo "option inconnue: $arg" >&2; exit 2 ;;
    *)  BRANCH="$arg" ;;
  esac
done

# --- pull ---
echo "== 1/3 : git pull =="
CUR="$(git branch --show-current)"
TARGET="${BRANCH:-$CUR}"
if [ "$TARGET" != "$CUR" ]; then
  echo "   switch $CUR -> $TARGET"
  git fetch origin "$TARGET"
  git checkout "$TARGET"
fi
git pull --ff-only origin "$TARGET"

# --- vérifs ---
cd "${REPO_ROOT}/site"
if [ ! -f .env.prod ]; then
  echo "✗ site/.env.prod manquant — crée-le à partir de .env.prod.example" >&2
  exit 3
fi

# --- build + restart ---
echo "== 2/3 : docker build + up =="
COMPOSE_ARGS=(-f docker-compose.prod.yml --env-file .env.prod)
if [ "$WITH_TUNNEL" -eq 1 ]; then
  COMPOSE_ARGS+=(--profile tunnel)
fi
docker compose "${COMPOSE_ARGS[@]}" up -d --build samplerod-site
if [ "$WITH_TUNNEL" -eq 1 ]; then
  docker compose "${COMPOSE_ARGS[@]}" up -d cloudflared
fi

# --- smoke test ---
echo "== 3/3 : smoke test =="
sleep 3
if command -v wget >/dev/null; then
  wget -qO- --tries=3 --timeout=5 http://127.0.0.1:8003/api/version && echo
else
  curl -fsS http://127.0.0.1:8003/api/version && echo
fi

echo "✓ déploiement OK"
