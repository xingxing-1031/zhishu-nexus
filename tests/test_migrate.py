from pathlib import Path

import pytest

from retail_analytics_agent.migrate import (
    MigrationError,
    _sql_files,
    _strip_transaction_wrappers,
)


def test_strip_transaction_wrappers_keeps_sql_body() -> None:
    sql = "BEGIN;\nCREATE TABLE demo (id integer);\nCOMMIT;\n"

    assert _strip_transaction_wrappers(sql) == "CREATE TABLE demo (id integer);"


def test_strip_transaction_wrappers_only_removes_outer_wrappers() -> None:
    sql = "\nBEGIN;\nSELECT 'BEGIN;' AS value;\nCOMMIT;\n"

    assert _strip_transaction_wrappers(sql) == "SELECT 'BEGIN;' AS value;"


def test_sql_files_are_sorted_and_missing_directory_is_rejected(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (migrations / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")

    assert [path.name for path in _sql_files(migrations)] == [
        "001_first.sql",
        "002_second.sql",
    ]
    with pytest.raises(MigrationError, match="does not exist"):
        _sql_files(tmp_path / "missing")


def test_repository_migrations_include_agent_run_registry() -> None:
    root = Path(__file__).resolve().parents[1]

    files = _sql_files(root / "db" / "migrations")

    assert files[-1].name == "014_trace_payload.sql"
    assert any(path.name == "010_agent_request_runs.sql" for path in files)
