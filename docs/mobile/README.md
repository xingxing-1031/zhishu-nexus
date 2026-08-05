# 手机学习卡入口

这组卡片用于离开电脑时复习项目知识，不代替写代码、运行测试和排错。

## 每次怎么学

一次学习控制在 15 分钟左右：

1. 用 5 分钟阅读一小节，不要求背原句。
2. 关闭页面，用 3 分钟回忆“它解决什么问题、怎么工作、边界是什么”。
3. 用 5 分钟回答卡片末尾的自测题，再展开标准答案核对。
4. 用 1 至 2 分钟口述，尽量不用“这个、那个、反正”等模糊词。

只看懂会产生熟悉感，不等于掌握。能在不看答案时说出因果关系，才算完成一次有效复习。

## 当前卡片

| 顺序 | 卡片 | 建议用时 | 状态 |
|---|---|---:|---|
| 1 | [项目全貌与当前边界](01-project-map.md) | 6 分钟 | 已学内容复习 |
| 2 | [Pydantic 与 pytest](02-pydantic-pytest.md) | 8 分钟 | 已学内容复习 |
| 3 | [零售 ER 模型与核心 SQL](03-sql-er.md) | 10 分钟 | 已学内容复习 |
| 4 | [FastAPI、HTTP 与接口测试](04-fastapi-http.md) | 8 分钟 | 已学内容复习 |
| 5 | [PostgreSQL、Docker 与 pgvector](05-postgresql-docker.md) | 8 分钟 | 已学内容复习 |
| 6 | [FastAPI 业务查询服务主链路](06-fastapi-query-service.md) | 15 分钟 | W2-2 深度理解 |
| 7 | [SQLGlot 与只读 SQL AST 校验](07-sqlglot-ast-safety.md) | 12 分钟 | W2-3 已完成 |
| 8 | [安全查询的四道执行防线](08-safe-query-guardrails.md) | 15 分钟 | W2-4 已完成 |
| 9 | [LangGraph 的 State、Node 与 Edge](09-langgraph-state-nodes-edges.md) | 15 分钟 | W3-1 已完成 |
| 10 | [Pydantic 结构化分析计划](10-structured-analysis-plan.md) | 15 分钟 | W3-2 已完成 |
| 11 | [工作流工具契约](11-workflow-tool-contracts.md) | 15 分钟 | W3-3 已完成 |
| 12 | [PostgreSQL Checkpointer 与中断恢复](12-postgres-checkpointer.md) | 15 分钟 | W3-4 已完成 |
| 13 | [指标字典与 Schema 目录](13-metric-schema-catalog.md) | 18 分钟 | W4-1 已完成 |
| 14 | [按分析计划检索业务证据](14-catalog-retrieval.md) | 18 分钟 | W4-2 已完成 |
| 15 | [向量检索、混合召回与重排](15-vector-hybrid-reranking.md) | 22 分钟 | W4-3 已完成 |
| 16 | [真实模型端到端分析与 SSE](16-end-to-end-analysis-sse.md) | 20 分钟 | W4-4 已完成 |
| 17 | [可信身份与字段访问控制](17-access-control.md) | 18 分钟 | W5-1 已完成 |
| 18 | [Human-in-the-loop 查询审批](18-hitl-approval.md) | 20 分钟 | W5-2 已完成 |
| 19 | [超时、重试、幂等与降级](19-timeout-retry-idempotency.md) | 20 分钟 | W5-3 已完成 |

## 复习节奏

同一张卡片建议复习四次：

- 第一次：当天阅读并口述。
- 第二次：隔 1 天，只做自测，答错再看正文。
- 第三次：隔 3 天，完成 1 分钟口述。
- 第四次：隔 7 天，把知识点联系到项目中的真实文件或代码。

不需要一天读完全部卡片。走路、坐车时只进行阅读和口述；涉及命令、代码或账号的操作留到电脑前完成。

## 手机与电脑的分工

```text
手机：阅读 -> 关页回忆 -> 自测 -> 口述
电脑：写代码 -> 跑测试 -> 分析报错 -> 查看改动 -> 提交 Git
```

手机复习不单独增加项目里程碑。项目进度仍以代码、测试、口述验收和 Git 证据为准。
