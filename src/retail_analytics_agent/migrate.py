from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.settings import Settings, get_settings

MIGRATION_TABLE = "schema_migrations"


class MigrationError(RuntimeError):
    """Raised when a database migration cannot be applied safely."""


@dataclass(frozen=True)
class MigrationReport:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def _strip_transaction_wrappers(sql: str) -> str:
    lines = sql.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and lines[0].strip().upper() == "BEGIN;":
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    while lines and lines[-1].strip().upper() == "COMMIT;":
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines).strip()


def _sql_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        raise MigrationError(f"SQL directory does not exist: {directory}")
    files = tuple(sorted(directory.glob("*.sql")))
    if not files:
        raise MigrationError(f"SQL directory is empty: {directory}")
    return files


def run_migrations(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    include_seed: bool = True,
    verify: bool = True,
) -> MigrationReport:
    root = project_root or Path.cwd()
    migration_files = _sql_files(root / "db" / "migrations")
    seed_files = (
        _sql_files(root / "db" / "seeds") if include_seed else ()
    )
    active_settings = settings or get_settings()
    applied: list[str] = []
    skipped: list[str] = []

    with connect_to_database(active_settings) as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        rows = connection.execute(
            f"SELECT version FROM {MIGRATION_TABLE}"
        ).fetchall()
        completed = {row["version"] for row in rows}

        for path in (*migration_files, *seed_files):
            version = path.name
            if path in seed_files:
                version = f"seed:{version}"
            if version in completed:
                skipped.append(version)
                continue
            sql = _strip_transaction_wrappers(
                path.read_text(encoding="utf-8")
            )
            try:
                with connection.transaction():
                    connection.execute(sql)
                    connection.execute(
                        f"INSERT INTO {MIGRATION_TABLE} (version) VALUES (%s)",
                        (version,),
                    )
            except Exception as exc:
                raise MigrationError(
                    f"failed to apply {version}; transaction rolled back"
                ) from exc
            applied.append(version)

        if verify:
            verification_path = root / "db" / "verification" / "verify_delivery.sql"
            verification_sql = verification_path.read_text(encoding="utf-8")
            try:
                with connection.transaction():
                    connection.execute(verification_sql)
            except Exception as exc:
                raise MigrationError(
                    "database migration completed but delivery verification failed"
                ) from exc

    return MigrationReport(tuple(applied), tuple(skipped))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply versioned retail analytics PostgreSQL migrations."
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="do not insert the demo seed dataset",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="skip delivery verification (not recommended for deployment)",
    )
    args = parser.parse_args()
    report = run_migrations(
        include_seed=not args.skip_seed,
        verify=not args.skip_verify,
    )
    print(f"applied={len(report.applied)} skipped={len(report.skipped)}")
    for version in report.applied:
        print(f"applied: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
