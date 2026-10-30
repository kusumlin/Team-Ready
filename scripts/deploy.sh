#!/usr/bin/env bash
# Copy the project to the server and (re)start it:  ./scripts/deploy.sh SERVER_IP
# Stop any local agents first: only one copy may run with the real seeds.
set -euo pipefail
cd "$(dirname "$0")/.."
IP="${1:?usage: scripts/deploy.sh SERVER_IP}"
KEY="${UNBLOCK_SSH_KEY:-$HOME/.ssh/unblock_deploy}"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new root@$IP"

if [ -f logs/pids ] && kill -0 $(cat logs/pids) 2>/dev/null; then
  echo "Local agents are running. Stop them first: kill \$(cat logs/pids)"; exit 1
fi

$SSH 'command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh; mkdir -p /root/unblock'
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .venv --exclude logs --exclude data/runtime --exclude outbox --exclude .git \
  --exclude .env --exclude friction.json --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  ./ "root@$IP:/root/unblock/"
scp -q -i "$KEY" .env "root@$IP:/root/unblock/.env"
$SSH 'chmod 600 /root/unblock/.env && cd /root/unblock && docker compose up -d --build && docker compose ps'
echo "Follow agents: $SSH 'cd /root/unblock && docker compose logs -f agents'"
