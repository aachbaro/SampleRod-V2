#!/usr/bin/env bash
# status.sh — vue d'ensemble du site marchand sur la tour
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$REPO_ROOT" ] || { echo "✗ pas dans un repo git" >&2; exit 1; }
cd "$REPO_ROOT"

echo "== Git =="
echo "branche    : $(git branch --show-current)"
echo "dernier    : $(git log --oneline -1)"
ahead=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "?")
behind=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo "?")
echo "vs origin  : ahead $ahead / behind $behind"
echo

echo "== Containers =="
docker ps --filter name=site-samplerod --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker ps --filter name=fragment-cloudflared --format 'table {{.Names}}\t{{.Status}}'
echo

echo "== Site =="
if command -v wget >/dev/null; then
  printf "local  : "; wget -qO- --timeout=3 http://127.0.0.1:8003/api/version || echo "(down)"
  echo
  printf "public : "; wget -qO- --timeout=5 https://samplerod.pascuans.dev/api/version || echo "(down)"
  echo
fi

echo "== Releases =="
echo "current -> $(readlink /srv/samplerod/releases/current 2>/dev/null || echo '(none)')"
ls -1 /srv/samplerod/releases/ 2>/dev/null | grep -v '^current$' | head -5 | sed 's/^/  /'
