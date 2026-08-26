"""API tests for the dataset lifecycle closure: analyst ready-dataset view
and the admin archive endpoint introduced in stage 6.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from retail_analytics_agent.access_control import get_access_context
from retail_analytics_agent.app import app
from retail_analytics_agent.dataset_models import (
    DatasetRecord,
    DatasetSourceType,
    DatasetStatus,
    QualityReport,
)
from retail_analytics_agent.dataset_mapping import MappingRole
from retail_analytics_agent.dataset_registry import (
    DatasetNotFoundError,
    DatasetStatusTransitionError,
    get_dataset_registry,
)
from retail_analytics_agent.metric_models import DatasetMetric, MetricStatus
from retail_analytics_agent.models import AccessContext, AccessRole
from retail_analytics_agent.settings import Settings, get_settings

_ALLOWED_TRANSITIONS: dict[DatasetStatus, frozenset[DatasetStatus]] = {
    DatasetStatus.UPLOADED: frozenset({DatasetStatus.PROFILING, DatasetStatus.FAILED}),
    DatasetStatus.PROFILING: frozenset({DatasetStatus.NEEDS_MAPPING, DatasetStatus.FAILED}),
    DatasetStatus.NEEDS_MAPPING: frozenset({DatasetStatus.READY, DatasetStatus.FAILED}),
    DatasetStatus.READY: frozenset({DatasetStatus.ARCHIVED}),
    DatasetStatus.FAILED: frozenset({DatasetStatus.PROFILING, DatasetStatus.ARCHIVED}),
    DatasetStatus.ARCHIVED: frozenset(),
}


class _FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, int], DatasetRecord] = {}
        self.metrics: dict[tuple[str, int, str], DatasetMetric] = {}

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
        if current is None:
            raise DatasetNotFoundError(f"dataset not found: {dataset_id}")
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise DatasetStatusTransitionError(
                f"invalid dataset status transition: "
                f"{current.status.value} -> {status.value}"
            )
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

    def list_active(self) -> tuple[DatasetRecord, ...]:
        return tuple(
            record
            for record in self.records.values()
            if record.status is not DatasetStatus.ARCHIVED
        )

    def save_metric(self, metric: DatasetMetric) -> DatasetMetric:
        self.metrics[
            (metric.dataset_id, metric.dataset_version, metric.metric_id)
        ] = metric
        return metric

    def list_metrics(
        self,
        dataset_id: str,
        version: int,
    ) -> tuple[DatasetMetric, ...]:
        return tuple(
            metric
            for (item_id, item_version, _metric_id), metric in self.metrics.items()
            if item_id == dataset_id and item_version == version
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password="test_password",
        dataset_upload_root=tmp_path,
        _env_file=None,
    )


def _record(
    dataset_id: str,
    version: int = 1,
    *,
    status: DatasetStatus = DatasetStatus.READY,
    name: str = "演示数据集",
) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        dataset_name=name,
        source_type=DatasetSourceType.CSV,
        source_ref=f"{dataset_id}/v{version}.csv",
        schema_name=f"staging_{dataset_id}_{version}",
        version=version,
        status=status,
        row_count=1000 if status is DatasetStatus.READY else 0,
        quality_report=QualityReport(passed=True, checked_rows=1000).model_dump(
            mode="json"
        )
        if status is DatasetStatus.READY
        else None,
    )


def _confirmed_metric(dataset_id: str, version: int) -> DatasetMetric:
    return DatasetMetric(
        dataset_id=dataset_id,
        dataset_version=version,
        metric_id="sales_amount",
        metric_version="v1",
        name="销售额",
        definition="销售额为已确认金额字段的合计。",
        aggregation="SUM",
        formula=f"SUM(dataset_rows.gross_amount)",
        source_role=MappingRole.AMOUNT,
        source_table="dataset_rows",
        source_column="gross_amount",
        supported_dimensions=(MappingRole.CHANNEL, MappingRole.REGION),
        status=MetricStatus.CONFIRMED,
    )


class TestAnalystDatasetView:
    def test_analyst_sees_only_ready_datasets_with_confirmed_metrics(
        self, tmp_path: Path
    ) -> None:
        registry = _FakeRegistry()
        registry.create(
            _record("sales", status=DatasetStatus.READY, name="跨渠道销售")
        )
        registry.save_metric(_confirmed_metric("sales", 1))
        registry.create(
            _record("draft", status=DatasetStatus.NEEDS_MAPPING, name="草稿")
        )
        registry.create(
            _record("old", status=DatasetStatus.ARCHIVED, name="归档")
        )
        app.dependency_overrides[get_dataset_registry] = lambda: registry
        app.dependency_overrides[get_access_context] = lambda: AccessContext(
            user_id="analyst",
            role=AccessRole.ANALYST,
        )
        try:
            response = TestClient(app).get("/datasets")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = response.json()
        assert [item["dataset_id"] for item in payload] == ["sales"]
        view = payload[0]
        assert view["dataset_name"] == "跨渠道销售"
        assert view["version"] == 1
        assert view["status"] == "ready"
        assert view["row_count"] == 1000
        metric = view["metrics"][0]
        assert metric["metric_id"] == "sales_amount"
        assert metric["formula"] == "SUM(dataset_rows.gross_amount)"
        assert metric["supported_dimensions"] == ["channel", "region"]

    def test_analyst_cannot_list_admin_datasets(self, tmp_path: Path) -> None:
        app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
        app.dependency_overrides[get_access_context] = lambda: AccessContext(
            user_id="analyst",
            role=AccessRole.ANALYST,
        )
        try:
            response = TestClient(app).get("/admin/datasets")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403


class TestArchiveDataset:
    def _admin_request(self, tmp_path: Path, registry: _FakeRegistry):
        app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
        app.dependency_overrides[get_access_context] = lambda: AccessContext(
            user_id="admin",
            role=AccessRole.ADMIN,
        )
        app.dependency_overrides[get_dataset_registry] = lambda: registry

    def test_admin_archives_ready_dataset(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        registry.create(_record("sales", status=DatasetStatus.READY))
        self._admin_request(tmp_path, registry)
        try:
            response = TestClient(app).post("/admin/datasets/sales/archive?version=1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["status"] == "archived"
        assert registry.get("sales", 1).status is DatasetStatus.ARCHIVED

    def test_archive_removes_dataset_from_analyst_view(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        registry.create(_record("sales", status=DatasetStatus.READY))
        self._admin_request(tmp_path, registry)
        try:
            client = TestClient(app)
            client.post("/admin/datasets/sales/archive?version=1")
            app.dependency_overrides[get_access_context] = lambda: AccessContext(
                user_id="analyst",
                role=AccessRole.ANALYST,
            )
            visible = client.get("/datasets")
        finally:
            app.dependency_overrides.clear()

        assert visible.status_code == 200
        assert visible.json() == []

    def test_archive_requires_valid_transition(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        registry.create(
            _record("draft", status=DatasetStatus.NEEDS_MAPPING)
        )
        self._admin_request(tmp_path, registry)
        try:
            response = TestClient(app).post("/admin/datasets/draft/archive?version=1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409

    def test_archive_missing_dataset_returns_404(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        self._admin_request(tmp_path, registry)
        try:
            response = TestClient(app).post("/admin/datasets/ghost/archive?version=1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_analyst_cannot_archive(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        registry.create(_record("sales", status=DatasetStatus.READY))
        app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
        app.dependency_overrides[get_access_context] = lambda: AccessContext(
            user_id="analyst",
            role=AccessRole.ANALYST,
        )
        app.dependency_overrides[get_dataset_registry] = lambda: registry
        try:
            response = TestClient(app).post("/admin/datasets/sales/archive?version=1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403
        assert registry.get("sales", 1).status is DatasetStatus.READY
