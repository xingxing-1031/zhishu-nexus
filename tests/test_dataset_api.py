from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.app import app
from retail_analytics_agent.data_import import ImportResult, get_dataset_importer
from retail_analytics_agent.database import get_database_connection
from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    QualityReport,
    SchemaProfile,
    TableProfile,
)
from retail_analytics_agent.dataset_registry import get_dataset_registry
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.schema_profiler import get_schema_profiler
from retail_analytics_agent.settings import Settings, get_settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password="test_password",
        dataset_upload_root=tmp_path,
        _env_file=None,
    )


class _FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, int], DatasetRecord] = {}

    def create(self, record: DatasetRecord) -> DatasetRecord:
        return self.records.setdefault((record.dataset_id, record.version), record)

    def get(self, dataset_id: str, version: int | None = None) -> DatasetRecord | None:
        candidates = [
            record
            for (item_id, item_version), record in self.records.items()
            if item_id == dataset_id and (version is None or item_version == version)
        ]
        return max(candidates, key=lambda item: item.version) if candidates else None

    def update_status(
        self,
        dataset_id: str,
        status: DatasetStatus,
        *,
        version: int | None = None,
        quality_report: QualityReport | None = None,
    ) -> DatasetRecord:
        current = self.get(dataset_id, version)
        assert current is not None
        updated = current.model_copy(
            update={
                "status": status,
                "quality_report": quality_report.model_dump(mode="json")
                if quality_report is not None
                else current.quality_report,
            }
        )
        self.records[(updated.dataset_id, updated.version)] = updated
        return updated

    def save_mapping(self, mapping, *, confirmed: bool = False) -> DatasetRecord:
        current = self.get(mapping.dataset_id, mapping.version)
        assert current is not None
        updated = current.model_copy(
            update={
                "mapping": mapping.model_copy(
                    update={"confirmed": confirmed}
                ).model_dump(mode="json"),
                "mapping_confirmed": confirmed,
            }
        )
        self.records[(updated.dataset_id, updated.version)] = updated
        return updated

    def list_active(self) -> tuple[DatasetRecord, ...]:
        return tuple(
            record
            for record in self.records.values()
            if record.status is not DatasetStatus.ARCHIVED
        )


class _FakeImporter:
    def __init__(self, *, quality_passes: bool = True) -> None:
        self.quality_passes = quality_passes

    def import_file(self, request, connection) -> ImportResult:
        return ImportResult(
            dataset_id=request.dataset_id,
            version=request.version,
            schema_name=request.target_schema,
            tables=("dataset_rows",),
            row_counts={"dataset_rows": 2},
        )


class _FakeProfiler:
    def __init__(self, *, quality_passes: bool = True) -> None:
        self.quality_passes = quality_passes

    def inspect(self, schema_name, connection) -> SchemaProfile:
        return SchemaProfile(schema_name=schema_name)

    def quality(self, schema_name, connection) -> QualityReport:
        return QualityReport(
            passed=self.quality_passes,
            checked_rows=2,
        )


def test_analyst_cannot_register_dataset(tmp_path: Path) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="analyst",
        role=AccessRole.ANALYST,
    )
    try:
        response = TestClient(app).post(
            "/admin/datasets",
            data={
                "dataset_id": "demo",
                "dataset_name": "Demo",
                "version": "1",
                "source_type": "csv",
            },
            files={"file": ("orders.csv", "amount\n1\n", "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_admin_registration_stores_file_under_generated_path(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    app.dependency_overrides[get_dataset_registry] = lambda: registry
    try:
        response = TestClient(app).post(
            "/admin/datasets",
            data={
                "dataset_id": "demo",
                "dataset_name": "Demo",
                "version": "1",
                "source_type": "csv",
            },
            files={"file": ("orders.csv", "amount\n1\n", "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["schema_name"] == "staging_demo_1"
    assert payload["source_ref"] == "demo/v1.csv"
    assert (tmp_path / "demo" / "v1.csv").is_file()


def test_invalid_dataset_id_is_rejected_without_writing_file(tmp_path: Path) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    try:
        response = TestClient(app).post(
            "/admin/datasets",
            data={
                "dataset_id": "../escape",
                "dataset_name": "Demo",
                "version": "1",
                "source_type": "csv",
            },
            files={"file": ("orders.csv", "amount\n1\n", "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert not (tmp_path.parent / "escape").exists()


def test_failed_quality_report_does_not_mark_dataset_ready(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    importer = _FakeImporter()
    profiler = _FakeProfiler(quality_passes=False)
    record = DatasetRecord(
        dataset_id="demo",
        dataset_name="Demo",
        source_type=DatasetSourceType.CSV,
        source_ref="demo/v1.csv",
        schema_name="staging_demo_1",
        version=1,
    )
    registry.create(record)
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    app.dependency_overrides[get_dataset_registry] = lambda: registry
    app.dependency_overrides[get_dataset_importer] = lambda: importer
    app.dependency_overrides[get_schema_profiler] = lambda: profiler
    app.dependency_overrides[get_database_connection] = lambda: MagicMock()
    try:
        response = TestClient(app).post(
            "/admin/datasets/demo/profile?version=1",
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["quality"]["passed"] is False
    assert registry.get("demo", 1).status is DatasetStatus.FAILED


def test_ready_requires_mapping_confirmation_and_is_listed(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    record = DatasetRecord(
        dataset_id="demo",
        dataset_name="Demo",
        source_type=DatasetSourceType.CSV,
        source_ref="demo/v1.csv",
        schema_name="staging_demo_1",
        version=1,
        status=DatasetStatus.NEEDS_MAPPING,
        quality_report=QualityReport(passed=True, checked_rows=2).model_dump(mode="json"),
        mapping={
            "dataset_id": "demo",
            "version": 1,
            "fields": [],
            "confirmed": True,
        },
        mapping_confirmed=True,
    )
    registry.create(record)
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    app.dependency_overrides[get_dataset_registry] = lambda: registry
    try:
        client = TestClient(app)
        rejected = client.post(
            "/admin/datasets/demo/ready?version=1",
            json={"mapping_confirmed": False},
        )
        accepted = client.post(
            "/admin/datasets/demo/ready?version=1",
            json={"mapping_confirmed": True},
        )
        active = client.get("/admin/datasets")
    finally:
        app.dependency_overrides.clear()

    assert rejected.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ready"
    assert active.status_code == 200
    assert active.json()[0]["dataset_id"] == "demo"


def test_mapping_confirmation_is_stored_before_ready(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    registry.create(
        DatasetRecord(
            dataset_id="demo",
            dataset_name="Demo",
            source_type=DatasetSourceType.CSV,
            source_ref="demo/v1.csv",
            schema_name="staging_demo_1",
            version=1,
            status=DatasetStatus.NEEDS_MAPPING,
        )
    )
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    app.dependency_overrides[get_dataset_registry] = lambda: registry
    app.dependency_overrides[get_schema_profiler] = lambda: _FakeProfiler()
    app.dependency_overrides[get_database_connection] = lambda: MagicMock()
    try:
        response = TestClient(app).post(
            "/admin/datasets/demo/mapping?version=1",
            json={
                "dataset_id": "demo",
                "version": 1,
                "fields": [],
                "confirmed": False,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["mapping_confirmed"] is True


def test_profile_review_is_idempotent_for_profiled_dataset(tmp_path: Path) -> None:
    """Re-reading a profiled dataset must not re-import or change its state."""
    registry = _FakeRegistry()
    registry.create(
        DatasetRecord(
            dataset_id="demo",
            dataset_name="Demo",
            source_type=DatasetSourceType.CSV,
            source_ref="demo/v1.csv",
            schema_name="staging_demo_1",
            version=1,
            status=DatasetStatus.NEEDS_MAPPING,
            row_count=2,
            quality_report=QualityReport(passed=True, checked_rows=2).model_dump(
                mode="json"
            ),
            mapping={
                "dataset_id": "demo",
                "version": 1,
                "fields": [
                    {
                        "role": "amount",
                        "table": "dataset_rows",
                        "column": "amount",
                        "confidence": 1.0,
                        "reasons": [],
                    },
                ],
                "confirmed": False,
            },
            mapping_confirmed=False,
        )
    )
    importer = MagicMock()
    profiler = MagicMock()
    profiler.inspect.return_value = SchemaProfile(
        schema_name="staging_demo_1",
        tables=(
            TableProfile(
                table_name="dataset_rows",
                row_count=2,
                columns=(
                    ColumnProfile(
                        name="amount",
                        normalized_type="number",
                        null_ratio=0.0,
                        unique_ratio=1.0,
                    ),
                ),
            ),
        ),
    )
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    app.dependency_overrides[get_access_context] = lambda: AccessContext(
        user_id="admin",
        role=AccessRole.ADMIN,
    )
    app.dependency_overrides[get_dataset_registry] = lambda: registry
    app.dependency_overrides[get_dataset_importer] = lambda: importer
    app.dependency_overrides[get_schema_profiler] = lambda: profiler
    app.dependency_overrides[get_database_connection] = lambda: MagicMock()
    try:
        response = TestClient(app).post(
            "/admin/datasets/demo/profile?version=1",
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["status"] == "needs_mapping"
    assert payload["quality"]["passed"] is True
    assert payload["mapping"]["fields"][0]["role"] == "amount"
    assert payload["schema"]["tables"][0]["row_count"] == 2
    assert payload["import_result"]["tables"] == ["dataset_rows"]
    assert registry.get("demo", 1).status is DatasetStatus.NEEDS_MAPPING
    importer.import_file.assert_not_called()
    profiler.quality.assert_not_called()
    profiler.inspect.assert_called_once()
