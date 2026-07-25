# Retail Analytics Agent

面向零售运营的可审计数据分析 Agent，目标是让不熟悉 SQL 的运营人员能够使用自然语言分析订单、商品、渠道和退款数据，同时保留可检查的 SQL、执行过程和数据依据。

## 当前状态

- 当前计划任务：`W3-3` 封装检索、校验和执行工具契约
- 总体进度：`10 / 32` 个项目里程碑
- 已实现：项目初始化、领域模型、零售 ER 模型、核心 SQL、PostgreSQL 数据库、四类 FastAPI 统计接口、SQLGlot AST 校验、安全查询与审计服务、LangGraph 工作流骨架，以及 Pydantic 结构化分析计划
- 自动化验证：Python 回归测试 `95 passed`；真实 PostgreSQL 安全查询与 `succeeded`/`rejected` 审计落库验收通过；分析计划测试覆盖枚举、字段边界、跨字段规则和 State 传递
- 当前边界：计划与其他工作流节点仍为可注入的假节点；尚未接入真实大模型、检索/校验/执行工具节点、Checkpointer 和生产 PostgreSQL 独立只读账号

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

### 结构化分析计划

- 使用 `AnalysisPlan` 将分析意图拆成指标、维度、筛选、时间范围、排序和最大行数。
- 使用枚举限制当前支持的业务词汇，并拒绝未知字段和额外结构。
- 使用跨字段规则校验筛选操作和值类型、重复指标/维度以及排序字段来源。
- 将 `AnalysisState.plan` 从任意字典升级为 `AnalysisPlan | None`。
- 保留 Pydantic 计划校验与 SQLGlot 执行安全校验之间的独立边界。

## 项目范围

目标工作流：

```text
自然语言问题
-> 检索指标口径和 Schema
-> 生成结构化分析计划
-> 生成并校验只读 SQL
-> 执行查询
-> 生成图表规格
-> 输出结论、SQL、指标口径和数据来源
```

当前仓库尚未实现完整 Agent 链路。范围与非目标见 [PROJECT_SCOPE.md](docs/PROJECT_SCOPE.md)，后续工程任务见 [UPGRADE_BACKLOG.md](docs/UPGRADE_BACKLOG.md)。

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
Copy-Item .env.example .env
docker compose up -d
docker compose cp db/migrations/001_initial_schema.sql postgres:/tmp/001_initial_schema.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /tmp/001_initial_schema.sql
docker compose cp db/seeds/001_demo_data.sql postgres:/tmp/001_demo_data.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /tmp/001_demo_data.sql
docker compose cp db/verification/verify_w2_1.sql postgres:/tmp/verify_w2_1.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U retail_user -d retail_analytics -f /tmp/verify_w2_1.sql
```

首次运行前请把 `.env` 中的示例密码改为本地密码。不要提交 `.env`，也不要使用 `docker compose down -v` 删除数据库数据卷。

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
|-- pyproject.toml
`-- README.md
```

## 下一阶段

1. 将检索、安全校验和查询服务封装为真实工具节点。
2. 接入 PostgreSQL Checkpointer 并验证任务中断恢复。
3. 建立指标字典、Schema 文档和版本信息，为后续 RAG 提供可信知识源。

## 完成定义

一个里程碑只有同时满足以下条件才会标记完成：

1. 代码或文档已经提交并推送。
2. 自动化测试或对应验证证据通过。
3. 能够脱离代码解释关键设计、故障边界和技术取舍。
4. 不把尚未运行的功能或预设指标描述成已完成结果。
