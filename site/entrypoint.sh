#!/usr/bin/env bash
set -e

mkdir -p "$(dirname "${DJANGO_DB_PATH:-/app/data/samplerod-site.sqlite3}")"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8003 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --access-logfile - \
    --error-logfile - \
    --log-level "${GUNICORN_LOG_LEVEL:-info}"
