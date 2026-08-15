# Agent 项目简历证据与表述

## 推荐项目名称

知枢 Nexus｜面向电商运营场景的企业智能 Agent 平台

## 一页简历推荐版

- 独立设计并实现企业智能 Agent 平台“知枢 Nexus”，基于 FastAPI、LangGraph、PostgreSQL 与 React/TypeScript 构建 Supervisor，将请求路由至通用对话、企业知识、经营数据或跨域协作模式；通用 Agent 通过 MCP 调用时间、天气、网页搜索、网页摘要和汇率工具，复杂任务由知识/数据 Agent 并行取证后综合并审核。
- 将企业知识作为独立 RAG Evidence API 接入，保留权限、版本、生效时间、混合检索、Reranker、引用和拒答边界；服务端上下文按用户/会话隔离并执行 Token 预算控制，工具记录参数哈希、耗时、状态与失败类型。
- 构建 SQLGlot AST 只读校验与指标、JOIN、时间范围业务一致性双层防线，使用顶层请求指纹、结果快照、checkpoint、人工审批、幂等键和结构化 Trace 支持相同请求回放与 SSE 断线恢复；企业请求进入管理员业务审计，普通聊天与公开工具查询排除，模型总结失败时仍保留可信 rows 与引用。
- 建立 60 条分层 development 评测，记录 Agent 模式、Skill 路由、工具集合、知识/数据证据、拒答、上下文预算与 P50/P95；远程 Qwen + 公网 VPS 结果为逐题契约通过 46/60（76.67%）、模式路由 60/60、安全拒答 8/8、工具选择 59/60、证据要求 50/60、P50/P95 9.21s/19.57s。

## BOSS 在线项目描述短版

独立实现企业智能 Agent 平台“知枢 Nexus”，使用 FastAPI、LangGraph、PostgreSQL 与 React/TypeScript 构建通用、企业知识、经营数据及协作四类执行模式；通过 MCP 接入时间、天气、搜索、网页摘要和汇率工具，并复用可审计 Text-to-SQL 与独立 RAG Evidence API。SQL 执行前经过 SQLGlot AST 与业务一致性双层校验，支持审批、顶层幂等与断线恢复、企业审计、Trace 和证据不足降级。

## 指标证据表

| 可用表述 | 原始证据 | 必须附带的边界 |
|---|---|---|
| 46/60 逐题契约通过 | `evaluation/reports/agent-live-development-20260815T000815Z.json` | 60 条 live development；不是通用 Agent 准确率或 frozen holdout |
| Agent 模式路由 60/60 | 同一报告 `metrics.agent_mode_accuracy` | 通用、知识、数据、协作和安全五类样本 |
| 安全拒答 8/8 | 同一报告 `metrics.refusal_accuracy` 与 `by_category.safety` | 写操作、越权字段和不支持指标；不等于全部业务回答正确 |
| 工具选择 59/60 | 同一报告 `metrics.tool_selection_accuracy` | 按工具集合比较，不把并发完成顺序当成选择错误 |
| 证据要求 50/60 | 同一报告 `metrics.evidence_requirement_accuracy` | RAG 证据不足会拒答或降级，失败仍保留在分母 |
| P50/P95 9.21/19.57 秒 | 同一报告 `latency_seconds` | 60 条串行公网请求，远程模型与外部工具 |
| 上下文最大占预算 5.25% | 同一报告 `context_budget_usage` | 仅为 ContextBuilder 确定性估算，不是模型总 Token |
| 发布 50-58 秒 | GitHub Actions runs `31745443474`、`31746510343`、`31747968222` | 完整发布总时长；不代表请求延迟 |

## 面试主动说明

这套评测最有价值的不是“76.67%”本身，而是样本级记录暴露了真实系统边界：

1. 周报 Skill 能路由，但下层 SQL 门禁不接受模糊“经营指标”，因此给 Skill 增加了显式默认指标契约。
2. 复合问题原样交给 RAG 会把 SQL 统计任务错误拆成知识证据 need，因此在 Agent 层分离 SQL 问题与制度问题。
3. 公网 API 每 IP 每分钟 6 次，评测器按 `Retry-After` 重试并记录等待，避免把限流误算成拒答失败。
4. 唯一最终未完全通过样本是总结服务降级；SQL、RAG、MCP 和证据均成功，系统保留可信 rows，没有为了全绿反复挑选运行结果。

## 禁止使用的表述

- “Agent 准确率 76.67%”
- “生产级高可用系统”
- “RAG 准确率 100%”
- “性能提升 90%”但不说明是 CI/CD 发布耗时
- “完全消除幻觉”
- “支持任意数据库、任意企业制度或海量数据”

更准确的说法是：在明确的合成数据、制度语料、角色和工具边界内，系统具备可审计执行、证据约束、失败降级和可复现实验能力。
