#!/usr/bin/env bash
# Deploys the current local commit to the NAS: pushes to GitHub, then pulls
# on the NAS (into /volume1/docker/video-player/project) and rebuilds/restarts
# the video-player container. Requires the local commit to already exist
# (commit your changes before running this script).
set -euo pipefail

NAS_HOST="${NAS_HOST:-vlado@192.168.2.98}"
NAS_SSH_KEY="${NAS_SSH_KEY:-$HOME/.ssh/id_ed25519_nas}"
NAS_PROJECT_DIR="${NAS_PROJECT_DIR:-/volume1/docker/video-player/project}"

echo "==> Pushing local commits to origin"
git push

echo "==> Pulling latest changes on NAS and restarting container"
ssh -i "${NAS_SSH_KEY}" "${NAS_HOST}" "
  set -e
  cd '${NAS_PROJECT_DIR}'
  \$HOME/bin/git pull --ff-only
  sudo -n /usr/local/bin/docker-compose build
  sudo -n /usr/local/bin/docker-compose up -d
"

echo "==> Done. Check http://192.168.2.98:8080/"
