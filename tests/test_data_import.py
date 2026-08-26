from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from retail_analytics_agent.data_import import (
    FileDatasetImporter,
    ImportRequest,
    ImportResult,
    UnsafeDatasetPathError,
    UnsupportedDatasetFormatError,
)
from retail_analytics_agent.dataset_models import DatasetSourceType


def _connection() -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    return connection


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_csv_import_creates_isolated_schema_and_preserves_rows(tmp_path: Path) -> None:
    source = _write_csv(
        tmp_path / "orders.csv",
        "Order ID,Amount,Channel\nA-1,12.50,web\nA-2,7.00,store\n",
    )
    connection = _connection()
    importer = FileDatasetImporter(upload_root=tmp_path)

    result = importer.import_file(
        ImportRequest(
            dataset_id="demo",
            version=2,
            source_path=source,
            source_type=DatasetSourceType.CSV,
            target_schema="staging_demo_2",
        ),
        connection,
    )

    assert isinstance(result, ImportResult)
    assert result.schema_name == "staging_demo_2"
    assert result.tables == ("dataset_rows",)
    assert result.row_counts == {"dataset_rows": 2}
    create_sql = str(connection.execute.call_args_list[0].args[0])
    assert "CREATE SCHEMA" in create_sql
    assert "staging_demo_2" in create_sql
    assert "order_id" in str(connection.execute.call_args_list[1].args[0])
    connection.cursor.assert_called_once()
    connection.cursor.return_value.__enter__.return_value.executemany.assert_called_once()


def test_csv_import_rejects_duplicate_columns_after_normalization(tmp_path: Path) -> None:
    source = _write_csv(
        tmp_path / "duplicate.csv",
        "Order ID,order-id,Amount\nA-1,A-1,12\n",
    )
    importer = FileDatasetImporter(upload_root=tmp_path)

    with pytest.raises(ValueError, match="duplicate column"):
        importer.import_file(
            ImportRequest(
                dataset_id="demo",
                version=1,
                source_path=source,
                source_type=DatasetSourceType.CSV,
                target_schema="staging_demo_1",
            ),
            _connection(),
        )


def test_import_rejects_path_traversal_before_database_execution(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.csv"
    _write_csv(outside, "amount\n1\n")
    importer = FileDatasetImporter(upload_root=tmp_path)
    connection = _connection()

    with pytest.raises(UnsafeDatasetPathError):
        importer.import_file(
            ImportRequest(
                dataset_id="demo",
                version=1,
                source_path=outside,
                source_type=DatasetSourceType.CSV,
                target_schema="staging_demo_1",
            ),
            connection,
        )

    connection.execute.assert_not_called()


def test_import_rejects_declared_type_and_extension_mismatch(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "orders.txt", "amount\n1\n")
    importer = FileDatasetImporter(upload_root=tmp_path)

    with pytest.raises(UnsupportedDatasetFormatError):
        importer.import_file(
            ImportRequest(
                dataset_id="demo",
                version=1,
                source_path=source,
                source_type=DatasetSourceType.CSV,
                target_schema="staging_demo_1",
            ),
            _connection(),
        )


def test_second_dataset_uses_a_different_schema(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "orders.csv", "amount\n1\n")
    connection = _connection()
    importer = FileDatasetImporter(upload_root=tmp_path)

    importer.import_file(
        ImportRequest(
            dataset_id="first",
            version=1,
            source_path=source,
            source_type=DatasetSourceType.CSV,
            target_schema="staging_first_1",
        ),
        connection,
    )
    importer.import_file(
        ImportRequest(
            dataset_id="second",
            version=1,
            source_path=source,
            source_type=DatasetSourceType.CSV,
            target_schema="staging_second_1",
        ),
        connection,
    )

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert any("staging_first_1" in statement for statement in statements)
    assert any("staging_second_1" in statement for statement in statements)


def test_parquet_import_explains_optional_dependency_when_unavailable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "orders.parquet"
    source.write_bytes(b"not-a-parquet-file")
    importer = FileDatasetImporter(upload_root=tmp_path)

    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="optional data dependencies"):
            importer.import_file(
                ImportRequest(
                    dataset_id="demo",
                    version=1,
                    source_path=source,
                    source_type=DatasetSourceType.PARQUET,
                    target_schema="staging_demo_1",
                ),
                _connection(),
            )
    else:
        pytest.skip("optional parquet dependencies are installed")

