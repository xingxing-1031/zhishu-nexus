# 阶段1：数据集级指标语义层 实施报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段1
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main，HEAD 7ad1703）

## 一、本阶段理解与计划

把已确认的 `DatasetMapping`（字段角色映射）升级为可供 Agent 使用的、版本化的销售指标定义。
只发布能被明确验证的指标；退款率、复购率等需要额外状态或客户定义的指标不自动发布。
指标引用只能落在已确认映射的字段上，版本不可静默覆盖，未确认指标不可用于分析计划。

按计划实施：模型层（`DatasetMetric` + propose/validate/版本）→ 持久化（migration 013 +
registry）→ 管理确认 API → 测试 → 空库全量迁移验证。

## 二、实际修改文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/retail_analytics_agent/metric_models.py` | **新增** | 数据集级指标模型 `DatasetMetric`、`MetricStatus`；`propose_metrics`、`validate_metrics`、`with_latest_version`、`as_confirmed`、`has_confirmed_metric`；稳定 `source_id` |
| `db/migrations/013_dataset_metric_versions.sql` | **新增** | `dataset_metric_versions` 表：`(dataset_id, dataset_version, metric_id, metric_version)` 主键、status/aggregation/version 约束、`supported_dimensions`/`fixed_filters` JSONB 数组校验、查询索引 |
| `src/retail_analytics_agent/dataset_registry.py` | 修改 | 新增 `save_metric` / `list_metrics` / `confirm_metric`；`DatasetMetricNotFoundError`；`_metric_params` / `_metric_from_row`（过滤表内审计时间列） |
| `src/retail_analytics_agent/app.py` | 修改 | 新增 `POST /admin/datasets/{id}/metrics/proposals`（生成并保存建议）、`POST /admin/datasets/{id}/metrics/confirm`（确认指标，确认人取当前登录用户）；`MetricProposalsResponse` / `MetricConfirmRequest` |
| `compose.yaml` | 修改 | postgres initdb 挂载 013 迁移（+1 行） |
| `tests/test_dataset_metrics.py` | **新增** | 11 个测试（见下） |
| `tests/test_migrate.py` | 修改 | 最新迁移断言 012 → 013 |

## 三、为什么按这种方式实现

- **propose 从确认映射推导而非从字段名推断**：`propose_metrics` 只消费 `DatasetMapping.fields`
  中的角色（AMOUNT/ORDER_ID/QUANTITY + 维度），生成的 `formula` 直接引用映射后的表列；
  两套不同字段名（`total_amount` vs `revenue`）经同一角色映射得到同一 `metric_id=sales_amount`、
  各自正确的 SQL。维度（渠道/区域/品类）只有映射中存在时才开放，与现有
  `knowledge.py` 固定指标目录"单指标 + supported_dimensions"的模式保持一致。
- **validate 是独立防线**：指标引用的列必须在映射中存在且 `_role_compatible` 类型兼容，
  维度必须在映射中，`metric_id` 不允许重复——防止 API 层直接手写任意指标绕过映射。
- **版本 append-only**：`with_latest_version` 对已存在的 `metric_id` 自动 `v(N+1)`，
  确认只做状态流转（`as_confirmed`），不改 definition/formula；`source_id` =
  `metric.<dataset>.<version>.<metric_id>.<metric_version>` 稳定，供 Trace/回答引用。
- **持久化沿用仓库现有 JSONB + 参数化 SQL 模式**：指标存独立表而非塞进 `dataset_registry`
  单行，版本化清晰；`_metric_from_row` 显式过滤 `created_at/updated_at`，避免 `extra="forbid"`
  拒绝审计列。

## 四、新增/修改的测试

`tests/test_dataset_metrics.py` 覆盖交接文件 5 条必测：

1. 两套不同字段名映射到同一销售额指标（`SUM(dataset_rows.total_amount)` vs
   `SUM(dataset_rows.revenue)`），维度 `{"channel"}` 正确开放。
2. 缺少 `order_id` 时不生成 `order_count` 与 `avg_order_value`。
3. 不兼容列类型被 `validate_metrics` 拒绝（`MetricValidationError`）。
4. 未确认指标 `status=proposed`、`has_confirmed_metric=False`；`as_confirmed` 后
   `status=confirmed`、`confirmed_by` 写入。
5. 版本 bump `v1→v2` 且 `source_id` 稳定不变；确认不改 `source_id`。

另含：migration 013 表结构断言；registry `save_metric` / `confirm_metric` 持久化与
确认幂等（已 confirmed 不重复更新）/ 指标不存在报错（Mock 连接，风格对齐
`test_dataset_registry.py`）。`tests/test_migrate.py` 最新迁移断言 012→013。

## 五、完整测试命令与真实输出

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_dataset_metrics.py -q      # 11 passed
.\.venv\Scripts\python.exe -m pytest tests/test_dataset_api.py tests/test_dataset_registry.py \
    tests/test_dataset_models.py tests/test_dataset_mapping.py tests/test_data_import.py \
    tests/test_schema_profiler.py tests/test_dataset_metrics.py -q         # 41 passed
.\.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_dataset_api.py -q  # 48 passed
.\.venv\Scripts\python.exe -m pytest -q                                     # 597 collected, 全绿
```

全量 597 用例通过（新增 11 个指标测试）。

### 空库全量迁移（含 013，独立容器重建）

阶段0独立容器 `zhn-phase0-pg` / 卷 `zhn-phase0_data` 已重建为全新空库（该卷为阶段0
独立验证资源，非项目数据卷；重建未触碰任何项目卷）。`POSTGRES_PORT=5544` 执行：

```text
applied=15 skipped=0
applied: 001_initial_schema.sql ... 012_dataset_mapping.sql
applied: 013_dataset_metric_versions.sql
applied: seed:001_demo_data.sql
applied: seed:002_richer_demo_dataset.sql
```

幂等复跑：`applied=0 skipped=15`。

表结构：`dataset_metric_versions` 19 列（含 `dataset_id/dataset_version/metric_id/
metric_version/.../status/effective_from/confirmed_by/confirmed_at/created_at/updated_at`）。

原交付校验 `verify_delivery.sql`：`W6-3 delivery database verification passed`。
独立容器与卷保留供后续阶段复用，清理命令：`docker rm -f zhn-phase0-pg && docker volume rm zhn-phase0_data`。

## 六、已知边界与未完成项

- **AnalysisPlan/SQL 生成尚未消费指标**：`validate_metrics` 已保证"未确认指标不可用"
  的模型层防线（`status=proposed` + `has_confirmed_metric`），但 AnalysisPlan、Schema 检索、
  SQL 生成的数据集感知与"未确认指标拒绝进入计划"的接线属阶段2。
- **指标仅支持已验证口径**：首期 5 类（销售额/订单数/销量/客单价/维度销售额）；退款率、
  复购率等需额外状态或客户定义，未自动发布（符合交接文件边界）。
- **管理界面未做**：proposals/confirm 是 HTTP API；管理员界面上传/映射/指标确认闭环属阶段6。
- **空库全量迁移已验证含 013**：此前交接文件"尚未完成"项中"从全新空 PostgreSQL 验证所有
  迁移（包括 011、012）"现已完成（含 013）。
- 交接文件 `docs/CLAUDE_UPGRADE_HANDOFF.md` 仍未提交 git（保持未跟踪，待用户决定）。

## 七、git 状态

```text
 M compose.yaml
 M src/retail_analytics_agent/app.py
 M src/retail_analytics_agent/dataset_registry.py
 M tests/test_migrate.py
?? db/migrations/013_dataset_metric_versions.sql
?? docs/CLAUDE_UPGRADE_HANDOFF.md
?? src/retail_analytics_agent/metric_models.py
?? tests/test_dataset_metrics.py
```

`git diff --stat`：4 文件 +239/-1（compose +1、app +82、registry +155、test_migrate 2-1）；
另 4 个新文件未跟踪（不在 diff --stat）。

**未提交、未 push。** 按交接文件工程约束，提交前先向用户报告并确认。

## 八、下一步

等待用户确认本阶段结果后：提交阶段1改动 → 进入阶段2（让 Agent 主分析链路真正感知数据集）。
