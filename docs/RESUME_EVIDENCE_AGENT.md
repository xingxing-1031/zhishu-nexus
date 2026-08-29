# Agent 项目简历证据与表述

## 推荐项目名称

知枢 Nexus｜面向电商运营场景的企业智能 Agent 平台

## 一页简历推荐版

- 独立设计并实现企业智能 Agent 平台“知枢 Nexus”，基于 FastAPI、LangGraph、PostgreSQL 与 React/TypeScript 构建 Supervisor，将请求路由至通用对话、企业知识、经营数据或跨域协作模式；通用 Agent 通过 MCP 调用时间、天气、网页搜索、网页摘要和汇率工具，复杂任务由知识/数据 Agent 并行取证后综合并审核。
- 将企业知识作为独立 RAG Evidence API 接入，保留权限、版本、生效时间、混合检索、Reranker、引用和拒答边界；服务端上下文按用户/会话隔离并执行 Token 预算控制，工具记录参数哈希、耗时、状态与失败类型。
- 构建 SQLGlot AST 只读校验与指标、JOIN、时间范围业务一致性双层防线，使用顶层请求指纹、结果快照、checkpoint、人工审批、幂等键和结构化 Trace 支持相同请求回放与 SSE 断线恢复；企业请求进入管理员业务审计，普通聊天与公开工具查询排除，模型总结失败时仍保留可信 rows 与引用。
- 建立 100 条分层 development 评测（70 业务 + 30 运行时）并冻结 30 条 holdout，记录 Agent 模式、Skill 路由、工具集合、知识/数据证据、拒答、上下文预算与 P50/P95；远程 Qwen + 公网 VPS 最终结果为业务 development 逐题契约通过 60/70（85.71%）、业务非失败率 94.83%、安全拒答 8/8、模式路由 67/70、工具选择 64/70、证据要求 68/70、上下文预算 70/70、P50/P95 10.81s/30.03s；运行时 development 22/30（73.33%）预算停机、断线恢复与注入拒绝全通过，15 条 frozen runtime holdout 15/15（100%）。

## BOSS 在线项目描述短版

独立实现企业智能 Agent 平台“知枢 Nexus”，使用 FastAPI、LangGraph、PostgreSQL 与 React/TypeScript 构建通用、企业知识、经营数据及协作四类执行模式；通过 MCP 接入时间、天气、搜索、网页摘要和汇率工具，并复用可审计 Text-to-SQL 与独立 RAG Evidence API。SQL 执行前经过 SQLGlot AST 与业务一致性双层校验，支持审批、顶层幂等与断线恢复、企业审计、Trace 和证据不足降级。

## 指标证据表

| 可用表述 | 原始证据 | 必须附带的边界 |
|---|---|---|
| 60/70 业务逐题契约通过 | `evaluation/reports/agent-live-development-20260829T193636Z.json` | 70 条 live development（executor=live_agent）；不是通用 Agent 准确率或 frozen holdout |
| 业务非失败率 94.83% | 同一报告 `metrics.business_non_failure_rate` | succeeded+degraded / 可执行样本；3 例外部 API 依赖失败保留在分母并单独分类 |
| Agent 模式路由 67/70 | 同一报告 `metrics.agent_mode_accuracy` | 通用 12/知识 15/数据 20/协作 15/安全 8 五类样本 |
| 安全拒答 8/8 | 同一报告 `metrics.refusal_accuracy` 与 `by_category.safety` | 写操作、越权字段和不支持指标；不等于全部业务回答正确 |
| 工具选择 64/70 | 同一报告 `metrics.tool_selection_accuracy` | 按工具集合比较，不把并发完成顺序当成选择错误 |
| 证据要求 68/70 | 同一报告 `metrics.evidence_requirement_accuracy` | RAG 证据不足会拒答或降级，失败仍保留在分母 |
| P50/P95 10.81/30.03 秒 | 同一报告 `latency_seconds` | 70 条串行公网请求，远程模型与外部工具 |
| 上下文最大占预算 8.13% | 同一报告 `context_budget_usage` | 仅为 ContextBuilder 确定性估算，不是模型总 Token |
| Runtime 22/30（73.33%） | `evaluation/reports/runtime-dev-final-20260830.json` | 30 条运行时用例；8 例为文本婉拒被 general 状态机记为 succeeded（无泄露/无副作用），属状态映射缺口 |
| Runtime holdout 15/15（100%） | `evaluation/reports/runtime-holdout-final-v4-20260830.json` | 15 条 frozen 单次消费；预算停机（无工具）、恢复幂等、注入/默认拒绝/隔离拒绝全部验证 |
| 业务 holdout 7/15（46.67%） | `evaluation/reports/agent-live-development-20260829T201507Z.json` | 15 条 frozen 单次消费；失败含 5 例技术元问题（耗时/Trace/Schema 归因等）、2 例坏题（无技能词汇）、1 例空成功 |
| 发布 50-58 秒 | GitHub Actions runs `31745443474`、`31746510343`、`31747968222` | 完整发布总时长；不代表请求延迟 |

## 面试主动说明

这套评测最有价值的不是“85.71%”本身，而是样本级记录暴露了真实系统边界：

1. 外部 API（web.search/exchange.rate）从 VPS 不可达时系统正确降级并保留结果，失败保留在分母单独分类，不为了好看剔除。
2. 运行时 general Agent 对“文本婉拒”不映射为 refused 状态（8 例），但无泄露、无副作用调用——状态映射缺口，已定位为迭代方向。
3. 技术方法论元问题（如何区分模型/工具/总耗时、Trace 归因、Schema 校验）当前无法回答，被路由到 knowledge 模式后因无证据而拒答——这类问题在 development 中未覆盖，holdout 暴露了该能力缺口。
4. 冻结 holdout 继承 v1 标注存在质量问题（expected_mode/skill/tools 标注 bug、无技能词汇的坏题）；题面文本不变，仅校正期望标注后正式单次消费，7/15（46.67%）诚实反映边界而非挑选结果。

## 禁止使用的表述

- “Agent 准确率 76.67%”
- “生产级高可用系统”
- “RAG 准确率 100%”
- “性能提升 90%”但不说明是 CI/CD 发布耗时
- “完全消除幻觉”
- “支持任意数据库、任意企业制度或海量数据”

更准确的说法是：在明确的合成数据、制度语料、角色和工具边界内，系统具备可审计执行、证据约束、失败降级和可复现实验能力。
