# Agent 项目简历证据与表述

## 推荐项目名称

企业经营分析 Agent（零售场景）

## 一页简历推荐版

- 独立设计并部署企业经营分析 Agent，基于 FastAPI、LangGraph、PostgreSQL、React/TypeScript 构建 4 类业务 Skill，将复合问题拆为结构化数据与制度证据子任务，通过统一 Tool Registry 接入可审计 Text-to-SQL、企业 RAG Evidence API 与 MCP Markdown 导出；服务端上下文按用户/会话隔离并执行 Token 预算控制。
- 构建 SQLGlot AST 只读校验与指标、JOIN、时间范围业务一致性双层防线，复用 checkpoint、人工审批、请求指纹、幂等键和结构化 Trace；模型总结失败时保留可信查询 rows 与引用并降级输出，避免无证据因果归因和恢复重放副作用。
- 建立 12 条远程 Qwen + 公网 VPS live development 评测，逐题契约通过 11/12，Skill 路由、工具选择、证据要求、拒答与上下文预算均为 100%，8 条业务题全部成功或可信降级，端到端 P95 29.535 秒；通过 Git bundle、Docker 依赖缓存和区域镜像将发布由超过 13 分钟未完成降至最近三次 50-58 秒。

## BOSS 在线项目描述短版

独立完成并部署企业经营分析 Agent，使用 FastAPI、LangGraph、PostgreSQL 与 React/TypeScript 实现 Skill 路由、服务端上下文、受治理 Tool Registry、Text-to-SQL、企业 RAG 和 MCP 报告导出。SQL 执行前经过 SQLGlot AST 只读校验与业务一致性校验，并支持审批、幂等、Trace 和可信降级。公网 12 条 development 实测中逐题通过 11/12，路由、工具选择、证据要求和拒答均为 100%，P95 29.535 秒。

## 指标证据表

| 可用表述 | 原始证据 | 必须附带的边界 |
|---|---|---|
| 11/12 逐题通过 | `evaluation/reports/agent-live-development-20260813T220105Z.json` | live development，已用于定位问题，不是 holdout |
| 路由/工具/证据/拒答/预算均 100% | 同一报告 `metrics` 与 12 条 `records` | 仅覆盖当前 12 条合成业务题 |
| 8/8 业务题无失败 | 同一报告，5 succeeded + 3 degraded | degraded 包含可信结果保留，不等于全部完整回答 |
| P95 29.535 秒 | 同一报告 `latency_seconds` | 12 条混合样本，串行、单 VPS、远程模型 |
| 上下文最大占预算 5.5% | 同一报告 `context_budget_usage` | 仅为 ContextBuilder 确定性估算，不是模型总 Token |
| 发布 50-58 秒 | GitHub Actions runs `31745443474`、`31746510343`、`31747968222` | 完整发布总时长；不代表请求延迟 |

## 面试主动说明

这套评测最有价值的不是“91.7%”本身，而是样本级记录暴露了真实系统边界：

1. 周报 Skill 能路由，但下层 SQL 门禁不接受模糊“经营指标”，因此给 Skill 增加了显式默认指标契约。
2. 复合问题原样交给 RAG 会把 SQL 统计任务错误拆成知识证据 need，因此在 Agent 层分离 SQL 问题与制度问题。
3. 公网 API 每 IP 每分钟 6 次，评测器按 `Retry-After` 重试并记录等待，避免把限流误算成拒答失败。
4. 唯一最终未完全通过样本是总结服务降级；SQL、RAG、MCP 和证据均成功，系统保留可信 rows，没有为了全绿反复挑选运行结果。

## 禁止使用的表述

- “Agent 准确率 91.7%”
- “生产级高可用系统”
- “RAG 准确率 100%”
- “性能提升 90%”但不说明是 CI/CD 发布耗时
- “完全消除幻觉”
- “支持任意数据库、任意企业制度或海量数据”

更准确的说法是：在明确的合成数据、制度语料、角色和工具边界内，系统具备可审计执行、证据约束、失败降级和可复现实验能力。
