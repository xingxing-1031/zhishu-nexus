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

DIRTY_STATUS="$(git status --porcelain --untracked-files=all | grep -vE '^\?\? \.deployed-release$' || true)"
if [[ -n "$DIRTY_STATUS" ]]; then
  echo "refusing deployment because the server worktree has local changes" >&2
  printf '%s\n' "$DIRTY_STATUS" >&2
  exit 1
fi

git fetch --tags origin
TARGET_REFERENCE="$REFERENCE"
if git rev-parse --verify --quiet "origin/$REFERENCE" >/dev/null; then
  TARGET_REFERENCE="origin/$REFERENCE"
fi
git checkout --detach "$TARGET_REFERENCE"
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml --profile tools run --rm --build migrate
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml up -d --build api caddy
curl --fail --silent --show-error --max-time 15 http://127.0.0.1/ready >/dev/null
git rev-parse HEAD > .deployed-release
echo "deployed=$(cat .deployed-release)"
