# 项目范围

## 业务问题

让不懂 SQL 的零售运营人员能够安全、可追溯地分析订单、商品、渠道和退款数据。

## 核心工作流

```text
自然语言问题
-> 检索指标口径和 Schema
-> 生成结构化分析计划
-> 生成并校验只读 SQL
-> 执行查询
-> 生成图表规格
-> 输出结论、SQL、指标口径和数据来源
```

## 暑假必须完成

- PostgreSQL 业务数据与指标字典
- SQLGlot AST 安全校验
- LangGraph 状态工作流与 Checkpointer
- 指标和 Schema 检索
- 图表规格与 SSE 状态输出
- 权限、人工确认、超时、重试和审计
- 至少 100 条独立评测数据
- Docker Compose、pytest 和 GitHub Actions

## 暑假明确不做

- 泛化到任意行业和任意数据库
- PDF/OCR 全格式解析
- 为了数量拆分多个 Sub-agent
- K8s 生产部署
- 复杂微服务拆分
- 没有评测依据的简历指标

