#!/usr/bin/env bash
set -euo pipefail

BASE_PATH="${1:-/volume1/docker/video-player}"

REQUIRED_DIRS=(
  "project"
  "data"
  "thumbnails"
  "cache"
  "cache/hls"
  "logs"
)

echo "Preparing Synology deployment folders under: ${BASE_PATH}"
mkdir -p "${BASE_PATH}"

verify_writable_dir() {
  local dir_path="$1"
  local probe_file

  probe_file="${dir_path}/.write-probe-$$"
  if ! (umask 077 && : > "${probe_file}") 2>/dev/null; then
    echo "ERROR: Directory is not writable: ${dir_path}" >&2
    echo "       Check Synology filesystem permissions and rerun." >&2
    exit 1
  fi
  rm -f "${probe_file}"
}

for relative_dir in "${REQUIRED_DIRS[@]}"; do
  target_dir="${BASE_PATH}/${relative_dir}"
  mkdir -p "${target_dir}"
  verify_writable_dir "${target_dir}"
  echo "Created/verified: ${target_dir}"
done

cat <<EOF

Next steps:
  cd ${BASE_PATH}/project
  git clone https://github.com/squ1sher/nas_video_player.git .   # if project is empty
  # or copy project files here
  sudo docker compose up -d --build

Note:
  This script recreates the folder structure only.
  If source code was deleted from ${BASE_PATH}/project, you still need to clone/copy it again.
EOF

