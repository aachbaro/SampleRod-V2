#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env.prod ]; then
  echo "missing .env.prod (copy .env.prod.example and fill it in)"
  exit 1
fi

mkdir -p /srv/samplerod/data /srv/samplerod/releases

WITH_TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --with-tunnel) WITH_TUNNEL=1 ;;
  esac
done

if [ "$WITH_TUNNEL" -eq 1 ]; then
  docker compose --env-file .env.prod -f docker-compose.prod.yml --profile tunnel up -d --build
else
  docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
fi

echo
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
