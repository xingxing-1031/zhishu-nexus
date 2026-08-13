#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <expected-commit>" >&2
  exit 2
fi

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.vps}"
EXPECTED_COMMIT="$1"
RELEASE_BUNDLE="${RELEASE_BUNDLE:-}"
SERVICE_TOKEN_FILE="${SERVICE_TOKEN_FILE:-}"
cd "$PROJECT_DIR"

cleanup() {
  if [[ -n "$SERVICE_TOKEN_FILE" ]]; then
    rm -f "$SERVICE_TOKEN_FILE"
  fi
  if [[ -n "$RELEASE_BUNDLE" ]]; then
    rm -f "$RELEASE_BUNDLE"
  fi
}
trap cleanup EXIT

DIRTY_STATUS="$(git status --porcelain --untracked-files=all | grep -vE '^\?\? \.deployed-release$' || true)"
if [[ -n "$DIRTY_STATUS" ]]; then
  echo "refusing deployment because the server worktree has local changes" >&2
  printf '%s\n' "$DIRTY_STATUS" >&2
  exit 1
fi

if [[ ! -r "$RELEASE_BUNDLE" ]]; then
  echo "missing release bundle: $RELEASE_BUNDLE" >&2
  exit 1
fi
git fetch "$RELEASE_BUNDLE" HEAD
TARGET_COMMIT="$(git rev-parse FETCH_HEAD)"
if [[ "$TARGET_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  echo "release bundle commit mismatch: expected=$EXPECTED_COMMIT actual=$TARGET_COMMIT" >&2
  exit 1
fi
git checkout --detach "$TARGET_COMMIT"

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp)"
  grep -v "^${key}=" "$ENV_FILE" > "$temporary" || true
  printf "%s='%s'\n" "$key" "$value" >> "$temporary"
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
if [[ ! -r "$SERVICE_TOKEN_FILE" ]]; then
  echo "missing internal service token file" >&2
  exit 1
fi
INTERNAL_SERVICE_TOKEN="$(sed '1s/^\xEF\xBB\xBF//' "$SERVICE_TOKEN_FILE" | tr -d '\r\n')"
if [[ ! "$INTERNAL_SERVICE_TOKEN" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "internal service token must be 64 hexadecimal characters" >&2
  exit 1
fi
set_env_value KNOWLEDGE_SERVICE_URL http://host.docker.internal:8010
set_env_value KNOWLEDGE_SERVICE_TOKEN "$INTERNAL_SERVICE_TOKEN"
set_env_value INTERNAL_SERVICE_TOKEN "$INTERNAL_SERVICE_TOKEN"
set_env_value KNOWLEDGE_DEPARTMENTS admin
set_env_value AGENT_CONTEXT_TOKEN_BUDGET 4000
set_env_value AGENT_MAX_STEPS 8
set_env_value MCP_EXPORT_ENABLED true
set_env_value MCP_EXPORT_TIMEOUT_SECONDS 15
set_env_value PIP_INDEX_URL https://mirrors.cloud.tencent.com/pypi/simple
unset INTERNAL_SERVICE_TOKEN

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml --profile tools run --rm --build migrate
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml up -d --build api caddy
curl --fail --silent --show-error --max-time 15 http://127.0.0.1/ready >/dev/null

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T api \
  python -c "from retail_analytics_agent.skills import default_skill_registry; assert default_skill_registry().route('delete from orders').refused"
git rev-parse HEAD > .deployed-release
echo "deployed=$(cat .deployed-release)"
