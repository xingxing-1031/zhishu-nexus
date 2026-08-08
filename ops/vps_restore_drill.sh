#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /absolute/path/to/backup.dump" >&2
  exit 2
fi

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.vps}"
BACKUP="$1"
RESTORE_DB="${RESTORE_DB:-retail_restore_drill}"

if [[ ! -f "$BACKUP" || ! "$BACKUP" = /* ]]; then
  echo "backup must be an existing absolute path" >&2
  exit 2
fi

cd "$PROJECT_DIR"
set -a
source "$ENV_FILE"
set +a

if [[ -f "${BACKUP}.sha256" ]]; then
  (cd "$(dirname "$BACKUP")" && sha256sum --check "$(basename "${BACKUP}.sha256")")
fi

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  dropdb --if-exists --username "$POSTGRES_USER" "$RESTORE_DB"
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  createdb --username "$POSTGRES_USER" "$RESTORE_DB"
cat "$BACKUP" | docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  pg_restore --exit-on-error --no-owner --username "$POSTGRES_USER" --dbname "$RESTORE_DB"

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  psql --tuples-only --no-align --username "$POSTGRES_USER" --dbname "$RESTORE_DB" \
  --command "SELECT COUNT(*) FROM orders;"
docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  dropdb --username "$POSTGRES_USER" "$RESTORE_DB"
echo "restore drill passed"
