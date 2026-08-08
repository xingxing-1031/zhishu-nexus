#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.vps}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

cd "$PROJECT_DIR"
set -a
source "$ENV_FILE"
set +a
mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$BACKUP_DIR/retail_${timestamp}.dump"
temporary="${backup}.partial"

docker compose --env-file "$ENV_FILE" -f compose.vps.yaml exec -T postgres \
  pg_dump --format=custom --no-owner --username "$POSTGRES_USER" "$POSTGRES_DB" \
  > "$temporary"
mv "$temporary" "$backup"
sha256sum "$backup" > "${backup}.sha256"
find "$BACKUP_DIR" -type f \( -name '*.dump' -o -name '*.sha256' \) -mtime "+$RETENTION_DAYS" -delete
printf 'backup=%s\n' "$backup"
