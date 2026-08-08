# Retail Analytics Agent

面向零售运营的可审计数据分析 Agent，目标是让不熟悉 SQL 的运营人员能够使用自然语言分析订单、商品、渠道和退款数据，同时保留可检查的 SQL、执行过程和数据依据。

## 当前状态

- 当前计划任务：项目一 v0.1 已完成 W6-4 交付验收，正在进行 W7-4 受限公开演示准备
- 总体进度：`24 / 32` 个基础里程碑已完成；W7 为交付后的演示优化阶段
- 已实现：本地 `qwen3:4b` 与远程 Qwen 端到端分析、演示级权限与人工审批、有限重试、请求幂等、可信结果降级、确定性故障注入和结构化执行 Trace
- 自动化验证：Python 完整回归测试通过；W6-2 完成 120 次受控评测；W6-3 本地空卷 pgvector smoke 和 GitHub Actions Python 3.11/3.12、PostgreSQL smoke 均通过
- 当前边界：已完成公网演示和 130 条可复现演示订单；正式登录可通过 `AUTH_MODE=password` 开启，HTTPS、备份恢复和 frozen holdout 仍需单独验收

当前为 v0.1 演示级权限体系：支持服务器配置的单账号认证与角色区分，并在 SQL AST 与确定性安全校验层限制允许访问的表、字段及敏感字段。关键词启发式判断仅用于前置拦截，不作为最终安全边界。正式多用户身份管理与多租户隔离不在 v0.1 范围内。

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

- `GET /health`：返回应用存活状态，不检查数据库。
- `GET /ready`：检查 PostgreSQL 连接和分析工作流所需的业务关系是否就绪；未就绪时返回 `503`。
- `POST /analysis/validate`：使用 `AnalysisRequest` 校验分析请求，并自动返回 200 或 422。
- 使用 TestClient 验证路由、模型默认值、非法行数限制和 JSON 响应。
- 第一轮代码审查处理了测试依赖弃用 warning，并在格式整理后完成 15 项回归测试。

### LangGraph 工作流骨架

- 使用 `AnalysisState` 保存单次分析任务的请求、计划、证据、SQL、执行结果、重试计数和轨迹。
- 使用七个可注入节点组织计划、检索、SQL 生成、校验、执行、总结和失败处理。
- 使用普通边固定主链路，使用条件边处理 SQL 重新生成、执行成功和执行失败。
- 将零行查询结果视为成功，仅在 `execution_error` 存在时进入失败节点。
- 已将真实 Ollama 规划、目录检索、SQL 生成、双重校验、PostgreSQL 执行和总结工具接入同一工作流。

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
- 生产检索节点使用版本化指标与 Schema 目录进行确定性最小证据检索。
- 另实现关键词、bge-m3/pgvector 向量召回、RRF 混合融合、域判断与可选 LLM Reranker，作为评测对比方案（见 W4-3/W6-2 报告），未接入线上工作流。

### 业务评测与持续集成

- 建立 40 条 development 与 20 条 frozen holdout，按 plan、evidence、SQL、outcome、rows、chart 和 answer 分阶段评分。
- 在固定模型、数据库快照、时间和策略下运行 40 条 development × 3 个方案，共保存 120 条真实工作流原始记录。
- 三方案本轮六个核心阶段均为 `100%`，平均延迟约为 `3.835s / 4.101s / 4.877s`；该结果不等于通用 Agent 准确率。
- GitHub Actions 在 Python 3.11/3.12 运行完整 pytest，并从空数据卷验证 pgvector、迁移和种子。

详细实验条件、结果和边界见 [W6-2 受控评测报告](docs/EVALUATION_REPORT.md)。

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

完整组件和安全边界见 [系统架构](docs/ARCHITECTURE.md)。

## v0.1 演示

演示界面与 FastAPI 同源，不需要单独安装前端依赖。它展示 SSE 节点进度、结构化计划、证据 source ID、真实查询 rows、后端 `ChartSpec` 图表和结构化 Trace；高风险请求会停在人工审批状态。

![v0.1 零售运营分析台](docs/assets/v0.1-demo.png)

## 本地运行

环境要求：Python 3.11 或 3.12、Docker Desktop、Ollama 与本地 `qwen3:4b`。

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

启动模型和 FastAPI 演示：

```powershell
ollama serve
.\.venv\Scripts\python.exe -m uvicorn retail_analytics_agent.app:app --reload
```

浏览器打开 `http://127.0.0.1:8000/`。演示使用 `.env` 中由服务器配置的 `LOCAL_ACCESS_USER_ID` 和 `LOCAL_ACCESS_ROLE`，客户端不能自行把 analyst 改成 admin。API 文档位于 `http://127.0.0.1:8000/docs`。

也可以使用 `demo` profile 启动 API 容器。容器默认以分析员身份运行，数据库通过 Compose 服务名访问，模型地址默认指向宿主机 Ollama；公网部署不能直接使用这个宿主机地址。

```powershell
$env:API_PORT = "8005"
docker compose --profile demo up -d --build --wait
```

浏览器打开 `http://127.0.0.1:8005/`；就绪检查使用 `http://127.0.0.1:8005/ready`。

公网演示推荐使用 OpenAI 兼容协议的远程 Qwen。下面的密钥只能配置在托管平台的服务器环境变量中，不能写入前端、Compose 文件或 Git：

```text
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
MODEL_API_KEY=<server-secret>
MODEL_TIMEOUT_SECONDS=120
PUBLIC_DEMO_MODE=true
PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE=6
PUBLIC_DEMO_MAX_ROWS=20
```

未配置 `MODEL_BASE_URL`、`MODEL_NAME` 或 `MODEL_API_KEY` 时，远程模式会在应用启动阶段拒绝加载；默认 `MODEL_PROVIDER=ollama`，本地开发方式保持不变。

`PUBLIC_DEMO_MODE=true` 会强制要求分析员身份，关闭请求状态、人工审批和原始执行记录接口，并对分析请求执行单进程限流与返回行数限制。它适合受限作品演示，不能替代网关级分布式限流、正式认证和多租户隔离。

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
|   |-- ARCHITECTURE.md
|   |-- EVALUATION_REPORT.md
|   |-- assets/
|   |-- mobile/
|   |-- sql/
|   |-- ER_MODEL.md
|   |-- PROJECT_SCOPE.md
|   `-- UPGRADE_BACKLOG.md
|-- evaluation/
|   |-- reports/
|   `-- business_development.json
|-- compose.yaml
|-- .github/workflows/ci.yml
|-- pyproject.toml
`-- README.md
```

## 下一阶段

1. 保持 v0.1 评测基线稳定，根据真实演示反馈整理项目答辩材料。
2. 按总路线图进入下一项目，不在当前仓库继续无边界扩张功能。
3. 正式登录、生产部署和 frozen holdout 验收作为独立后续任务评估。

## 完成定义

一个里程碑只有同时满足以下条件才会标记完成：

1. 代码或文档已经提交并推送。
2. 自动化测试或对应验证证据通过。
3. 能够脱离代码解释关键设计、故障边界和技术取舍。
4. 不把尚未运行的功能或预设指标描述成已完成结果。
