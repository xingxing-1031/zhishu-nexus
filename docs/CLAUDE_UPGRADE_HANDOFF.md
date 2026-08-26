# 知枢 Nexus 下一阶段升级交接文件（供 Claude 执行）

> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`
>
> 核心目标：把项目从“固定零售种子表上的 Agent 演示”升级为“接入符合契约的销售数据后，可以复用同一套受控分析流程”的工程原型。
>
> 执行原则：先读代码和现有设计，再逐阶段实现。不要重新设计品牌，不要重写现有架构，不要添加与目标无关的热点技术。

## 一、Claude 开始前必须阅读

先完整阅读以下文件：

1. `docs/superpowers/specs/2026-08-25-migratable-sales-agent-design.md`
2. `docs/superpowers/plans/2026-08-25-sales-data-onboarding.md`
3. `docs/DATASET_ONBOARDING.md`
4. `docs/ARCHITECTURE.md`
5. `docs/PROJECT_SCOPE.md`
6. `docs/EVALUATION_PROTOCOL.md`
7. `README.md`

再重点阅读这些实现：

- `src/retail_analytics_agent/dataset_models.py`
- `src/retail_analytics_agent/dataset_registry.py`
- `src/retail_analytics_agent/data_import.py`
- `src/retail_analytics_agent/schema_profiler.py`
- `src/retail_analytics_agent/dataset_mapping.py`
- `src/retail_analytics_agent/models.py`
- `src/retail_analytics_agent/catalog.py`
- `src/retail_analytics_agent/analysis_service.py`
- `src/retail_analytics_agent/workflow.py`
- `src/retail_analytics_agent/sql_safety.py`
- `src/retail_analytics_agent/sql_business_validation.py`
- `src/retail_analytics_agent/execution_trace.py`
- `src/retail_analytics_agent/app.py`

## 二、当前真实状态

### 已完成

- CSV/Parquet 文件注册与安全上传。
- 每个数据集版本进入独立 `staging_<dataset_id>_<version>` schema。
- `DatasetRegistry`、状态流转和质量报告持久化。
- `SchemaProfile` 和 `QualityReport`。
- 确定性字段角色候选：金额、时间、标识、分类等。
- 管理员编辑并确认 `DatasetMapping`。
- 未确认映射的数据集不能进入 `ready`。
- 原有固定零售数据分析、RAG Evidence API、MCP、审批、SSE、幂等、Checkpoint、Trace 和审计仍保留。
- 当前仓库工作树干净。
- 2026-08-26 使用 `.venv\Scripts\python.exe -m pytest -q` 验证，完整测试通过。

### 尚未完成

最关键的缺口是：

> 数据集虽然可以导入、探查、确认映射并进入 `ready`，但 Agent 主分析链路仍主要依赖固定的 `public.orders`、`order_items`、`products`、`refunds` 和固定指标目录。

也就是说，数据接入前半段已完成，但“换一份销售数据仍然复用同一套 Agent 分析”还没有形成真正闭环。

另外尚未完成：

- 从全新空 PostgreSQL 验证所有迁移（包括 011、012）。
- 数据集级指标语义定义和版本管理。
- `AnalysisPlan`、Schema 检索、SQL 生成与校验的数据集感知。
- 两套字段命名不同的销售数据跨数据集回归。
- 新一轮未消费 frozen holdout。
- 管理页面中的数据集接入、映射确认和选择闭环。

## 三、总验收目标

最终必须能现场演示以下流程：

```text
管理员上传销售 CSV/Parquet
-> 系统创建隔离 staging schema
-> 输出字段画像和数据质量报告
-> 生成字段映射草稿
-> 管理员确认业务字段和指标口径
-> 数据集进入 ready
-> 分析员选择该数据集并自然语言提问
-> Agent 生成结构化 AnalysisPlan
-> 基于该数据集的 Schema/Metric Catalog 生成 SQL
-> SQLGlot AST + 数据集范围 + 业务口径校验
-> 只读执行
-> 返回分析结果、口径、数据来源、Trace 和失败边界
```

同时接入第二套字段名明显不同的销售数据时：

- 不修改 Agent 主工作流代码；
- 只进行接入、探查和映射确认；
- 同一类销售问题仍可分析；
- SQL 只能访问当前选中的 ready 数据集；
- 结果可以追溯到数据集、版本、指标定义和 SQL。

## 四、实施阶段

一次只执行一个阶段。每个阶段完成后先运行测试、总结改动，再等待下一步，不要一次生成全部代码。

---

## 阶段 0：补齐数据库迁移基线

### 目标

确认迁移 011、012 可以在全新空数据库执行，并且不会破坏原有 public 表、种子数据和验收脚本。

### 要做

1. 使用独立 Compose 项目名、独立端口和新数据卷启动空 PostgreSQL。
2. 执行全部迁移和种子文件。
3. 运行现有数据库 verification SQL。
4. 检查 `dataset_registry`、质量报告和 dataset mapping 表/字段存在。
5. 检查重复执行迁移的行为符合仓库现有迁移约定。
6. 不得删除用户当前数据库卷，不运行 `docker compose down -v` 作用于现有项目。

### 验收

- 空库迁移命令退出码为 0。
- 原有数据库 verification 全部通过。
- 新增数据集表结构存在且约束正确。
- 保存完整命令和关键输出到交接报告。

如果 Docker 未运行，明确记录为环境阻塞，不要伪造通过结论，然后继续做不依赖数据库容器的任务。

---

## 阶段 1：数据集级指标语义层

### 目标

把已确认的字段角色映射升级为可供 Agent 使用的、版本化的销售指标定义。

### 建议模型

新增或扩展数据集级指标模型，至少包含：

```text
dataset_id
dataset_version
metric_id
metric_version
name
definition
formula / aggregation
source_role 或 source_column
supported_dimensions
fixed_filters
effective_from
status
confirmed_by
confirmed_at
```

首期只支持能被明确验证的指标，不要承诺自动推断所有业务口径：

- 销售额：`SUM(amount)`
- 订单数：存在 `order_id` 时 `COUNT(DISTINCT order_id)`
- 销量：存在 `quantity` 时 `SUM(quantity)`
- 平均订单金额：同时存在 `amount` 和 `order_id` 时计算
- 渠道/区域/品类销售额：对应维度存在时开放

退款率、复购率等需要额外状态或客户定义的指标，字段不足或口径未确认时不能自动发布。

### 必须满足

- 指标只能引用当前确认映射中存在且类型兼容的字段。
- 指标定义需要管理员确认，模型建议不能直接生效。
- 指标版本不可静默覆盖；新定义创建新版本。
- ready 数据集至少拥有一个可查询指标。
- 指标定义可以被 Trace 和最终回答引用稳定 source ID。

### 测试

- 两套不同字段名映射到同一销售额指标。
- 缺少 `order_id` 时不生成订单数和客单价。
- 不兼容字段类型被拒绝。
- 未确认指标不能用于 AnalysisPlan。
- 指标版本和 source ID 稳定。

---

## 阶段 2：让 Agent 主分析链路真正感知数据集

### 目标

分析员选择一个 ready 数据集后，现有结构化计划、目录检索、SQL 生成、安全校验、执行和总结都针对该数据集工作。

### 要做

1. 为分析请求增加明确的 `dataset_id` 和 `dataset_version`，保持原固定演示数据的兼容默认值。
2. 由服务端根据用户权限解析数据集，不允许模型自己决定任意 schema。
3. `AnalysisState` 和 Checkpoint 保存数据集身份、映射版本和指标版本。
4. 目录检索只返回当前数据集的 SchemaProfile、映射和已确认指标。
5. SQL 生成只能使用当前 staging schema 中映射允许的表和列。
6. SQLGlot 校验除只读安全外，还必须校验：
   - 只能访问当前数据集 schema；
   - 只能访问允许表和字段；
   - 不允许跨 dataset JOIN；
   - 指标公式和维度符合当前指标定义；
   - 最大行数和时间预算仍受限制。
7. 最终回答展示数据集名、版本、指标口径和数据来源。
8. 数据集非 ready、映射未确认、指标不存在或字段含义不清时，返回可理解的澄清/拒答，不生成猜测 SQL。

### 核心跨数据集测试

准备两个小型 fixture：

```text
数据集 A：order_id, total_amount, sales_channel, ordered_at
数据集 B：txn_no, revenue, source, transaction_date
```

二者通过不同映射得到相同业务角色。同一个问题，例如“按渠道统计本月销售额”，应复用同一个 AnalysisPlan 语义，但生成各自正确的 SQL 字段。

还要测试：

- A 的请求绝不能访问 B 的 schema。
- dataset_id 不存在、archived 或 needs_mapping 时拒绝。
- 用户无数据集权限时拒绝并写安全审计。
- 固定 public 演示数据原有测试不回归。

### 这是整个升级最重要的阶段

在这个阶段验收之前，不要继续添加新 Agent、知识图谱、微服务或消息队列。

---

## 阶段 3：路由、规划和 Skill 契约补强

### 目标

让系统处理清晰问题、模糊问题、追问和复合任务时有可解释的结构化决策，而不是只靠关键词或只靠模型自由判断。

### 路由设计

保留现有四类顶层模式，采用：

```text
确定性前置规则
-> LLM 结构化路由
-> Pydantic + 业务代码校验
-> 低置信度澄清或安全兜底
```

结构化结果至少包含：

```text
mode
confidence
subtasks
missing_information
reason_code
```

### 规则负责

- 空问题和明显非法输入。
- 写操作、越权和敏感字段前置拦截。
- 明确的系统身份、时间等确定性请求。
- 当前数据集不存在或未 ready。

### 模型负责

- 同义表达和语义意图。
- 复合问题拆解。
- 追问中的省略条件理解。
- 缺失业务条件识别。

### 代码负责

- 枚举、Schema 和置信度校验。
- 子任务数量、依赖环和工具白名单。
- 用户权限、数据集权限和必要输入。
- 低置信度时提出具体澄清问题。

### Skill

不要把 Skill 只做成 Prompt 文本。复用或升级现有 Skill 结构，使其包含：

```text
skill_id/version
required_inputs
allowed_roles
required_tools
completion_criteria
refusal_conditions
output_schema
```

首期只升级销售分析相关 Skill，避免一次重构所有能力。

---

## 阶段 4：在现有 Trace 上补齐可交付证据

### 目标

复用现有 `ExecutionTrace`，不要再新建一套重复 Trace 系统。让一次跨数据集分析可以回答：用了哪个数据集、为什么这样路由、计划是什么、调用了什么、哪一步失败、最终为什么回答或拒答。

### 补充记录

- dataset ID/version/schema（schema 仅管理员 Trace 可见时需脱敏控制）。
- mapping version、metric source IDs。
- 路由模式、置信度、原因码和缺失信息。
- AnalysisPlan 校验结果。
- SQL 安全校验和业务一致性校验结果。
- 工具名、参数摘要、输入/结果 hash、耗时和错误类型。
- 查询结果行数，不在普通 Trace 泄露敏感完整数据。
- 上下文各层 token 预算、实际估算、裁剪来源。
- 审批、重试、降级和最终状态。

### Trace 与审计边界

- Trace：开发排障，记录内部执行链路。
- 审计：安全和责任追溯，记录谁在何时访问什么数据、触发什么高风险动作、是否审批。
- 不要把所有普通聊天内容写入业务审计。
- 企业数据访问、安全拒绝和审批必须进入审计。

---

## 阶段 5：跨数据集真实评测

### 目标

用至少两套字段和分布不同的销售数据，证明迁移能力来自接入契约和语义映射，而不是针对一张固定表写死。

### 数据要求

- 优先使用可公开、可注明来源的销售数据，或明确标注为受控合成数据。
- 不使用来源不明或包含个人敏感信息的数据。
- 至少两套数据的列名、日期范围、渠道/地区值和缺失情况不同。
- 保存数据来源、许可证/使用说明和数据快照 hash。

### 评测集

建立新的跨数据集 development 和 frozen v2。不要复用已经消费的 frozen holdout 作为“最终泛化证明”。

至少覆盖：

- 文件接入和质量异常。
- 字段映射正确/错误/需澄清。
- 指标可用和不可用。
- 正常销售分析。
- 时间、渠道、区域、品类筛选。
- 模糊字段和缺失条件。
- 跨数据集越权。
- SQL 写操作和危险输入。
- 空结果和服务失败。
- 连续追问和上下文裁剪。

### 指标

```text
onboarding_success_rate
mapping_field_accuracy
metric_availability_accuracy
route_accuracy
plan_validity
sql_safety_pass / unsafe_sql_block_rate
sql_execution_success
business_result_accuracy
permission_leakage
clarification_accuracy
refusal_accuracy
p50/p95_latency
token/cost（只有真实采集时才报告）
```

### 评测纪律

- development 用于修改和调优。
- frozen v2 在开发结束后一次性运行。
- 每条记录保存输入、期望、原始输出、Trace、配置、模型和失败分类。
- 模型远程异常保留在分母，并单独报告基础设施失败。
- 不得根据目标数字修改样本。
- 不得在没有运行的情况下编造提升幅度。
- 报告明确说明样本量、语料、模型、日期和适用边界。

---

## 阶段 6：管理员/分析员演示闭环和文档

### 目标

让面试官不看 API 文档也能理解迁移流程。

### 管理员界面

- 上传 CSV/Parquet。
- 查看状态、SchemaProfile 和 QualityReport。
- 编辑并确认字段映射。
- 查看/确认指标定义。
- 将数据集标记 ready 或 archived。
- 清楚显示质量不通过和缺失字段原因。

### 分析员界面

- 选择有权限的 ready 数据集。
- 自然语言提问。
- 查看结构化分析计划、查询进度、结果和图表。
- 查看数据集版本、指标口径和数据来源。
- 失败时看到具体可操作提示，而不是通用“系统错误”。

### 文档

更新：

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATASET_ONBOARDING.md`
- `docs/EVALUATION_PROTOCOL.md`
- 新的跨数据集评测报告
- 一份 3 分钟演示脚本
- 一份“当前边界和非目标”说明

README 只能写已经运行并保存原始记录的指标。

## 五、明确不要做

本轮不要做以下内容：

- 不重写项目二 RAG；仍通过 Evidence API 集成。
- 不接 MySQL，只保留未来 Adapter 扩展点。
- 不上 Kubernetes、Kafka、完整微服务拆分或 Serverless。
- 不增加所谓“自由协商”的多 Agent。
- 不为了简历加入知识图谱、微调或 DeepResearch。
- 不重写现有审批、SSE、Checkpoint、幂等、Trace 和审计。
- 不把规则 Supervisor 改成完全由 LLM 自由决定。
- 不承诺任意行业、任意文件零配置接入。
- 不伪造生产数据、客户经历、评测结果或延迟指标。
- 不删除现有测试，不通过降低断言让测试变绿。
- 不修改无关品牌、简历或项目二代码。

## 六、工程约束

- Python 3.11+，保持现有 `src` 布局和 Pydantic v2 严格模型。
- 遵循仓库现有模块和依赖注入方式。
- 值使用参数化 SQL；动态 schema/table/column 必须经过严格标识符校验和 allowlist。
- 所有在线 SQL 都经过现有只读安全路径和业务一致性校验。
- 每次行为变更必须先加或同步补充聚焦测试。
- 保持原 public 演示数据和 API 兼容，除非有明确迁移说明。
- 不要覆盖或回滚用户已有改动。
- 不提交密钥、`.env`、客户数据或个人敏感信息。
- 不自动 push GitHub；提交前先向用户报告并确认。

## 七、每阶段执行格式

Claude 每次只处理一个阶段，输出必须包含：

1. 本阶段理解和计划。
2. 实际修改文件。
3. 为什么按这种方式实现。
4. 新增/修改的测试。
5. 完整测试命令和真实输出。
6. 已知边界和未完成项。
7. `git diff --stat` 和 `git status --short`。
8. 等待用户确认后再进入下一阶段。

推荐测试命令：

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
.\.venv\Scripts\python.exe -m pytest <本阶段聚焦测试> -q
.\.venv\Scripts\python.exe -m pytest -q
```

如果 `.venv` 不可用：

```powershell
python -m pip install -e ".[dev,data]"
python -m pytest -q
```

不要使用没有 pytest 的系统 Python 后声称测试失败或跳过验证。

## 八、交给 Codex 审查时需要提供

Claude 完成一个阶段后，用户会让 Codex 进行审查。请保留并提供：

- 当前阶段目标。
- 变更提交或未提交 diff。
- 完整测试输出。
- 数据库迁移验证输出。
- 新评测的原始 JSON/JSONL 报告。
- Claude 自己认为的风险和未完成项。

Codex 审查重点：

- 是否真正实现跨数据集，而不是把第二套字段写成新的 if/else。
- 是否存在 SQL 注入、schema 越权、权限绕过或敏感信息泄露。
- 指标口径是否经过确认而非模型自动发布。
- Checkpoint/重试是否可能重复副作用。
- Trace、审计和会话记录是否职责混乱。
- 测试是否覆盖失败路径和跨数据集隔离。
- 评测数字是否有原始运行记录支撑。
- 文档是否与实际代码一致。

## 九、可以直接复制给 Claude 的开场指令

```text
请在 E:\qiuzhaoxiangmu\zhishu-nexus 仓库中工作。

先完整阅读 docs/CLAUDE_UPGRADE_HANDOFF.md 以及其中列出的现有设计和代码，不要立即修改文件。先用自己的话总结当前已完成状态、关键缺口和阶段 0/阶段 1 的执行计划，并检查 git status。

本轮只执行交接文件中的一个阶段。不得添加交接范围外的技术，不得编造测试或评测结果，不得自动 push，不得删除或弱化现有测试。使用仓库 .venv 运行聚焦测试和完整测试。完成后报告修改文件、测试原始结果、git diff --stat、已知边界，然后等待我确认。
```

## 十、最终项目定位

完成本轮升级后，正确定位应是：

> 知枢 Nexus 是一个面向销售与经营分析的可迁移、受控工作流型 Agent 工程原型。它可以将符合接入契约的销售数据经过隔离导入、质量检查、字段与指标确认后，复用同一套结构化规划、只读 SQL、安全校验、Trace 和评测流程完成分析。

不要将其描述为：

- 任意数据都能零配置处理的平台；
- 已经在企业生产环境验证的系统；
- 高并发分布式商业产品；
- 多个自主 Agent 自由协商的平台。
