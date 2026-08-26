# 阶段3：路由、规划和 Skill 契约补强 实施报告（2026-08-26）

> 交接来源：`docs/CLAUDE_UPGRADE_HANDOFF.md` 阶段3
> 仓库：`E:\qiuzhaoxiangmu\zhishu-nexus`（分支 main，HEAD a36d105）

## 一、本阶段理解与计划

企业 Agent 链路（`/agent/run`）的路由由 `Supervisor`（纯关键词 → `AgentMode`）、
`SkillRegistry`（纯关键词 → `SkillId`）和 `TaskPlanner`（模板/模型 → `TaskPlan`）组成。
阶段3要把"清晰/模糊/追问/复合任务"变成可解释的结构化决策，并升级 Skill 契约为可执行契约。

按交接文档实施四层流水线：**确定性前置规则 → LLM 结构化路由 → Pydantic + 业务代码校验
→ 低置信度澄清或安全兜底**；结构化结果含 `mode / confidence / subtasks /
missing_information / reason_code`；规则层新增空问题、写操作、越权、敏感字段、数据集
不存在/未 ready 拦截；Skill 首期升级销售分析相关 4 个 Skill。

## 二、实际修改文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/retail_analytics_agent/agent_models.py` | 修改 | 新增 `RoutingDecision`（mode/confidence/subtasks/missing_information/reason_code/reason/refused）；`Subtask` 加 `depends_on`；`TaskPlan` validator 加依赖环检测；`AgentRequest` 加 `dataset_id`（≤80）/`dataset_version`（≥1） |
| `src/retail_analytics_agent/supervisor.py` | 修改 | `AgentPlan` 加 `confidence`/`reason_code`/`missing_information`/`refused`；`Supervisor` 重构为四层路由：`_apply_rules`（空问题/写操作/越权/敏感字段/数据集状态）→ `_keyword_decision`（原关键词逻辑 + 置信度/模糊判定）→ `_llm_decision`（`StructuredChatClient.complete_json` 结构化路由，失败降级）→ 代码层校验 + 低置信度澄清；`route()` 返回 `RoutingDecision`，`plan()` 转 `AgentPlan` |
| `src/retail_analytics_agent/skills.py` | 修改 | `SkillDefinition` 加 `version`/`required_inputs`/`allowed_roles`；4 个销售分析 Skill（退款诊断/渠道对比/商品分析/周报）全部填充契约字段 |
| `src/retail_analytics_agent/zhishu_service.py` | 修改 | `_prepare` 把 `access_role`/`dataset_id`/`dataset_version` 传给 `supervisor.plan`；`run`/`stream` 消费 `plan.refused`（拒绝）与 `plan.missing_information`（低置信度澄清），新增 `_refused_response`/`_clarification_response` |
| `src/retail_analytics_agent/agent_service.py` | 修改 | `_ensure_role_allows` 校验 Skill `allowed_roles`；`sql.query` 工具参数透传 `dataset_id`/`dataset_version` |
| `src/retail_analytics_agent/agent_tools.py` | 修改 | `SQLAnalysisInput` 加 `dataset_id`/`dataset_version`，`run_sql` 构造 `AnalysisRequest` 时透传 |
| `src/retail_analytics_agent/app.py` | 修改 | `get_agent_service` 为 `Supervisor` 注入 `model`（`StructuredChatClient`）+ `_dataset_status_checker()`（基于 `DatasetRegistry` 返回 `ready` 状态） |
| `tests/test_agent_routing_contract.py` | **新增** | 25 个阶段3契约测试（见下） |

## 三、为什么按这种方式实现

- **Supervisor 单一入口承载四层**：现有 `Supervisor` 就是企业 Agent 链路的顶层路由。
  把规则/关键词/LLM/代码校验四层收敛进 `route()`，`plan()` 只负责转成执行计划，
  调用方（`zhishu_service`）无需感知路由细节；无模型时 `route()` 完全保持原关键词行为，
  现有 `Supervisor()` 测试零回归。
- **模型不能自选 schema，数据集由规则层强校验**：`dataset_checker` 是注入的
  `Callable[[str, int|None], str|None]`，返回 `None` 记 `dataset_not_found`、非
  `ready` 记 `dataset_not_ready` 并 `refused=True`，避免请求进入数据链路才被拒。
- **LLM 只负责意图，子任务仍由代码层生成**：LLM 输出 `mode/confidence/missing_information/
  reason_code`，`steps` 由 `_steps(mode)` 确定性生成（agent/工具白名单安全），
  `subtasks` 仅作为结构化决策证据记录——符合"代码负责子任务数量、依赖环和工具白名单"。
- **低置信度只在缺口径时澄清**：`plan` 仅当 `confidence < min_confidence` 时保留
  `missing_information`，高置信度请求即使 LLM 附带了缺口也正常执行，避免过度追问。
- **拒绝写安全兜底，敏感字段交审批流**：规则层直接拒绝空问题/写操作/越权/数据集异常；
  敏感字段请求不拒绝，而是高置信路由到 DATA 模式，交由既有审批链路兜底。
- **dataset 从 AgentRequest 贯穿到 AnalysisRequest**：`AgentRequest` → `sql.query` 工具 →
  `AnalysisRequest` 全程透传，阶段2的分析链路 `dataset_scope` 得以在企业 Agent 链路复用。

## 四、新增/修改的测试

新增 `tests/test_agent_routing_contract.py` 25 个：

- 规则层：空问题拒绝、写操作拒绝、越权（analyst 拒绝 / admin 放行）、敏感字段路由
  DATA+审批、数据集 not_found / not_ready / ready 通过 / checker 不可用转澄清。
- 结构化路由：`RoutingDecision` 含全部五个字段、关键词高置信、模糊请求低置信 +
  missing_information、`AgentPlan` 结构化字段。
- LLM 路由：mock 模型覆盖低置信关键词、模型失败降级关键词、高置信忽略
  missing_information、非 JSON 输出忽略。
- Skill 契约：4 个 Skill 均声明 version/required_inputs/allowed_roles 且含 `sql.query`。
- 依赖环：`depends_on` 指向未知 id 拒绝、环形依赖拒绝、无环通过。
- 服务消费：写操作在服务层 REFUSED、模糊问题返回澄清文案、非 ready 数据集
  REFUSED、ready 数据集进入执行且 `dataset_id` 透传到 data agent。

现有测试无修改、无弱化；全量 643 通过。

## 五、完整测试命令和真实输出

```powershell
cd E:\qiuzhaoxiangmu\zhishu-nexus
.\.venv\Scripts\python.exe -m pytest tests\test_agent_routing_contract.py -q
# 25 passed

.\.venv\Scripts\python.exe -m pytest
# 643 passed in 11.05s
```

完整全量输出：`643 passed in 11.05s`（阶段2为 618，新增 25），无 failed/error/skipped。

## 六、已知边界和未完成项

- LLM 结构化路由依赖模型返回合法 JSON；失败/非 JSON 自动降级到关键词层，不会抛错。
- 敏感字段识别复用 `access_control.requested_sensitive_columns`（仅 `refunds.reason`），
  其余列若未来扩展敏感字段清单需同步。
- `RoutingDecision.subtasks` 目前作为决策记录，未反向改写 `AgentPlan.steps`（steps 由
  mode 确定性生成，白名单更安全）；若需模型级子任务拆解落地可在后续阶段放开。
- Skill `allowed_roles` 当前为 analyst+admin，尚未接入"用户→数据集"独立 ACL（同阶段2边界）。
- 数据集前置校验只覆盖企业 Agent 链路入口；分析链路自身仍由阶段2 workflow scope 节点兜底。

## 七、git diff --stat 与 git status --short

```
7 files changed, 522 insertions(+), 21 deletions(-)
```

`git status --short`：

```
 M src/retail_analytics_agent/agent_models.py
 M src/retail_analytics_agent/agent_service.py
 M src/retail_analytics_agent/agent_tools.py
 M src/retail_analytics_agent/app.py
 M src/retail_analytics_agent/skills.py
 M src/retail_analytics_agent/supervisor.py
 M src/retail_analytics_agent/zhishu_service.py
?? docs/CLAUDE_UPGRADE_HANDOFF.md
?? tests/test_agent_routing_contract.py
```
