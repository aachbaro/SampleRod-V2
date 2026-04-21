#!/usr/bin/env bash
# logs.sh — tail des logs du site + (option) cloudflared
#
# Usage :
#   ./logs.sh                 # tail site
#   ./logs.sh -f              # follow
#   ./logs.sh --tunnel        # logs du tunnel Cloudflare aussi
#   ./logs.sh --since 10m -f  # logs récents puis follow
set -euo pipefail

SERVICE="site-samplerod-site-1"
TUNNEL="fragment-cloudflared-1"
INCLUDE_TUNNEL=0
DOCKER_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --tunnel) INCLUDE_TUNNEL=1 ;;
    *)        DOCKER_ARGS+=("$arg") ;;
  esac
done

if [ ${#DOCKER_ARGS[@]} -eq 0 ]; then
  DOCKER_ARGS=(--tail 100)
fi

echo "== $SERVICE =="
docker logs "${DOCKER_ARGS[@]}" "$SERVICE" 2>&1 &
SITE_PID=$!

if [ "$INCLUDE_TUNNEL" -eq 1 ]; then
  echo "== $TUNNEL =="
  docker logs "${DOCKER_ARGS[@]}" "$TUNNEL" 2>&1 | sed 's/^/[tunnel] /' &
fi

wait $SITE_PID
