# 销售数据接入与 Schema 探查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 支持将 CSV/Parquet 销售数据导入隔离的 PostgreSQL staging schema，并生成可供后续 Agent 使用的 SchemaProfile 和数据质量报告。

**Architecture:** 新增数据集注册、文件导入、Schema 探查和质量报告四个边界。文件先进入受控 staging schema，在线查询继续使用 PostgreSQL 只读连接；原有 public 业务表和分析工作流保持兼容。数据集只有在质量检查完成且映射状态允许后才能标记为 `ready`。

**Tech Stack:** Python 3.11+, Pydantic v2, psycopg 3, PostgreSQL 16, FastAPI, pytest, existing migration runner.

## Global Constraints

- Keep Python 3.11+ and the existing `src` package layout.
- Keep public `orders`, `order_items`, `products`, `refunds` behavior unchanged.
- Use typed Pydantic boundaries and reject unknown input fields.
- Never execute SQL derived from uploaded content without the existing read-only safety path.
- Do not invent data-quality or migration benchmark results.
- Every behavior change must include focused tests.

---

### Task 1: Add dataset and profile domain models

**Files:**
- Create: `src/retail_analytics_agent/dataset_models.py`
- Test: `tests/test_dataset_models.py`

**Interfaces:**
- Produces `DatasetStatus`, `DatasetSourceType`, `DatasetRecord`, `ColumnProfile`, `TableProfile`, `SchemaProfile`, `QualityIssue`, `QualityReport`.
- Later tasks consume these models without depending on database rows or FastAPI request objects.

- [x] **Step 1: Write failing model tests**

Test that a valid dataset record accepts `dataset_id`, source type, schema name, version, status and row count; unknown fields are rejected; quality reports preserve severity and table/column location; status values are restricted to `uploaded`, `profiling`, `needs_mapping`, `ready`, `failed`, and `archived`.

- [x] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_dataset_models.py -q`

Expected: FAIL because `dataset_models.py` and its models do not exist.

- [x] **Step 3: Implement typed models**

Use the repository's strict Pydantic pattern. `DatasetRecord` must validate non-empty identifiers, a positive version, a non-negative row count, and a schema name matching `staging_[a-z0-9_]+`. `ColumnProfile` stores name, normalized type, null ratio, unique ratio and sample values. `TableProfile` stores columns and row count. `QualityIssue` stores code, severity, message, table and optional column. `QualityReport` stores passed, checked row count and a tuple of issues.

- [x] **Step 4: Run the focused test**

Run: `python -m pytest tests/test_dataset_models.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/retail_analytics_agent/dataset_models.py tests/test_dataset_models.py
git commit -m "feat: add sales dataset profile models"
```

### Task 2: Persist dataset registry and staging metadata

**Files:**
- Create: `db/migrations/011_dataset_registry.sql`
- Create: `src/retail_analytics_agent/dataset_registry.py`
- Test: `tests/test_dataset_registry.py`

**Interfaces:**
- `DatasetRegistry.create(record) -> DatasetRecord`
- `DatasetRegistry.get(dataset_id) -> DatasetRecord | None`
- `DatasetRegistry.update_status(dataset_id, status, quality_report=None) -> DatasetRecord`
- `DatasetRegistry.list_active() -> tuple[DatasetRecord, ...]`
- The registry uses the existing psycopg connection and never interpolates user-provided table names without identifier validation.

- [x] **Step 1: Write failing registry tests**

Test migration creates `dataset_registry` and `dataset_quality_reports`; creating a dataset is idempotent by `(dataset_id, version)`; status updates persist; archived datasets are excluded from `list_active`; invalid schema names are rejected before SQL execution.

- [x] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_dataset_registry.py -q`

Expected: FAIL because the migration and registry implementation do not exist.

- [x] **Step 3: Add migration**

Create `dataset_registry` with dataset ID, name, source type, source reference, schema name, version, status, row count, quality JSON, created/updated timestamps, and a unique constraint on `(dataset_id, version)`. Add indexes on status and dataset ID.

- [x] **Step 4: Implement registry**

Use parameterized SQL for values and a dedicated identifier validator for schema/table names. Serialize Pydantic quality reports as JSON. Wrap create and status transitions in transactions. Allow only legal transitions: uploaded -> profiling/failed, profiling -> needs_mapping/failed, needs_mapping -> ready/failed, ready -> archived.

- [x] **Step 5: Run the focused test**

Run: `python -m pytest tests/test_dataset_registry.py -q`

Expected: PASS against the repository's PostgreSQL test fixture or the existing test doubles.

- [x] **Step 6: Commit**

```bash
git add db/migrations/011_dataset_registry.sql src/retail_analytics_agent/dataset_registry.py tests/test_dataset_registry.py
git commit -m "feat: persist dataset registry and status transitions"
```

### Task 3: Implement CSV and Parquet import into isolated staging schemas

**Files:**
- Create: `src/retail_analytics_agent/data_import.py`
- Modify: `pyproject.toml`
- Test: `tests/test_data_import.py`

**Interfaces:**
- `ImportRequest(dataset_id, version, source_path, source_type, target_schema)`.
- `ImportResult(dataset_id, schema_name, tables, row_counts)`.
- `FileDatasetImporter.import_file(request, connection) -> ImportResult`.
- Later tasks consume `ImportResult` and query only its validated schema.

- [x] **Step 1: Write failing import tests**

Test CSV import creates a normalized table name, preserves row count and basic scalar values, rejects path traversal and unsupported extensions, rejects duplicate column names, and uses a separate schema for a second dataset. Test Parquet import with a small fixture, skipping only when the optional Parquet dependency is unavailable.

- [x] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_data_import.py -q`

Expected: FAIL because importer and dependencies do not exist.

- [x] **Step 3: Add minimal import dependencies**

Add `pandas` and `pyarrow` as an optional dependency group named `data` rather than making them mandatory for the existing API runtime. The importer must provide a clear error when the optional group is not installed.

- [x] **Step 4: Implement safe import**

Resolve the input path, require it to be inside the configured upload root, infer the source type from the declared type and extension, normalize columns to lowercase snake case, reject collisions after normalization, create `staging_<dataset_id>_<version>` with validated identifiers, and load rows using parameterized COPY or batched inserts. Never use the original filename as an SQL identifier.

- [x] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_data_import.py -q`

Expected: PASS, including isolation and invalid-input cases.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/retail_analytics_agent/data_import.py tests/test_data_import.py
git commit -m "feat: import sales files into staging schemas"
```

### Task 4: Add SchemaProfiler and data quality checks

**Files:**
- Create: `src/retail_analytics_agent/schema_profiler.py`
- Test: `tests/test_schema_profiler.py`

**Interfaces:**
- `SchemaProfiler.inspect(schema_name, connection) -> SchemaProfile`
- `SchemaProfiler.quality(schema_name, connection) -> QualityReport`
- `SchemaProfiler._candidate_roles(column_profile) -> tuple[str, ...]` remains deterministic and unit-testable.

- [x] **Step 1: Write failing profiler tests**

Test detection of numeric amount candidates, date candidates, categorical candidates, null and duplicate ratios, sample values, empty tables, and a quality failure for a duplicate key candidate or invalid timestamp range. Test that profiling an unvalidated schema raises a domain error.

- [x] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_schema_profiler.py -q`

Expected: FAIL because the profiler does not exist.

- [x] **Step 3: Implement safe metadata queries**

Query `information_schema.columns`, `pg_stats` where available, and bounded samples from the validated staging schema. Use allowlisted identifiers and bounded limits. Compute ratios in Python from bounded aggregates. Candidate roles must be hints only: amount, time, categorical, identifier.

- [x] **Step 4: Implement quality report**

Check row count, null ratio, duplicate ratio, timestamp parse/range, negative amount count, and candidate key uniqueness. Return issues with stable codes and severity. `passed` is false for malformed schema, zero rows, duplicate normalized columns, or critical data-quality issues.

- [x] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_schema_profiler.py -q`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add src/retail_analytics_agent/schema_profiler.py tests/test_schema_profiler.py
git commit -m "feat: profile staging schemas and report data quality"
```

### Task 5: Add administrator-facing dataset API and readiness guard

**Files:**
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `src/retail_analytics_agent/settings.py`
- Modify: `src/retail_analytics_agent/database.py`
- Test: `tests/test_dataset_api.py`

**Interfaces:**
- `POST /admin/datasets` registers an upload and returns `DatasetRecord`.
- `POST /admin/datasets/{dataset_id}/profile` imports/profiles the selected version and returns `SchemaProfile` plus `QualityReport`.
- `POST /admin/datasets/{dataset_id}/ready` transitions only a quality-passed dataset after mapping confirmation.
- `GET /admin/datasets` lists active datasets for admins only.

- [x] **Step 1: Write failing API tests**

Test analyst receives 403, admin can register a dataset, unsafe file paths receive 422, profiling exposes quality failures without marking the dataset ready, and a ready dataset appears in the active list.

- [x] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_dataset_api.py -q`

Expected: FAIL because routes and request models do not exist.

- [x] **Step 3: Add configuration**

Add an upload root setting with a safe default under the application data directory, a maximum upload size, and allowed extensions `csv` and `parquet`. Validate the root is absolute and the size is positive.

- [x] **Step 4: Implement admin routes**

Reuse existing `get_access_context` and `_require_admin_access`. Store uploads under a generated dataset path, never under the client filename. Register before importing, update status during each phase, and persist the quality report after profiling. Do not expose raw file paths in API responses.

- [x] **Step 5: Add readiness integration**

Update database readiness checks to keep the existing public relation checks unchanged and add a separate dataset readiness query. Do not make an uploaded dataset required for the application to start.

- [x] **Step 6: Run focused tests**

Run: `python -m pytest tests/test_dataset_api.py tests/test_admin_views.py -q`

Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add src/retail_analytics_agent/app.py src/retail_analytics_agent/settings.py src/retail_analytics_agent/database.py tests/test_dataset_api.py
git commit -m "feat: expose admin dataset onboarding workflow"
```

### Task 6: Verify regression and document the onboarding flow

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Create: `docs/DATASET_ONBOARDING.md`
- Test: existing full suite

- [x] **Step 1: Run the focused and full tests**

Run: `python -m pytest tests/test_dataset_models.py tests/test_dataset_registry.py tests/test_data_import.py tests/test_schema_profiler.py tests/test_dataset_api.py -q`

Then run: `python -m pytest -q`

Expected: all focused and existing tests pass.

- [x] **Step 2: Document a reproducible sample flow**

Document a small CSV with orders, products and channels, the generated staging schema, the quality report, the mapping confirmation step and one read-only Agent query. State that the data is demo/public data and that mapping confirmation is required.

- [ ] **Step 3: Verify migration from an empty database**

Run the existing migration and verification commands with the new migration included. Confirm the original public tables and existing analysis tests remain unchanged.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ARCHITECTURE.md docs/DATASET_ONBOARDING.md
git commit -m "docs: document portable sales dataset onboarding"
```
