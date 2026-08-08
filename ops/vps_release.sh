#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <git-ref>" >&2
  exit 2
fi

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.vps}"
REFERENCE="$1"
cd "$PROJECT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing deployment because the server worktree has local changes" >&2
  exit 1
fi

git fetch --tags origin
git checkout --detach "$REFERENCE"
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml --profile tools run --rm --build migrate
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml up -d --build api caddy
curl --fail --silent --show-error --max-time 15 http://127.0.0.1/ready >/dev/null
git rev-parse HEAD > .deployed-release
echo "deployed=$(cat .deployed-release)"
