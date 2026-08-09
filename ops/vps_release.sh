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

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp)"
  grep -v "^${key}=" "$ENV_FILE" > "$temporary" || true
  printf '%s=%s\n' "$key" "$value" >> "$temporary"
  mv "$temporary" "$ENV_FILE"
}

hash_demo_password() {
  python3 - "$1" <<'PY'
import base64
import hashlib
import secrets
import sys

password = sys.argv[1]
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
print(f"pbkdf2_sha256$210000${encode(salt)}${encode(digest)}")
PY
}

set_env_value AUTH_MODE password
set_env_value AUTH_USER_ID ANALYST-001
set_env_value AUTH_USERNAME analyst-demo
set_env_value AUTH_ROLE analyst
set_env_value AUTH_PASSWORD_HASH "$(hash_demo_password 'DemoAnalyst2026!')"
set_env_value AUTH_ADMIN_USER_ID ADMIN-001
set_env_value AUTH_ADMIN_USERNAME admin-demo
set_env_value AUTH_ADMIN_PASSWORD_HASH "$(hash_demo_password 'DemoAdmin2026!')"
if ! grep -q '^AUTH_SESSION_SECRET=.' "$ENV_FILE"; then
  set_env_value AUTH_SESSION_SECRET "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml --profile tools run --rm --build migrate
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml up -d --build api caddy
curl --fail --silent --show-error --max-time 15 http://127.0.0.1/ready >/dev/null
git rev-parse HEAD > .deployed-release
echo "deployed=$(cat .deployed-release)"
