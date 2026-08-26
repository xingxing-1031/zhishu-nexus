# 阶段4：在现有 Trace 上补齐可交付证据 实施报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段4
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main）

## 一、本阶段理解与计划

阶段4目标是复用现有 `ExecutionTrace`（不再新建一套重复 Trace 系统），让一次跨数据集分析
可以回答六问：用了哪个数据集、为什么这样路由、计划是什么、调用了什么、哪一步失败、
最终为什么回答或拒答。核心约束是**只记录可交付证据、不在普通 Trace 泄露敏感完整数据**，
并明确 Trace（排障）与审计（责任追溯）的边界。

按 handoff 补充记录逐项落点：

- dataset ID/version/schema（schema 仅管理员可见）→ `scope` 节点 payload + `get_trace` 按角色脱敏
- 路由模式、置信度、原因码、缺失信息 → 企业链路 `supervisor.route` 事件 payload
- AnalysisPlan 校验结果 → `plan` 节点 payload（goal/metrics/dimensions/time_range/limit）
- SQL 安全校验与业务一致性校验 → `validate_sql` / `validate_business_sql` payload
- 查询结果行数、不泄露完整数据 → `execute_sql` payload 只记 `row_count`
- 上下文 token 预算/估算/裁剪 → 企业链路 `agent.context` 事件 payload
- 审批、重试、降级、最终状态 → `assess_risk` / `request_approval` / `summarize` / `fail` payload

复用机制：`ExecutionTraceEvent` 新增可选 `payload JSONB`，`trace_workflow_node` 成功路径
统一附加 `_node_evidence` 提取的节点证据；审批中断（`GraphInterrupt`）附加
`approval_requested` 标记。企业 Agent 链路通过注入 `trace_store` 复用同一张表。

## 二、实际修改文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/retail_analytics_agent/tracing.py` | 修改 | `ExecutionTraceEvent` 加 `payload: dict\|None`；`TRACE_INSERT_SQL`/`TRACE_SELECT_SQL` 加 `payload` 列；`record_execution_trace` 加 `payload` 参数 |
| `db/migrations/014_trace_payload.sql` | **新增** | `ALTER TABLE analysis_trace_events ADD COLUMN payload JSONB;` |
| `src/retail_analytics_agent/workflow.py` | 修改 | 新增 `_node_evidence(node_name, state, update)`，为 scope/plan/retrieve/generate_sql/validate_sql/validate_business_sql/assess_risk/request_approval/execute_sql/summarize/fail 各节点提取交付证据；`trace_workflow_node` 成功路径与审批中断路径附 payload |
| `src/retail_analytics_agent/analysis_service.py` | 修改 | 新增 `_sanitize_trace_events`；`get_trace` 对非 ADMIN viewer 把 `dataset_schema` 置 None |
| `src/retail_analytics_agent/zhishu_service.py` | 修改 | `ZhishuAgentService` 加 `trace_store` 字段；`_prepare` 后新增 `_record_trace_evidence`，在 `execution_trace_context` 内记录 `supervisor.route`（路由模式/置信度/原因码/缺失信息/refused/agents/数据集身份）与 `agent.context`（token 预算/估算/裁剪）；新增 `_routing_evidence` |
| `src/retail_analytics_agent/app.py` | 修改 | `get_agent_service` 构造 `ZhishuAgentService` 时注入 `trace_store=getattr(runner, "trace_store", None)` |
| `compose.yaml` | 修改 | postgres initdb 挂载新增 `014_trace_payload.sql` |
| `tests/test_migrate.py` | 修改 | 最新迁移断言从 013 更新为 014 |
| `tests/test_trace_payload.py` | **新增** | 16 个阶段4测试（见下） |

## 三、为什么按这种方式实现

- **复用现有 Trace 而非新建系统**：`payload` 只是给既有 `ExecutionTraceEvent` 加一个可选
  JSON 列，`record_execution_trace` 调用点全部兼容；分析链路（workflow）与企业 Agent 链路
  （zhishu_service）共用同一 store/表，不重复造轮子。
- **证据在统一包装器 `trace_workflow_node` 提取**：所有节点都已通过该包装器记录 trace，
  只需在其中补 `_node_evidence`，无需改动 11 个节点函数本身；`state`（输入）与 `update`
  （输出）都可取，能覆盖每个节点的关键证据。
- **只记行数与摘要、不记敏感明细**：`execute_sql` 只记 `row_count`，不落完整行；
  `validate_sql` 只记表名与 result_limit，不落完整 SQL（完整 SQL 已由审计表负责）；
  `summarize` 记回答长度而非全文；审批中断只记标记，审批内容走既有审批审计。
- **schema 脱敏在读取端而非写入端**：写入时完整记录 `dataset_schema`（排障需要），
  `get_trace` 在返回前按 viewer 角色清洗，admin 保留、analyst 置 None——避免普通分析员
  看到 schema 名称，同时不影响排障。
- **路由证据进 Trace 而非业务审计**：`supervisor.route` 记录路由决策（模式/置信度/原因码/
  缺失信息），属于内部执行链路排障证据；写操作/越权/审批等安全事件仍走既有审计与审批表，
  不把普通聊天内容写入业务审计（符合阶段4的 Trace 与审计边界）。
- **context 快照复用现有 `_context_snapshot`**：token_budget/estimate/truncated 已在企业
  链路维护，直接作为 `agent.context` 的 payload，回答"上下文为什么被裁剪"。

## 四、新增/修改的测试

新增 `tests/test_trace_payload.py` 16 个：

- Trace payload 字段：事件可携带 payload、payload 可选、`model_dump(mode="json")` 可序列化。
- workflow 节点证据：plan（goal/metrics/dimensions/limit）、scope（dataset_id/version/schema/
  name/metric_count）、scope 无数据集时不带 schema、validate_sql（sql_valid/tables/result_limit）、
  execute_sql（row_count）、summarize（status/answer_chars）、summarize 降级（degradation_reason）、
  fail（failure_reason）。
- 脱敏：analyst 读 trace 时 `dataset_schema` 置 None、其余字段保留；admin 完整保留。
- 企业链路证据：knowledge 请求记录 `supervisor.route`（mode/reason_code/confidence/agents）与
  `agent.context`（token_budget/token_estimate/truncated）；写操作拒绝记录 REJECTED 路由；模糊请求
  记录 PENDING 路由与 missing_information；数据请求把 dataset_id/version 透传进路由 payload。

修改 `tests/test_migrate.py`：最新迁移断言更新为 `014_trace_payload.sql`（配合 compose 挂载）。

## 五、完整测试命令和真实输出

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
.\.venv\Scripts\python.exe -m pytest tests\test_trace_payload.py -q
# 16 passed

.\.venv\Scripts\python.exe -m pytest
# 659 passed in 9.37s
```

完整全量输出：`659 passed in 9.37s`（阶段3为 643，新增 16），无 failed/error/skipped。

## 六、已知边界和未完成项

- `_node_evidence` 只覆盖 workflow 节点与两个企业链路事件；数据链路内工具级（`sql.query`、
  `knowledge.search`）的输入 hash/耗时已在 `ToolCallRecord`/审计记录，未再复制进 Trace，避免
  重复。
- mapping version / metric source IDs 只记录了 `metric_count`（已确认指标数），未逐条记录
  metric 的 source_id 明细；如需逐条可在后续阶段扩展 scope payload。
- 普通聊天内容不写入业务审计（沿用既有边界）；审批、写操作拒绝、越权等安全事件仍走既有
  `query_approval_logs` 与审计链路，阶段4未改动该边界。
- 脱敏目前只清洗 `dataset_schema` 一个字段；若未来其他 payload 字段被判定敏感需同步在
  `_sanitize_trace_events` 中登记。
- `payload` 为 JSONB，跨节点写入均为 JSON 安全的标量/列表/字典，无自定义对象直存。
- 新迁移只影响既有 `analysis_trace_events` 表加列，老数据 `payload` 为 NULL，读取兼容。

## 七、git diff --stat 与 git status --short

```
compose.yaml                                   |   1 +
src/retail_analytics_agent/analysis_service.py |  24 ++++-
src/retail_analytics_agent/app.py              |   1 +
src/retail_analytics_agent/tracing.py          |  14 ++-
src/retail_analytics_agent/workflow.py         | 128 +++++++++++++++++++++++++
src/retail_analytics_agent/zhishu_service.py   |  50 ++++++++++
tests/test_migrate.py                          |   2 +-
7 files changed, 214 insertions(+), 6 deletions(-)
```

`git status --short`：

```
 M compose.yaml
 M src/retail_analytics_agent/analysis_service.py
 M src/retail_analytics_agent/app.py
 M src/retail_analytics_agent/tracing.py
 M src/retail_analytics_agent/workflow.py
 M src/retail_analytics_agent/zhishu_service.py
 M tests/test_migrate.py
?? db/migrations/014_trace_payload.sql
?? docs/CLAUDE_UPGRADE_HANDOFF.md
?? tests/test_trace_payload.py
```
