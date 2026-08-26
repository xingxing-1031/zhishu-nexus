# 阶段2：让 Agent 主分析链路真正感知数据集 实施报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段2
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main，HEAD c668eef）

## 一、本阶段理解与计划

分析请求携带 `dataset_id` / `dataset_version` 后，服务端根据数据集元数据解析出
`DatasetScope`（指标目录、schema 目录、允许列、维度/筛选项、时间列），并让该 scope
贯穿计划 → 目录检索 → SQL 生成 → SQLGlot 安全校验 → 业务一致性校验 → 执行 → 总结
全链路。SQL 只能访问当前选中数据集的 staging schema；跨数据集 schema、跨数据集列、
未确认映射、非 ready 数据集、不存在数据集一律拒绝并写安全审计；固定 public 演示数据
不回归。

按计划实施：请求模型加字段 → `DatasetScope` 解析层 → SQL 安全/业务校验接受
`allowed_schema`/scope → 工作流 scope 节点 + checkpoint → 服务端注入 resolver →
public demo 限制 → 跨数据集核心测试 → 全量回归。

## 二、实际修改文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/retail_analytics_agent/models.py` | 修改 | `AnalysisRequest` 新增 `dataset_id`（1-80）/`dataset_version`（≥1）；`AnalysisDimension` 新增 `REGION="region"` |
| `src/retail_analytics_agent/dataset_scope.py` | **新增** | `DatasetScope`（pydantic frozen，含 metric/schema catalog、allowed_columns、dimension/filter/time 列）、`resolve_dataset_scope`（确认指标 + 确认映射 → scope）、`DatasetScopeResolver`（registry + profiler → scope，抛出稳定 reason_code）、`DatasetScopeRejectionError` |
| `src/retail_analytics_agent/sql_safety.py` | 修改 | `prepare_safe_sql` 支持 `allowed_schema`；`_validate_tables` 用 `accepted_schemas`；`_validate_columns`/`_collect_referenced_columns` 接收 allowed_columns 映射 |
| `src/retail_analytics_agent/query_service.py` | 修改 | `prepare_audited_sql` 透传 `allowed_columns`/`allowed_schema` |
| `src/retail_analytics_agent/sql_consistency.py` | 修改 | `validate_sql_against_evidence` 支持 `scope`：使用 scope 的 metric/schema catalog、filter 列、time 列、维度列；`_dataset_metric_matches` 解析公式结构；`_definitions_for_plan` 兼容 3/5 段 source_id |
| `src/retail_analytics_agent/model_adapters.py` | 修改 | `_sql_generation_contract` 支持 `scope`（schema 前缀表引用、scope 目录、scope 时间列/维度/筛选列）；`_dimension_sql_expression` scope 分支；`SQLGenerator`/`ResultSummarizer` 新增 `scope`/`dataset_name` 参数；summarize 回答开头指出统计来自该数据集 |
| `src/retail_analytics_agent/workflow_tools.py` | 修改 | `CatalogRetrievalTool`/`SQLGlotValidationTool`/`SQLConsistencyValidationTool` 接收 `scope`；`_scope_column_tables` 辅助 |
| `src/retail_analytics_agent/workflow.py` | 修改 | `AnalysisState` 新增 dataset 字段；`create_domain_scope_node` 在数据集请求时走 `_resolve_dataset_scope`（拒绝时写 `QueryAuditRecord(status=REJECTED)` 安全审计）；retrieve/generate_sql/validate_sql/validate_business_sql/summarize 透传 scope/dataset_name；`create_workflow_nodes` 注入 `dataset_resolver`/`dataset_audit_sink` |
| `src/retail_analytics_agent/checkpointing.py` | 修改 | `_CHECKPOINT_TYPES` 注册 `DatasetScope` 及其嵌套 catalog 类型，供 JsonPlusSerializer 反序列化 |
| `src/retail_analytics_agent/request_registry.py` | 修改 | `request_fingerprint` 加入 dataset 字段，数据集请求之间互不冲突 |
| `src/retail_analytics_agent/analysis_service.py` | 修改 | `get_analysis_runner` 注入 `DatasetScopeResolver`；`_PUBLIC_REJECTION_MESSAGES` 新增 6 个 dataset 拒答消息 |
| `src/retail_analytics_agent/app.py` | 修改 | `_enforce_public_demo_request` 在 public demo 下拒绝带 `dataset_id` 的请求 |
| `tests/test_dataset_scope.py` | **新增** | 21 个跨数据集核心测试（见下） |
| `tests/test_workflow_tools.py` 等 3 个 | 修改 | 同步补充 `scope`/`dataset_name`/`region` 接口断言 |

## 三、为什么按这种方式实现

- **scope 贯穿但不重写链路**：所有 SQL/catalog 契约增加可选 `scope` 参数，scope 为 None
  时完全走原固定 public demo 路径——这是"不重写现有架构"与"数据集感知"的最小耦合点。
- **服务端解析，模型不能自选 schema**：scope 在工作流 scope 节点内由注入的
  `DatasetScopeResolver`（registry + schema profiler）解析，拒绝原因用稳定 `reason_code`
  （`dataset_not_found`/`dataset_archived`/`dataset_not_ready`/`dataset_mapping_unconfirmed`/
  `dataset_no_metrics`/`dataset_unavailable`），并转为可读中文拒答。
- **安全审计在拒绝时就写入**：dataset 拒绝在 scope 节点写 `QueryAuditRecord(status=REJECTED,
  original_sql="")`；SQL 层越权（跨 schema/跨列）由 `prepare_audited_sql` 审计。权限边界
  满足"无数据集权限拒绝 + 安全审计"要求。
- **SQL 隔离双层强制**：`sql_safety._validate_tables` 用 `allowed_schema`（只允许当前
  staging schema）；`_validate_columns` 用 `allowed_columns`（只允许当前数据集的映射列）；
  `sql_consistency` 再按当前 scope 的指标公式、维度列、时间列做业务一致性校验。
- **checkpoint 可恢复**：`DatasetScope` 是 pydantic 模型，注册进 JsonPlusSerializer
  allowed 模块，审批中断/续跑不会丢数据集身份。
- **fingerprint 包含 dataset**：同一 `request_id` 绑定不同数据集输入时判为冲突，避免幂等
  误命中。

## 四、新增/修改的测试

新增 `tests/test_dataset_scope.py` 21 个：

- 跨数据集同一指标语义：A（total_amount/sales_channel）vs B（revenue/source）解析到同一
  `SALES_AMOUNT`，各自 source_columns/维度列/时间列/schema 正确且互不泄漏。
- 拒绝路径：映射未确认、无确认指标、指标 id 不在支持范围。
- `DatasetScopeResolver`：dataset 不存在 / archived / not_ready / 映射未确认。
- SQL 隔离：自己数据集 SQL 通过；引用 B 的 schema 被 `prepare_safe_sql` 和
  `SQLGlotValidationTool` 拒绝；自己 schema 内引用 B 的列被拒。
- 目录检索与 SQL 生成契约：A 的 evidence/contract 不含 B 字段，`required_tables` 用各自
  schema 前缀，`required_group_by` 用各自维度列。
- workflow scope 节点：拒绝时写 `QueryAuditRecord(REJECTED)`；接受时写
  `dataset_scope`/`dataset_name`/`dataset_schema`；无 resolver 时 `dataset_unavailable`。
- 端到端（Mock 模型）：dataset 请求 → scope 传入 retrieve/generate/validate/summarize。
- 拒答消息覆盖 + public demo 拒绝 dataset 请求、无 dataset 请求不受影响。

同步更新：`tests/test_workflow_tools.py`（retrieve/validate 的 `scope=None`、stub 签名）、
`tests/test_workflow_model_nodes.py`（generate 的 `scope=None`、summarize 的 `dataset_name=None`）、
`tests/test_model_adapters.py`（planner contract `supported_dimensions` 增加 `region`）。

## 五、完整测试命令和真实输出

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
.\.venv\Scripts\python.exe -m pytest tests\test_dataset_scope.py -q
# 21 passed

.\.venv\Scripts\python.exe -m pytest -q
# 618 passed in 9.13s
```

完整全量输出：`618 passed in 9.13s`，无 failed/error/skipped。

## 六、已知边界和未完成项

- 数据集权限当前以"存在 + READY + 映射/指标已确认"为准，尚无独立 ACL；跨数据集越权由 SQL
  层强制拒绝（`allowed_schema`/`allowed_columns`）。独立的"用户→数据集"授权需后续接入。
- 最终回答已带 `dataset_name`；数据集版本、指标口径、数据来源的完整可交付证据在阶段4
  Trace 中补充。
- 分析员前端选择数据集的入口属阶段6；跨数据集真实评测（两套真实销售数据）属阶段5。
- `AnalysisDimension.REGION` 已加入规划契约；public demo 固定指标目录未开放 region 维度，
  仅数据集映射支持时可用。

## 七、git diff --stat 与 git status --short

```
14 files changed, 411 insertions(+), 68 deletions(-)
```

`git status --short`：

```
 M src/retail_analytics_agent/analysis_service.py
 M src/retail_analytics_agent/app.py
 M src/retail_analytics_agent/checkpointing.py
 M src/retail_analytics_agent/model_adapters.py
 M src/retail_analytics_agent/models.py
 M src/retail_analytics_agent/query_service.py
 M src/retail_analytics_agent/request_registry.py
 M src/retail_analytics_agent/sql_consistency.py
 M src/retail_analytics_agent/sql_safety.py
 M src/retail_analytics_agent/workflow.py
 M src/retail_analytics_agent/workflow_tools.py
 M tests/test_model_adapters.py
 M tests/test_workflow_model_nodes.py
 M tests/test_workflow_tools.py
?? src/retail_analytics_agent/dataset_scope.py
?? tests/test_dataset_scope.py
```
