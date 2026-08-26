# Agent Runtime + Evaluation 升级方案

> 给 Claude 执行、由 Codex 验收的升级方案。目标不是继续堆框架，而是让知枢 Nexus 能被观察、复现、故障注入、量化比较。

## 1. 升级目标

当前项目已经具备 Supervisor、LangGraph、Postgres Checkpoint、审批、SSE、Trace、RAG、受控 Text-to-SQL 和多组评测。下一阶段不再扩展无关业务，而是补齐 Agent 的运行时治理和失败归因能力。

最终希望做到：面对一次回答错误，可以判断问题主要来自哪一层，并用测试和评测证明修复是否有效：

Model / Context / Tool / Skill / State / Permission / Memory / Runtime。

项目的准确定位：

> 面向电商/零售经营分析的受控 Agent Runtime。它支持数据分析、企业知识检索和跨域协作，并提供预算控制、状态恢复、权限审计、故障注入和分层评测。

不把项目描述成“任意数据都能直接分析的生产平台”，也不声称已经具备正式多租户、高可用和无限并发能力。

## 2. 当前基础和范围

已有能力：

- Supervisor 路由通用、知识、数据和协作模式。
- LangGraph 分析图：计划、Schema/指标检索、SQL 生成、AST 安全校验、业务一致性校验、审批、执行和总结。
- 项目二 RAG Evidence API，支持版本、权限、引用和拒答。
- PostgreSQL Checkpoint、审批恢复、请求幂等、SSE、Trace 和审计。
- 数据集上传、字段画像、字段映射、指标确认和 ready 状态。
- development、frozen、跨数据集和检索评测基础。

本阶段不做：

- 不更换 Python、FastAPI、LangGraph、PostgreSQL 主技术栈。
- 不新增金融、招聘、客服、合同审查等无关业务模块。
- 不为了热点引入新的 Agent 平台或编排框架。
- 不把受控测试集结果写成生产环境准确率。
- 不实现正式注册、多租户、高可用集群和分布式网关限流。

## 3. 总体架构

请求入口
→ AgentRun（统一 run_id / request_id / thread_id / 预算）
→ Supervisor 路由
→ ContextBuilder（权限过滤、Token 预算、上下文快照）
→ LangGraph 工作流
→ Skill / Tool Contract 校验
→ Data Agent / Knowledge Agent / MCP
→ Checkpoint 与幂等边界
→ Trace Event
→ 分层评测与失败归因

核心原则：

1. 模型负责提出计划，代码负责边界和执行。
2. Checkpoint 保证可恢复，不承诺天然 exactly-once；外部副作用必须使用稳定幂等键。
3. RAG 证据和 SQL 结果都必须带来源、版本和权限信息。
4. 每个失败都要有明确组件归属和可复现实验。

## 4. 分阶段升级

### 阶段 1：统一 AgentRun Harness

目标：给所有 Agent 请求提供统一运行时边界。

建议文件：

- 新增 src/retail_analytics_agent/agent_runtime.py
- 修改 agent_models.py、agent_service.py、zhishu_service.py、settings.py
- 新增 tests/test_agent_runtime.py

AgentRun 至少包含：

- run_id、request_id、thread_id、user_id、mode
- state_version、deadline、status、terminal_reason
- step_count、model_call_count、tool_call_count、token_budget

运行时规则：

- 每一步开始前检查总截止时间。
- 超过最大步骤、模型调用、工具调用或 Token 预算时停止。
- 需要副作用的工具必须带幂等键。
- 模型超时、工具超时、数据库不可用分别记录不同错误类型。
- 终止状态统一为 succeeded、partial_success、failed、waiting_approval、cancelled 或 budget_exceeded。

验收标准：

- 正常查询能完成，并记录完整计数。
- 模型超时只有限重试，不会无限循环。
- 超过预算时停在明确节点并返回可理解的降级信息。
- 重试同一个请求不会重复写入请求登记或外部副作用。
- 新增行为有单元测试和至少一个端到端测试。

### 阶段 2：Context Engineering 实装

目标：确认上下文快照真正进入模型调用，而不是只保存在 State 中。

建议文件：

- context_builder.py、context_store.py、model_adapters.py、workflow.py、agent_models.py
- 新增 tests/test_context_runtime.py

上下文分层：

1. 系统规则
2. 当前用户问题
3. 业务指标和 Schema
4. RAG / 数据证据
5. 历史对话和工具结果

每层记录 source_id、priority、token_cost、permission_scope 和 content_hash。

必须实现：

- 模型调用前统一构建上下文，各节点不能随意拼接。
- 按优先级裁剪：当前问题、权限规则、指标口径和证据优先于旧历史。
- 无权限、过期和重复证据不得进入模型上下文。
- 记录入选内容、裁剪内容、Token 预算和估算方式。
- Token 计数封装为可替换接口；没有 Qwen tokenizer 时使用保守估算并标记方式。

验收标准：

- 测试能证明模型节点收到的 prompt 包含当前 ContextSnapshot。
- 超预算时仍保留权限规则、指标口径和当前证据。
- 无权限证据不会出现在 prompt、Trace 或最终答案。
- 相同上下文快照能生成相同输入哈希。

### 阶段 3：Skill / Tool Contract 强校验

目标：把 Skill 和 Tool 从模型参考描述升级为运行时强制契约。

建议文件：

- skills.py、tool_registry.py、agent_tools.py、workflow_tools.py、common_tools.py
- 新增 tests/test_skill_contracts.py、tests/test_tool_contracts.py

ToolContract 至少包含：

- name、input_schema、output_schema
- required_role、allowed_resources、side_effect_level
- timeout_seconds、retry_policy、idempotency_required
- preconditions、postconditions

SkillContract 至少包含：

- skill_id、trigger_description、input_schema、allowed_tools
- required_evidence、completion_conditions、failure_conditions、output_schema

知识查询 Skill 的完成条件示例：

- 至少有一条当前用户有权限的证据。
- 每个结论都能关联 source_id。
- 证据不足时必须拒答或标记缺口。
- 不得引用已过期版本。

验收标准：

- 未知工具参数在调用前被拒绝。
- 未授权角色无法调用工具，即使模型选择了该工具。
- 工具返回值不符合 Schema 时不能进入总结节点。
- 缺少必要证据时 Skill 不能标记成功。
- 每个工具至少有正常、参数错误、权限拒绝、超时四类测试。

### 阶段 4：Permission 全链路闭环

目标：把权限从入口检查扩展为每个资源访问点的统一授权。

建议文件：

- access_control.py、dataset_scope.py、knowledge.py、knowledge_store.py
- agent_tools.py、analysis_service.py
- 新增 tests/test_permission_matrix.py

统一接口：

authorize(user, action, resource, purpose) -> AuthorizationDecision

必须在以下环节校验：

路由 → 数据集选择 → Schema / 指标检索 → SQL 生成 → SQL 执行 → RAG 召回 → 证据返回 → Trace 查看 → 审批恢复。

验收标准：

- 分析员只能查询已授权数据集和字段。
- RAG 在召回前过滤无权限文档。
- 权限变化后，旧 Checkpoint 恢复时重新授权。
- 未授权数据不会出现在 rows、evidence、prompt、Trace 和导出报告。
- 权限矩阵至少覆盖 analyst、admin、无权限用户和过期权限。

### 阶段 5：State / Memory / Checkpoint 分层

目标：明确临时工作状态、可恢复 Checkpoint 和跨请求记忆的边界。

三类状态：

- Working State：当前节点运行所需的临时值。
- Checkpoint：可以恢复的完整工作流状态。
- Conversation Memory：跨请求保留的用户对话和偏好。

Checkpoint 必须带：

thread_id、request_id、state_version、last_completed_node、next_node、created_at、expires_at。

恢复规则：

- 校验当前用户、请求归属和状态版本。
- 审批恢复前重新检查权限和审批状态。
- 外部副作用执行前以 request_id + phase 检查幂等记录。
- 已完成的只读节点可以复用结果，不重复调用模型或数据库。
- 状态版本不兼容时明确失败，不静默读取旧字段。

验收标准：

- SSE 断开后用同一 thread_id 可以继续未完成任务。
- 任意节点模拟进程重启，恢复后不丢失已完成证据和 SQL。
- 恢复同一审批两次不会产生两条终态副作用。
- 过期 Checkpoint、错误用户和旧版本状态都会被拒绝。

### 阶段 6：结构化 Trace 与失败归因

目标：让一次错误可以从 Trace 中定位到具体层级。

TraceEvent 建议包含：

run_id、parent_event_id、node、attempt、event_type、status、input_hash、output_hash、context_snapshot_id、selected_source_ids、tool_name、tool_args_hash、policy_decision、latency_ms、token_usage、error_type、error_message。

错误分类固定为：

model、context、tool、skill、state、permission、memory、runtime。

安全要求：

- 不记录 API Key、密码、未脱敏敏感字段或完整大段企业文档。
- 保留哈希、摘要、来源 ID 和必要的脱敏元数据。

验收标准：

- 可以按 run_id 查看完整父子事件链。
- 每个失败事件都有组件分类、节点、尝试次数和错误类型。
- 固定输入和故障规则下，Trace 顺序和错误归因可重复。
- 普通用户看不到不属于自己的完整 Trace。

### 阶段 7：故障注入和恢复测试

目标：主动验证异常路径，而不是只验证成功路径。

故障类型至少包括：

model_timeout、model_invalid_json、tool_timeout、tool_unauthorized、rag_empty_evidence、sql_ast_rejected、business_check_failed、database_unavailable、checkpoint_corrupted、approval_resume_duplicate、sse_disconnect。

每个故障都验证：

- 是否在正确节点停止。
- 是否按策略重试。
- 是否保留已成功分支。
- 是否产生重复副作用。
- 是否返回明确降级。
- 是否能恢复或安全终止。
- Trace 是否归因到正确层级。

建议新增：

- fault_injection.py 的场景开关或注入器。
- tests/test_fault_matrix.py。
- evaluation/fault_cases.jsonl。

### 阶段 8：分层 Evaluation 与回归门禁

目标：用数据证明升级有效，并防止后续改动倒退。

按八层统计：

| 层级 | 指标 |
| --- | --- |
| Model | 计划正确率、结构化输出合格率 |
| Context | 上下文命中率、证据覆盖率、Token 超预算率 |
| Tool | 工具选择率、参数通过率、工具成功率 |
| Skill | 完成条件满足率、越界率 |
| State | Checkpoint 恢复率、状态一致性 |
| Permission | 授权正确率、错误放行率、权限泄漏率 |
| Memory | 记忆命中率、错误记忆率 |
| Runtime | 成功率、部分成功率、超时率、P50/P95、重复副作用率 |

评测集分四类：

1. 契约测试：验证 Tool、Skill、State、Permission 边界。
2. 端到端测试：验证用户问题到最终回答。
3. 故障注入测试：验证失败、降级和恢复。
4. 冻结集测试：固定模型、数据库快照和策略，只做一次性验收。

回归门禁：

- frozen 集不允许权限泄漏。
- Tool 合约测试全部通过。
- Checkpoint 恢复测试全部通过。
- 关键链路成功率不能低于上一基线。
- 延迟或 Token 成本明显上升时，必须在报告中说明。
- 指标变化要保存原始记录、配置快照和版本号。

建议涉及文件：

- evaluation_observation.py、evaluation_runtime.py、evaluation_executors.py
- 新增 evaluation/agent_harness_development.jsonl
- 新增 evaluation/agent_harness_frozen.jsonl
- 更新 docs/EVALUATION_PROTOCOL.md 和 .github/workflows/ci.yml

## 5. 推荐执行顺序

1. AgentRun Harness
2. Context 实装
3. Tool / Skill Contract
4. Permission 闭环
5. State / Memory / Checkpoint
6. Trace 失败归因
7. 故障注入
8. 分层 Evaluation 与 CI 门禁

不要一次修改全部模块。每完成一个阶段，必须：

1. 先写或补测试。
2. 修改最小范围代码。
3. 运行相关测试和完整回归。
4. 记录实际结果，不编造指标。
5. 更新 README 或评测协议。
6. 交给 Codex 做代码审查后再进入下一阶段。

## 6. 给 Claude 的执行要求

- 先阅读 README.md、AGENTS.md、docs/ARCHITECTURE.md、docs/EVALUATION_PROTOCOL.md 和相关测试。
- 不要重写现有工作流，不要删除现有测试。
- 每次只完成一个阶段，并先说明准备修改的文件和接口。
- 所有行为变化必须有测试。
- 不要把 deterministic fixture 结果写成远程模型效果。
- 不要泄露或提交 .env 中的密钥。
- 无法真实运行的功能要明确标注“已实现但未在真实环境验证”。
- 完成后输出修改文件、测试命令、测试结果、已知限制和下一阶段建议。

## 7. 最终完成定义

只有同时满足以下条件，才可以称本次升级完成：

- 每次 Agent 运行都有统一预算、状态和终止原因。
- ContextSnapshot 确实进入模型调用，并能追踪裁剪结果。
- Tool、Skill、Permission 的关键约束由代码强制校验。
- Checkpoint 恢复有状态版本和幂等保护。
- Trace 能把故障归因到八个层级之一。
- 故障注入覆盖正常、超时、权限、恢复和部分成功场景。
- development 与 frozen 评测都保存原始记录。
- CI 能阻止权限泄漏、合约破坏和恢复回归。
- 文档如实区分“已实现”“已测试”和“尚未生产验证”。

## 8. 面试时的简短表述

> 我下一步没有继续堆新的 Agent 框架，而是给现有系统补了一层 Runtime 和 Evaluation。每次 Agent 执行都有步骤、Token、模型调用和工具调用预算；上下文、工具、Skill、权限和 Checkpoint 都有明确契约；Trace 会记录每个节点的输入摘要、状态和错误类型。然后我通过故障注入分别模拟模型超时、RAG 无证据、SQL 校验失败、权限拒绝和断线恢复，再用冻结集验证升级前后的成功率、延迟、Token 和权限泄漏情况。这样我可以判断问题究竟来自 Model、Context、Tool、State 还是 Runtime，而不是只看最后回答对不对。

## 9. 与原始升级要求的逐项对照

下面这份清单用于 Claude 执行时逐项打勾，避免只实现了标题却漏掉关键行为。

### Agent Harness

- [ ] AgentRun 包含 run_id、request_id、thread_id、user_id、mode、state_version、started_at、deadline、step_count、model_call_count、tool_call_count、token_budget、status、terminal_reason。
- [ ] 有最大步骤数、最大模型调用数、最大工具调用数、总超时、单节点超时和最大重试次数。
- [ ] 能检测同一阶段重复动作，并用稳定 action_key 或 request_id + phase 做幂等保护。
- [ ] SSE 断开默认不取消后台任务；显式取消才进入 cancelled。
- [ ] SSE 重连使用同一 request_id/thread_id 查看已有状态，不重新创建任务。
- [ ] 超出预算进入 budget_exceeded 或明确的部分成功/失败状态，不继续重试。

### Context Engineering

- [ ] 上下文按系统规则、当前任务、业务口径/Schema、检索证据、历史对话/工具结果五层组织。
- [ ] 每层有 source_id、priority、token_cost、created_at、permission_scope、content_hash。
- [ ] 模型实际收到统一构建的上下文，而不是只在 State 中保存 ContextSnapshot。
- [ ] 调用前执行 Token 计算、优先级裁剪、过期过滤、权限过滤和重复证据去重。
- [ ] 记录入选内容、裁剪内容、Token 预算、实际/估算计数方式。
- [ ] 有可替换的 TokenCounter 接口；中文估算不足时采用保守策略。
- [ ] 测试可以证明 ContextSnapshot 的内容确实进入模型输入。

### Tool / Skill Contract

- [ ] ToolContract 具备名称、输入/输出 Schema、角色、资源范围、副作用等级、超时、重试、幂等、前置条件和后置条件。
- [ ] 销售数据工具输入包含 dataset_id、metric、dimensions、time_range、filters。
- [ ] 销售数据工具输出包含 rows、metric_definition、dataset_version、sql_hash、execution_time、warnings。
- [ ] 输入缺字段、未知字段、未授权、数据集非 ready、指标未确认、输出不符合 Schema 时都由代码拒绝。
- [ ] Skill 具备触发条件、输入格式、执行步骤、允许工具、完成条件、失败条件和输出格式。
- [ ] Skill 的完成/失败条件由代码校验，不依赖 Prompt 自觉。
- [ ] 知识查询完成条件包括：有权限证据、结论可关联 source_id、证据不足拒答、不能引用过期版本。
- [ ] 每个工具都有正常、参数错误、权限拒绝、超时和重复调用测试。

### Permission

- [ ] 统一 authorize(user, action, resource, purpose) 接口。
- [ ] 路由、数据集选择、Schema/指标检索、SQL 生成、SQL 执行、RAG 召回、证据返回、Trace 查看、审批恢复全部重新授权。
- [ ] 支持数据集级、行级、字段级和敏感字段过滤。
- [ ] RAG 使用召回前 pre-filter，不能只在召回后丢弃无权限文档。
- [ ] 权限变化后，旧 Checkpoint 恢复必须重新授权。
- [ ] 授权决定记录 subject、action、resource、decision、reason、policy_version。
- [ ] 权限测试覆盖错误放行、错误拒绝、权限泄漏和过期权限。

### State / Memory / Checkpoint

- [ ] Working State、Checkpoint、Conversation Memory 在类型和职责上分开。
- [ ] Checkpoint 包含 thread_id、request_id、state_version、last_completed_node、next_node、created_at、expires_at。
- [ ] 恢复时检查用户、请求归属、状态版本、审批有效性、前序节点和外部副作用记录。
- [ ] 明确“Checkpoint 可恢复，不等于 exactly-once”。
- [ ] 外部副作用执行前检查稳定幂等键；已完成则复用结果。
- [ ] SSE 断线、进程重启、重复审批、过期状态和错误用户都有测试。

### Trace

- [ ] TraceEvent 包含 run_id、parent_event_id、node、attempt、event_type、status、input_hash、output_hash、context_snapshot_id、selected_source_ids、tool_name、tool_args_hash、policy_decision、latency_ms、token_usage、error_type、error_message。
- [ ] 支持按时间查看完整链路、按组件/错误筛选、按请求回放。
- [ ] 错误类型固定映射到 Model、Context、Tool、Skill、State、Permission、Memory、Runtime。
- [ ] 不记录 API Key、密码、完整敏感数据或未脱敏文档。
- [ ] 固定输入和故障规则下，Trace 顺序和归因可重复。

### 故障注入

- [ ] 覆盖 model_timeout、model_invalid_json、tool_timeout、tool_unauthorized、rag_empty_evidence、sql_ast_rejected、business_check_failed、database_unavailable、checkpoint_corrupted、approval_resume_duplicate、sse_disconnect。
- [ ] 每种故障验证停止节点、重试次数、成功分支保留、重复副作用、降级信息、恢复结果和 Trace 归因。
- [ ] 复合问题支持 partial_success：一路成功、一路失败时保留成功结果并明确缺失部分。

### Evaluation

- [ ] 分别统计 Model、Context、Tool、Skill、State、Permission、Memory、Runtime 八层指标。
- [ ] 同时具备契约测试、端到端测试、故障注入测试和冻结集测试。
- [ ] 冻结集固定模型、Prompt/策略、代码版本、数据库快照、数据集版本和运行配置，不能用于调参。
- [ ] 每次评测保存原始 Trace、配置快照、版本号和汇总指标。
- [ ] 回归门禁至少阻止权限泄漏、契约破坏、Checkpoint 恢复失败和关键成功率下降。
