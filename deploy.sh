#!/usr/bin/env bash
# Run the tests, copy the bridge to the docker host, rebuild, restart and health-check.
# Settings live in deploy.env (copy deploy.env.example). Supports a plain docker host over
# SSH, or a Proxmox LXC (DEPLOY_PCT) reached through its node.
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.env ] || { echo "Create deploy.env from deploy.env.example first."; exit 1; }
# shellcheck disable=SC1091
source deploy.env
: "${DEPLOY_SSH:?}" "${DEPLOY_DIR:?}" "${BRIDGE_URL:?}"

python3 -m unittest discover -s tests -q

run() {  # run a command on the docker host
  if [ -n "${DEPLOY_PCT:-}" ]; then ssh "$DEPLOY_SSH" "pct exec $DEPLOY_PCT -- bash -c $(printf '%q' "$1")"
  else ssh "$DEPLOY_SSH" "$1"; fi
}
put() {  # copy a local file to the docker host
  if [ -n "${DEPLOY_PCT:-}" ]; then
    scp -q "$1" "$DEPLOY_SSH:/tmp/abb-torznab-$1"
    ssh "$DEPLOY_SSH" "pct push $DEPLOY_PCT /tmp/abb-torznab-$1 $DEPLOY_DIR/$1 && rm -f /tmp/abb-torznab-$1"
  else scp -q "$1" "$DEPLOY_SSH:$DEPLOY_DIR/$1"; fi
}

run "mkdir -p $DEPLOY_DIR/data"
for f in app.py Dockerfile docker-compose.yml .dockerignore .env.example; do put "$f"; done
run "cd $DEPLOY_DIR && docker compose up -d --build"
sleep 4
run "curl -fsS $BRIDGE_URL/health" && echo " deployed"
