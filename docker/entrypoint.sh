#!/usr/bin/env sh
set -eu

mkdir -p "$(dirname "${DATABASE_PATH:-/app/data/app.db}")"
mkdir -p "${THUMBNAILS_PATH:-/app/thumbnails}"
mkdir -p "${CACHE_PATH:-/app/cache}"
mkdir -p "${LOGS_PATH:-/app/logs}"

exec uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8080}"

