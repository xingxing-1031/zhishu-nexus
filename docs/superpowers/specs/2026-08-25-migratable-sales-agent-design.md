# 可迁移销售分析 Agent 升级设计

## 目标

将知枢 Nexus 从绑定固定零售种子表的演示系统，升级为面向销售与经营分析的可迁移 Agent 工程原型：对符合接入契约的 PostgreSQL、CSV 和 Parquet 数据，通过数据集隔离、Schema 探查、指标语义映射和受控 Text-to-SQL，复用同一套 Agent 主流程完成分析。

项目二企业知识库 RAG 保持独立，通过 Evidence API 为项目一提供带权限、版本和引用的证据。项目一负责 Agent 编排、销售分析、工具治理和运行控制；项目二负责文档证据治理与检索评测。

## 范围与边界

### 本次范围

- 支持 PostgreSQL 数据源，以及 CSV/Parquet 上传后导入 PostgreSQL staging schema。
- 为每个数据集建立独立的 dataset 元数据、SchemaProfile、质量报告和指标映射版本。
- 采用“确定性规则 + 模型结构化判断 + 代码校验”的混合路由。
- 为复合任务记录子任务依赖、并行条件和完成标准。
- 将 Skill 扩展为带版本、输入、权限、工具、完成条件和拒答条件的能力契约。
- 统一记录 AgentRun、AgentStep、ToolCall、Observation、Verification 和最终回答。
- 对上下文进行分层、预算化和可追踪裁剪。
- 建立覆盖路由、工具、越权、失败、追问和长上下文的 Agent 评测集。

### 明确不做

- 不承诺对任意行业、任意数据格式零配置分析。
- 首期不接 MySQL、Kubernetes、Electron 或 Pi SDK。
- 不允许模型未经确认自动发布指标口径或执行写操作。
- 不把项目二的 RAG 实现复制到项目一；项目一通过 Evidence API 调用项目二。
- 不使用没有原始运行记录支撑的准确率、延迟或成本指标。

## 总体架构

```text
CSV / Parquet / PostgreSQL
        |
        v
Data Source Adapter
        |
        v
Dataset Registry -> Staging Schema -> Schema Profiler -> Quality Report
                                      |
                                      v
                              Metric Semantic Catalog
                                      |
User Request -> Preflight Rules -> Structured Router -> Plan/Skill Validation
                                      |
                                      v
                              Agent Runtime / AgentRun
                                      |
          +---------------------------+---------------------------+
          |                           |                           |
       SQL Tool                  RAG Evidence API             MCP Tools
          |                           |                           |
          +---------------------------+---------------------------+
                                      |
                         Observation / Verification
                                      |
                         Synthesis -> Review -> Answer
                                      |
                         Trace / Audit / Evaluation
```

## 一、数据接入与数据集隔离

### 接入流程

```text
上传或注册数据源
  -> 创建 dataset_id
  -> 保存原始文件和元数据
  -> 解析与数据质量检查
  -> 创建独立 staging schema
  -> 导入 PostgreSQL
  -> 生成 SchemaProfile
  -> 生成指标映射草稿
  -> 管理员确认
  -> 状态变为 ready
```

CSV 和 Parquet 不直接作为在线查询后端。文件先导入 PostgreSQL，在线 Agent 始终通过统一的只读 SQL 接口访问数据。

每个数据集保存：

```text
dataset_id
dataset_name
source_type
source_uri 或文件引用
schema_name
version
status
row_count
quality_report
created_at
```

状态使用：`uploaded`、`profiling`、`needs_mapping`、`ready`、`failed`、`archived`。

每个数据集使用独立 schema，例如：`staging_olist_2026`、`staging_online_retail_2026`。

### 数据源适配器

```python
class DataSourceAdapter(Protocol):
    def connect(self) -> None: ...
    def list_tables(self) -> list[str]: ...
    def describe_schema(self) -> SchemaSnapshot: ...
    def sample_rows(self, table: str, limit: int = 20) -> list[dict[str, object]]: ...
    def profile_data(self, table: str) -> TableQualityProfile: ...
    def execute_readonly_query(self, sql: str, max_rows: int) -> QueryResult: ...
```

首期适配器：`PostgresDataSourceAdapter`、`CsvImportAdapter`、`ParquetImportAdapter`。CSV/Parquet 负责解析和导入，PostgreSQL 负责在线探查和只读查询。

## 二、Schema 探查与数据质量

每张表输出：

```text
table_name, columns, column_types
primary_key_candidates, foreign_key_candidates
time_columns, amount_columns, categorical_columns
null_ratio, unique_ratio, sample_values, relationships
```

系统只生成候选映射，例如 `total_amount -> 可能是销售金额`，不把字段名直接当成业务语义。管理员确认后，映射才进入指标目录。

导入前检查格式、编码、空文件、重复字段和可解析类型；导入后检查行数、重复率、空值率、时间范围、金额范围、主键冲突、关联匹配率和状态冲突。质量不通过的数据集不能进入 `ready`，Agent 不得对其生成正式业务结论。

## 三、指标语义层

每个指标以版本化 `MetricDefinition` 保存：

```text
metric_id, version, name, definition, formula
source_fields, supported_dimensions, fixed_filters
example_sql, effective_from, status
```

首期指标包括销售额、订单数、销量、退款率、客单价、复购率，以及渠道和区域销售额。没有业务定义的字段不能直接被 SQL 生成器作为指标使用。

## 四、混合路由、规划与 Skill

路由采用：

```text
确定性前置规则 -> LLM 结构化路由 -> Pydantic/业务代码校验
                                      -> 低置信度澄清或安全兜底
```

规则处理空问题、危险意图、写操作、越权、身份/时间问题和明显缺失条件。模型负责同义表达、复合问题、追问和子任务拆分。

模型输出包含 `mode`、`confidence`、`subtasks` 和 `missing_information`。代码校验路由值、置信度、子任务数量、依赖是否成环、工具白名单、权限和必要输入。

每个子任务保存：

```text
subtask_id, type, goal, depends_on
parallelizable, required_tools, success_criteria
```

无依赖的知识和数据任务可以并行；依赖数据结果的检索必须串行。顶层总结只消费已验证结果，并列出失败部分。

Skill 升级为版本化能力契约，包含：

```text
skill_id, version, description, trigger_examples
required_inputs, required_tools, allowed_roles
completion_criteria, refusal_conditions, output_schema
```

Skill 路由结果保存置信度、理由和缺失输入。Skill 不能访问未声明的工具，也不能输出未声明的结果结构。

## 五、Agent Runtime、工具与上下文

一次运行统一记录：

```text
Route -> Plan -> Context -> Decision -> ToolCall -> Observation
      -> Verification -> Retry/Recovery/Approval -> Answer
```

每个 AgentStep 保存 `run_id`、`step_id`、`step_type`、`state_before`、`decision`、`tool_call`、`observation`、`state_after`、`status`、`duration_ms`、`token_estimate` 和 `error_type`。

所有 SQL、RAG 和 MCP 工具结果统一保存 `tool_name`、`status`、`payload`、`evidence_ids`、`input_hash`、`result_hash`、`duration_ms` 和 `error_type`。

错误分类：`invalid_arguments`、`timeout`、`permission_denied`、`service_unavailable`、`empty_result`、`invalid_result`。参数错误最多修正一次，超时有限重试，权限拒绝直接拒绝，服务不可用可信降级，空结果明确说明，非法结果不得进入总结。

上下文拆为 `system_context`、`task_context`、`evidence_context`、`tool_context` 和 `conversation_context`，每层记录预算、估算、优先级、裁剪标记和来源 ID。预算不足时优先裁剪旧对话和低价值工具结果，保留权限、当前目标、已确认条件和证据。

## 六、项目二 RAG 边界

项目二继续独立实现：

```text
文档解析 -> 清洗 -> 结构化切分 -> 权限/版本过滤
-> BM25 + 向量 -> RRF -> Reranker
-> 证据覆盖检查 -> 引用回答或可信拒答
```

项目一只通过 Evidence API 获取证据，不复制 RAG 内部实现。项目一 Trace 记录原始问题、查询改写、候选数量、重排结果、证据覆盖率、引用和拒答原因。

## 七、评测设计

项目一首期建立至少 100 条 Agent 评测：20 条正常销售分析、15 条复合问题、15 条模糊问题、15 条工具调用、10 条工具失败、10 条越权和敏感字段、10 条上下文追问、10 条长上下文、5 条拒答。

指标包括：

```text
route_accuracy, skill_accuracy, tool_selection_accuracy
argument_validity, task_success, sql_execution_success
business_result_accuracy, evidence_recall, citation_accuracy
refusal_accuracy, permission_leakage
p50/p95_latency, token_cost
```

development 集用于调优，frozen holdout 只用于最终验收。每次实验保存数据集、Prompt、模型、配置、原始输出、Trace、分项指标和失败样本。

## 八、验收标准

1. 接入第二套销售数据时不重写 Agent 主流程。
2. 上传数据后可以生成 Schema 和数据质量报告。
3. 指标映射经过确认后才能查询。
4. 路由可以处理正常、复合、模糊和追问问题。
5. 工具失败、证据不足和权限不足均有明确降级。
6. 每次运行均可查看 Trace 和最终状态。
7. 路由或 Skill 修改后可以用 frozen holdout 验证泛化。
8. 评测同时检查路由、工具、证据、SQL 和业务结果，而不只看最终文本。

## 实施顺序

1. 数据集注册、CSV/Parquet 导入和 staging schema。
2. SchemaProfile、质量报告和指标映射草稿/确认。
3. 混合 Supervisor、依赖感知计划和 Skill Manifest。
4. AgentRun、Observation 和分层 Context Trace。
5. 跨数据集评测和回归报告。
6. README、演示流程、简历证据和面试材料同步更新。
