#!/usr/bin/env bash
set -euo pipefail

BASE_PATH="${1:-/volume1/docker/video-player}"
PROJECT_DIR="${BASE_PATH}/project"
REPO_URL="https://github.com/squ1sher/nas_video_player.git"

echo "Restoring/updating project under: ${PROJECT_DIR}"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required but was not found in PATH." >&2
  exit 1
fi

mkdir -p "${BASE_PATH}"

if [ ! -d "${PROJECT_DIR}" ] || [ -z "$(ls -A "${PROJECT_DIR}" 2>/dev/null)" ]; then
  echo "Project folder is missing or empty. Cloning repository..."
  git clone "${REPO_URL}" "${PROJECT_DIR}"
elif [ -d "${PROJECT_DIR}/.git" ]; then
  echo "Git repository detected. Pulling latest changes..."
  git -C "${PROJECT_DIR}" pull --ff-only
else
  echo "ERROR: ${PROJECT_DIR} exists and is not empty, but is not a git repository." >&2
  echo "       Refusing to overwrite existing files." >&2
  exit 1
fi

echo "Project is ready: ${PROJECT_DIR}"
echo "Run next:"
echo "  bash ${PROJECT_DIR}/scripts/bootstrap-synology.sh ${BASE_PATH}"
echo "  cd ${PROJECT_DIR}"
echo "  sudo docker compose up -d --build"

