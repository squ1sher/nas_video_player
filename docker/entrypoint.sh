#!/usr/bin/env sh
set -eu

ensure_writable_dir() {
  dir_path="$1"
  dir_label="$2"

  mkdir -p "$dir_path"

  if [ ! -d "$dir_path" ]; then
	echo "[bootstrap] ERROR: Failed to create runtime directory for $dir_label: $dir_path" >&2
	exit 1
  fi

  probe_file="$dir_path/.write-probe-$$"
  if ! (umask 077 && : > "$probe_file") 2>/dev/null; then
	echo "[bootstrap] ERROR: Runtime directory is not writable for $dir_label: $dir_path" >&2
	echo "[bootstrap] Check Synology bind mount permissions for this host path." >&2
	exit 1
  fi
  rm -f "$probe_file"

  echo "[bootstrap] Ready: $dir_label -> $dir_path"
}

ensure_writable_dir "$(dirname "${DATABASE_PATH:-/app/data/app.db}")" "database"
ensure_writable_dir "${THUMBNAILS_PATH:-/app/thumbnails}" "thumbnails"
ensure_writable_dir "${CACHE_PATH:-/app/cache}" "cache"
ensure_writable_dir "${HLS_OUTPUT_PATH:-/app/cache/hls}" "hls"
ensure_writable_dir "${LOGS_PATH:-/app/logs}" "logs"

exec uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8080}"

