# Retail Analytics Agent

面向零售运营的可审计数据分析 Agent，目标是让不熟悉 SQL 的运营人员能够使用自然语言分析订单、商品、渠道和退款数据，同时保留可检查的 SQL、执行过程和数据依据。

## 当前状态

- 当前计划任务：`W6-3` Docker Compose、pytest 和 GitHub Actions 交付
- 总体进度：`22 / 32` 个项目里程碑，W6-2 已完成
- 已实现：真实 `qwen3:4b` 端到端分析、权限与人工审批、有限重试、请求幂等、可信结果降级、确定性故障注入和结构化执行 Trace
- 自动化验证：Python 回归测试 `358 passed`；W6-2 完成 40 条 development × 3 个检索方案的 120 次受控评测，核心阶段通过率均为 `100%`
- 当前边界：仍是本地身份和小规模种子数据；尚未完成正式登录、生产部署、前端图表渲染和 frozen holdout 最终验收

## 手机学习

离开电脑时可使用 [手机学习卡](docs/mobile/README.md) 复习已经完成的知识，并预习下一阶段。卡片包含短篇正文、折叠自测答案、口述题和间隔复习方法；阅读记录不代替代码、测试和里程碑验收。

## 已完成内容

### Python 工程基础

- 使用 `src` 布局组织正式源码。
- 使用 `pyproject.toml` 管理项目元数据、运行依赖、开发依赖和 pytest 配置。
- 使用独立虚拟环境和 pytest 建立可复现的开发与测试入口。

### 零售领域模型

- `Order`：订单编号、渠道、金额和状态。
- `Product`：商品编号、名称、类别和当前参考价格。
- `Refund`：退款编号、关联订单、退款金额、原因和状态。
- `AnalysisRequest`：分析请求编号、用户、自然语言问题和最大返回行数。
- 使用 Pydantic 校验金额边界、状态枚举和查询行数限制。

### 数据库设计与 SQL

- 设计 `orders`、`products`、`order_items` 和 `refunds` 四张核心业务表。
- 使用 `order_items` 拆分订单与商品的多对多关系，并保存历史成交价快照。
- 完成 11 个查询块，覆盖连接、筛选、聚合、去重计数、退款统计、空值处理、结果排序与行数限制等核心场景。
- 设计说明见 [ER_MODEL.md](docs/ER_MODEL.md)，练习 SQL 见 [w1_3_join.sql](docs/sql/w1_3_join.sql)。

### PostgreSQL 开发数据库

- 使用 Docker Compose 运行 PostgreSQL 16 和 pgvector，数据库数据保存在命名数据卷中。
- 使用版本化迁移创建 `orders`、`products`、`order_items`、`refunds` 四张表，以及金额、状态、外键和索引约束。
- 使用可重复种子脚本导入 6 个商品、10 个订单、13 条订单明细和 6 条退款；重复执行后行数不变。
- 在真实 PostgreSQL 中执行 11 个业务查询块，并验证订单总金额与明细计算结果一致。
- 使用数据库验收脚本检查扩展、表、关键数据场景、金额一致性和非法状态拒绝。

### FastAPI 接口基础

- `GET /health`：返回应用存活状态。
- `POST /analysis/validate`：使用 `AnalysisRequest` 校验分析请求，并自动返回 200 或 422。
- 使用 TestClient 验证路由、模型默认值、非法行数限制和 JSON 响应。
- 第一轮代码审查处理了测试依赖弃用 warning，并在格式整理后完成 15 项回归测试。

### LangGraph 工作流骨架

- 使用 `AnalysisState` 保存单次分析任务的请求、计划、证据、SQL、执行结果、重试计数和轨迹。
- 使用七个可注入节点组织计划、检索、SQL 生成、校验、执行、总结和失败处理。
- 使用普通边固定主链路，使用条件边处理 SQL 重新生成、执行成功和执行失败。
- 将零行查询结果视为成功，仅在 `execution_error` 存在时进入失败节点。
- 使用固定输出的假节点验证图结构；当前不宣称已经接入大模型或真实工具节点。

### 容错与可观测性

- 模型瞬时错误采用有限重试、指数退避、随机抖动和工作流总时间预算。
- 相同 API 请求使用请求指纹复用状态，相同 `request_id` 的不同输入返回 409。
- 查询审计、审批审计和请求登记使用幂等边界，避免恢复重放产生重复副作用。
- 使用确定性故障规则指定组件和第几次调用失败，避免随机测试无法复现。
- 结构化 Trace 记录节点、模型尝试、状态、耗时、错误类型和重试等待；查询与审批审计仍保留独立职责。
- `GET /analysis/{request_id}/trace` 只允许请求本人或 admin 读取完整执行事件。

### 结构化分析计划

- 使用 `AnalysisPlan` 将分析意图拆成指标、维度、筛选、时间范围、排序和最大行数。
- 使用枚举限制当前支持的业务词汇，并拒绝未知字段和额外结构。
- 使用跨字段规则校验筛选操作和值类型、重复指标/维度以及排序字段来源。
- 将 `AnalysisState.plan` 从任意字典升级为 `AnalysisPlan | None`。
- 保留 Pydantic 计划校验与 SQLGlot 执行安全校验之间的独立边界。
- 在 SQLGlot 安全校验之后增加独立业务一致性节点，检查指标公式、固定筛选、Evidence 表、JOIN 和维度分组；失败时有限重试且不访问数据库。

### 指标与 Schema 知识目录

- 使用版本化 `MetricDefinition` 记录 6 个指标的业务含义、公式、来源字段、固定筛选和支持维度。
- 使用 `SchemaCatalog` 记录 4 张业务表的字段、主键和 3 条允许 JOIN 关系。
- 为指标、表和关联生成稳定 `source_id`，支持后续检索证据和审计回溯。
- 使用固定种子数据在真实 PostgreSQL 中验证销售额、订单数、销售件数、退款金额、退款笔数和平均订单金额。
- 当前目录已接入 LangGraph 检索节点，并能根据结构化分析计划返回最小充分证据；尚未实现关键词、向量或混合检索。

## 项目范围

目标工作流：

```text
自然语言问题
-> 检索指标口径和 Schema
-> 生成结构化分析计划
-> 生成 SQL
-> 校验只读安全与业务一致性
-> 执行查询
-> 生成图表规格
-> 输出结论、SQL、指标口径和数据来源
```

当前仓库已实现自然语言到安全 SQL、真实查询、结果解释、权限控制和可恢复审批链路。范围与非目标见 [PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md)，后续工程任务见 [UPGRADE_BACKLOG.md](docs/UPGRADE_BACKLOG.md)。

## 本地运行

环境要求：Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

启动并验证本地数据库：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 首次使用空数据卷时，Compose 会按文件名顺序自动执行 6 个迁移和种子脚本。
docker compose up -d --wait
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /opt/retail-db/verification/verify_delivery.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /opt/retail-db/verification/verify_w2_1.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /opt/retail-db/verification/verify_w4_1_metrics.sql
```

首次运行前请把 `.env` 中的示例密码改为本地密码。初始化脚本只对空数据卷执行；已有数据卷不会重复创建表或导入种子。不要提交 `.env`，也不要使用 `docker compose down -v` 删除本地数据库数据卷。需要验证全新初始化时，请使用独立 Compose 项目名和端口。

GitHub Actions 使用同一份 Compose 配置启动临时 pgvector 数据库，并执行 `db/verification/verify_delivery.sql`；Python 3.11 和 3.12 矩阵分别执行完整 pytest。工作流文件见 [.github/workflows/ci.yml](.github/workflows/ci.yml)。

## 目录结构

```text
retail-analytics-agent/
|-- db/
|   |-- migrations/
|   |-- seeds/
|   `-- verification/
|-- src/retail_analytics_agent/
|   |-- __init__.py
|   |-- app.py
|   |-- models.py
|   `-- workflow.py
|-- tests/
|   |-- test_app.py
|   |-- test_models.py
|   |-- test_smoke.py
|   `-- test_workflow.py
|-- docs/
|   |-- sql/
|   |-- ER_MODEL.md
|   |-- PROJECT_SCOPE.md
|   `-- UPGRADE_BACKLOG.md
|-- compose.yaml
|-- .github/workflows/ci.yml
|-- pyproject.toml
`-- README.md
```

## 下一阶段

1. 完成 Docker Compose、pytest 和 GitHub Actions 交付链路。
2. 完善 README、架构图和 v0.1 演示。
3. 评估正式登录、生产部署和前端图表渲染方案。

## 完成定义

一个里程碑只有同时满足以下条件才会标记完成：

1. 代码或文档已经提交并推送。
2. 自动化测试或对应验证证据通过。
3. 能够脱离代码解释关键设计、故障边界和技术取舍。
4. 不把尚未运行的功能或预设指标描述成已完成结果。
