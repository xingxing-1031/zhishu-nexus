# 企业经营分析 Agent 面试讲解

## 一句话介绍

我把原来的可审计 Text-to-SQL 工作流升级成一个单 Agent 企业经营分析 Runtime：它先把问题路由到业务 Skill，再生成有界 TaskPlan，使用服务端上下文和统一 Tool Registry 调用 PostgreSQL 与企业制度 RAG，最后输出带数据 source ID、制度引用、限制说明和 Markdown 导出的经营复盘报告。

## 主流程

1. 用户提出“最近 30 天退款率为什么变化，结合售后制度复盘”。
2. Skill Router 选择 `refund_diagnosis`，TaskPlanner 生成趋势、拆解、制度证据和报告等有界子任务。
3. ContextBuilder 按“当前目标/约束 -> 证据 -> 最近工具结果 -> 摘要 -> 历史原文”装配上下文，并设置 Token 上限。
4. Tool Registry 校验每次调用的 Pydantic Schema、角色、风险等级、超时和幂等键。
5. `sql.query` 复用原有 SQLGlot AST 只读校验、指标/JOIN/时间范围业务一致性校验、审批和 PostgreSQL 只读执行。
6. `knowledge.search` 通过项目二受令牌保护的 `/internal/evidence` 获取权限过滤、版本和生效时间明确的制度证据；项目二继续负责 Rerank、引用边界和权限。
7. ReportComposer 把 SQL 结果与制度引用合并成结构化报告；可选 `report.export` 通过官方 MCP Python SDK 导出 Markdown。

## 高频追问

### 为什么不是把 RAG 也封装成 MCP？

RAG 是核心证据链，必须稳定参与主链路、保留项目二的权限和引用边界，因此使用内部 HTTP Evidence API。MCP 选择报告导出这种可替换的外部工具，展示工具发现、Schema、调用失败降级和协议接入能力，不让协议层绕过核心安全边界。

### 上下文如何控制？

服务端按 conversation ID 和 user ID 隔离保存结构化对话、确认约束、证据 ID 和摘要，不保存模型隐式思考。ContextBuilder 用确定性 Token 估算，优先保留当前目标和证据，预算不足时截断旧历史并在响应中标记 `truncated`。

### 如何处理恢复和副作用？

LangGraph checkpoint 只在节点边界保存可恢复状态；工具调用带 `request_id`、conversation ID 和输入指纹。幂等工具复用相同结果，邮件/导出等副作用必须有稳定幂等键，避免恢复时重复执行。Trace 解释运行过程，Audit 记录责任和追溯，两者不混用。

### SSE 和任务状态是什么关系？

SSE 只是订阅通道，前端断开不会取消服务端线程中的任务；任务状态和工具结果由服务端保存。重新打开页面应按 conversation/task ID 查询状态或继续订阅，不能把一个浏览器连接当作任务生命周期。

### 目前哪些数字能写在简历？

可以写已经保存并可复现的项目二 frozen holdout：8 条、执行成功率 75%、核心通过率 62.5%、Recall@5 100%、引用准确率 85%、权限泄漏率 0%、P50/P95 6.93s/41.45s。项目一新增 Agent deterministic development 的 5 条规则样本结果只能写成“规则层评测”，不能写成真实模型准确率。远程 API + 真实数据库实测后，再补 Agent 端到端 P50/P95 和成功率。
