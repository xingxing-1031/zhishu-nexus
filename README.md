# Retail Analytics Agent

面向零售运营的可审计数据分析 Agent，目标是让不熟悉 SQL 的运营人员能够使用自然语言分析订单、商品、渠道和退款数据，同时保留可检查的 SQL、执行过程和数据依据。

## 当前状态

- 当前计划任务：`W2-1` PostgreSQL 表结构、迁移和种子数据
- 总体进度：`4 / 32` 个项目里程碑
- 已完成：项目初始化、Pydantic 领域模型、零售 ER 模型、核心 SQL 练习和 FastAPI 基础接口
- 自动化测试：`15 passed`
- 当前边界：接口只完成健康检查和请求校验；尚未接入 PostgreSQL、真实 SQL 执行和 Agent 工作流

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

### FastAPI 接口基础

- `GET /health`：返回应用存活状态。
- `POST /analysis/validate`：使用 `AnalysisRequest` 校验分析请求，并自动返回 200 或 422。
- 使用 TestClient 验证路由、模型默认值、非法行数限制和 JSON 响应。
- 第一轮代码审查处理了测试依赖弃用 warning，并在格式整理后完成 15 项回归测试。

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

## 目录结构

```text
retail-analytics-agent/
|-- src/retail_analytics_agent/
|   |-- __init__.py
|   |-- app.py
|   `-- models.py
|-- tests/
|   |-- test_app.py
|   |-- test_models.py
|   `-- test_smoke.py
|-- docs/
|   |-- sql/
|   |-- ER_MODEL.md
|   |-- PROJECT_SCOPE.md
|   `-- UPGRADE_BACKLOG.md
|-- pyproject.toml
`-- README.md
```

## 下一阶段

1. 使用 PostgreSQL 建表、迁移并导入可复现的种子数据。
2. 将现有 SQL 放入真实数据库执行并保存验证证据。
3. 实现订单、商品、退款和渠道统计查询接口。
4. 实现只读 SQL 校验、查询限制和审计记录。

## 完成定义

一个里程碑只有同时满足以下条件才会标记完成：

1. 代码或文档已经提交并推送。
2. 自动化测试或对应验证证据通过。
3. 能够脱离代码解释关键设计、故障边界和技术取舍。
4. 不把尚未运行的功能或预设指标描述成已完成结果。
