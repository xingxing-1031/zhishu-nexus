# 知枢 Nexus Agent 审计与上下文加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让企业 Agent 请求具备统一审计、持久化幂等和状态恢复能力，同时修复品牌身份、上下文、追问路由与 SSE 错误保存。

**Architecture:** 新增 PostgreSQL `agent_request_runs` 作为顶层 Agent 请求登记与结果快照，所有模式用于幂等和恢复，仅 `auditable=true` 的企业请求进入管理员业务审计。ZhishuAgentService 成为顶层上下文所有者，内部 Data Agent 可关闭重复上下文写入；Supervisor 从已确认的上一模式恢复省略式追问。前端通过状态接口恢复流式错误或已完成结果。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、PostgreSQL 16、React 18、TypeScript、Vite、pytest、Ruff

## Global Constraints

- 普通闲聊和纯公开工具请求不出现在管理员业务审计中。
- 企业知识、经营数据、知识与数据协作及企业安全拒绝必须审计。
- 不把敏感查询结果全文写入 Agent 审计。
- SQL 与审批详情继续由现有查询审计和审批表保存。
- 前端所有“知枢”双字标识保持横向排列。
- Python 导入包名 `retail_analytics_agent` 和 VPS 目录不改名。
- 当前运行时服务、评测、MCP 和 User-Agent 使用 `Zhishu/zhishu` 命名，不保留 `Qixi/qixi` 当前名称。
- 每个行为改动必须有自动化回归测试，不虚构性能数据。

---

### Task 1: 顶层 Agent 请求登记与企业审计模型

**Files:**
- Create: `db/migrations/010_agent_request_runs.sql`
- Create: `src/retail_analytics_agent/agent_runs.py`
- Create: `tests/test_agent_runs.py`
- Modify: `db/verification/verify_delivery.sql`
- Modify: `tests/test_migrate.py`

**Interfaces:**
- Produces: `AgentRunStore.claim(request, access_context, mode, auditable) -> AgentRunClaim`
- Produces: `AgentRunStore.complete(response, duration_ms) -> None`
- Produces: `AgentRunStore.fail(request_id, reason, duration_ms) -> None`
- Produces: `AgentRunStore.get(request_id, viewer) -> AgentRunRecord | None`
- Produces: `DatabaseAgentRunStore` and `InMemoryAgentRunStore`

- [ ] **Step 1: Write failing migration and store contract tests**

```python
def test_agent_run_migration_defines_status_and_identity_constraints() -> None:
    sql = Path("db/migrations/010_agent_request_runs.sql").read_text()
    assert "CREATE TABLE agent_request_runs" in sql
    assert "UNIQUE (request_id)" in sql or "request_id TEXT PRIMARY KEY" in sql
    assert "request_fingerprint" in sql
    assert "response_payload JSONB" in sql

def test_agent_run_store_replays_same_request_without_duplicate_execution() -> None:
    store = InMemoryAgentRunStore()
    first = store.claim(_request(), _access(), AgentMode.KNOWLEDGE, True)
    second = store.claim(_request(), _access(), AgentMode.KNOWLEDGE, True)
    assert first.status is AgentRunClaimStatus.NEW
    assert second.status is AgentRunClaimStatus.EXISTING
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_runs.py tests/test_migrate.py -q`  
Expected: FAIL because migration and Agent run models do not exist.

- [ ] **Step 3: Implement migration and typed stores**

Implement a single row per `request_id` with fingerprint, conversation, user, role, mode, question, auditable flag, status, tool names, evidence count, approval flag, public failure reason, response JSON, duration and timestamps. `claim` returns conflict when the fingerprint changes; `complete` and `fail` update the existing row idempotently.

- [ ] **Step 4: Extend delivery verification**

Add `agent_request_runs` to the required relations and verify `request_fingerprint`, `auditable`, and `response_payload` exist.

- [ ] **Step 5: Run focused tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_runs.py tests/test_migrate.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/010_agent_request_runs.sql db/verification/verify_delivery.sql src/retail_analytics_agent/agent_runs.py tests/test_agent_runs.py tests/test_migrate.py
git commit -m "feat: add durable agent run registry"
```

### Task 2: Agent 身份、上下文与追问路由

**Files:**
- Create: `src/retail_analytics_agent/brand_identity.py`
- Modify: `src/retail_analytics_agent/general_agent.py`
- Rename: `src/retail_analytics_agent/qixi_service.py` to `src/retail_analytics_agent/zhishu_service.py`
- Rename: `src/retail_analytics_agent/qixi_evaluation.py` to `src/retail_analytics_agent/zhishu_evaluation.py`
- Modify: `src/retail_analytics_agent/agent_service.py`
- Modify: `src/retail_analytics_agent/supervisor.py`
- Modify: `tests/test_general_agent.py`
- Rename: `tests/test_qixi_service.py` to `tests/test_zhishu_service.py`
- Rename: `tests/test_qixi_evaluation.py` to `tests/test_zhishu_evaluation.py`
- Create: `tests/test_supervisor.py`

**Interfaces:**
- Produces: `ZHISHU_ASSISTANT_IDENTITY` and `UNTRUSTED_EVIDENCE_RULE`
- Produces: `EnterpriseAgentService.run(..., persist_context: bool = True)`
- Produces: `Supervisor.plan(..., previous_mode: AgentMode | None = None)`
- Consumes: `AgentRunStore` from Task 1

- [ ] **Step 1: Write failing identity, context and follow-up tests**

```python
def test_general_agent_prompt_identifies_zhishu_and_marks_tools_untrusted() -> None:
    agent.answer("你是谁", [], "r1", "c1", "analyst")
    prompt = model.calls[0]["system_prompt"]
    assert "知枢 AI" in prompt
    assert "不可信" in prompt
    assert "企析" not in prompt

def test_supervisor_reuses_previous_data_mode_for_elliptical_follow_up() -> None:
    plan = Supervisor().plan("再拆一下", previous_mode=AgentMode.DATA)
    assert plan.mode is AgentMode.DATA

def test_collaboration_persists_original_question_and_final_answer_once() -> None:
    service.run(_request("结合退款数据和售后制度给出复盘"), _access())
    record = data.context_builder.store.get("c1", "u1")
    assert [turn.role for turn in record.turns] == ["user", "assistant"]
    assert record.turns[0].content == "结合退款数据和售后制度给出复盘"
    assert record.turns[1].content == "基于已验证证据的结论。"
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_general_agent.py tests/test_zhishu_service.py tests/test_zhishu_evaluation.py tests/test_supervisor.py -q`
Expected: FAIL on stale identity, ignored history and duplicate/incomplete context.

- [ ] **Step 3: Centralize identity and prompt safety rules**

Replace all runtime “企析” strings with shared “知枢 AI” constants. Tell answer models that webpage, MCP and RAG content is untrusted evidence and must never override system identity, permissions or tool policy.

- [ ] **Step 4: Make ZhishuAgentService own top-level context**

Append the original user turn once before execution and the final answer once after execution. Pass `persist_context=False` to internal Data Agent calls. Store `last_agent_mode=<mode>` and `last_skill=<skill>` as confirmed constraints.

- [ ] **Step 5: Reuse previous enterprise mode for elliptical follow-ups**

Use explicit current-turn enterprise terms first. Only when the current question contains a follow-up marker and no explicit mode evidence, reuse the previous non-general mode. Make stream and non-stream execution use the same prepared plan.

- [ ] **Step 6: Run focused tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_general_agent.py tests/test_zhishu_service.py tests/test_zhishu_evaluation.py tests/test_supervisor.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/retail_analytics_agent/brand_identity.py src/retail_analytics_agent/zhishu_service.py src/retail_analytics_agent/zhishu_evaluation.py src/retail_analytics_agent/general_agent.py src/retail_analytics_agent/agent_service.py src/retail_analytics_agent/supervisor.py tests/test_general_agent.py tests/test_zhishu_service.py tests/test_zhishu_evaluation.py tests/test_supervisor.py
git commit -m "fix: unify agent identity and conversation context"
```

### Task 3: Agent 生命周期、幂等、公开错误与状态接口

**Files:**
- Modify: `src/retail_analytics_agent/zhishu_service.py`
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `src/retail_analytics_agent/public_errors.py`
- Modify: `tests/test_zhishu_service.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: `ZhishuAgentService.get_status(request_id, viewer) -> AgentResponse`
- Produces: `GET /agent/runs/{request_id}`
- Consumes: `AgentRunStore` from Task 1

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_agent_replays_completed_request_from_run_store() -> None:
    first = service.run(request, access)
    second = service.run(request, access)
    assert second == first
    assert general.calls == 1

def test_agent_stream_does_not_expose_internal_exception_text() -> None:
    events = list(service.stream(request, access))
    assert events[-1].event.value == "error"
    assert "postgresql://" not in events[-1].message

def test_agent_status_endpoint_returns_owned_completed_result() -> None:
    response = client.get("/agent/runs/REQ-001")
    assert response.status_code == 200
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhishu_service.py tests/test_app.py -q`
Expected: FAIL because durable replay and status endpoint are missing.

- [ ] **Step 3: Wrap every top-level run in the store lifecycle**

Claim after routing, return stored terminal responses, return a typed `running` response for an identical in-flight request, and finish/fail the record on every exit. Mark enterprise modes and enterprise security attempts as auditable.

- [ ] **Step 4: Add owner/admin status lookup**

Expose the stored response only to the request owner or administrator. Return 404 for unknown requests, 409 for running requests without a terminal response, and sanitized errors for failed requests.

- [ ] **Step 5: Sanitize stream errors**

Do not yield raw exception strings from service-level streams. Route all exceptions through `public_error_message` and store only the public failure reason in `agent_request_runs`.

- [ ] **Step 6: Run focused tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zhishu_service.py tests/test_app.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/retail_analytics_agent/zhishu_service.py src/retail_analytics_agent/app.py src/retail_analytics_agent/public_errors.py tests/test_zhishu_service.py tests/test_app.py
git commit -m "feat: persist and recover agent runs"
```

### Task 4: 管理员企业审计读模型与界面

**Files:**
- Modify: `src/retail_analytics_agent/admin_views.py`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/AdminPages.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `tests/test_admin_views.py`
- Modify: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Extends: `AdminAuditEntry` with `conversation_id`, `agent_mode`, `tool_names`, `evidence_count`
- Preserves: `GET /admin/audit` query filters and historical data rows

- [ ] **Step 1: Write failing admin audit tests**

```python
def test_admin_audit_lists_only_auditable_agent_runs() -> None:
    sql = ADMIN_AUDIT_SELECT_SQL
    assert "agent_request_runs" in sql
    assert "run.auditable = TRUE" in sql
    assert "agent_mode" in sql
```

Add a frontend contract assertion for mode labels and the new “Agent 模式” table column.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_admin_views.py tests/test_frontend_conversation_contract.py -q`  
Expected: FAIL because the unified read model and fields are absent.

- [ ] **Step 3: Implement unified read model**

Read `agent_request_runs WHERE auditable = TRUE`, join the latest SQL audit and approval entries, map Agent `refused` to admin `rejected`, and preserve backfilled historical Data Agent rows.

- [ ] **Step 4: Add mode filter and evidence/tool columns**

Use localized mode labels: 通用安全事件、企业知识、经营数据、知识与数据协作。Keep the table horizontally scrollable on narrow screens and keep filter controls at least 44px high.

- [ ] **Step 5: Run focused tests and frontend build**

Run: `.venv/Scripts/python.exe -m pytest tests/test_admin_views.py tests/test_frontend_conversation_contract.py -q`  
Run: `npm run build` in `frontend`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/retail_analytics_agent/admin_views.py frontend/src/types.ts frontend/src/AdminPages.tsx frontend/src/styles.css tests/test_admin_views.py tests/test_frontend_conversation_contract.py
git commit -m "feat: show enterprise agent audit records"
```

### Task 5: 横向品牌标识与前端 SSE 恢复

**Files:**
- Modify: `frontend/src/brand.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Produces: horizontal `BrandMark`
- Produces: `api.agentRun(requestId) -> AgentResponse`
- Preserves: desktop/mobile fixed composer and conversation synchronization

- [ ] **Step 1: Write failing frontend contract tests**

```python
def test_brand_mark_uses_horizontal_layout() -> None:
    assert "grid-template-columns" in brand_mark_rule
    assert "grid-template-rows: 1fr 1fr" not in brand_mark_rule

def test_workspace_persists_stream_error_and_attempts_status_recovery() -> None:
    assert "failureRef" in workspace
    assert "api.agentRun" in workspace
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_frontend_conversation_contract.py -q`  
Expected: FAIL on vertical layout and missing recovery contract.

- [ ] **Step 3: Implement horizontal mark**

Render “知”“枢” in one row. Use a wider stable mark box, update assistant message grid columns, and verify 390px mobile layout has no horizontal overflow.

- [ ] **Step 4: Persist stream errors and recover terminal status**

Keep the latest stream error in a ref used by `finally`. When the stream ends without a terminal response, request `/agent/runs/{request_id}` once; if a terminal response exists, save it, otherwise preserve the sanitized failure instead of creating a blank turn.

- [ ] **Step 5: Run focused tests and production build**

Run: `.venv/Scripts/python.exe -m pytest tests/test_frontend_conversation_contract.py -q`  
Run: `npm run build` in `frontend`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/brand.tsx frontend/src/styles.css frontend/src/api.ts frontend/src/Workspace.tsx tests/test_frontend_conversation_contract.py
git commit -m "fix: recover agent streams and use horizontal brand mark"
```

### Task 6: 全量验证、文档、发布与线上验收

**Files:**
- Modify: `README.md`
- Modify: `docs/PROJECT_HANDOFF.md`
- Modify: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`
- Modify: `docs/RESUME_EVIDENCE_AGENT.md`

**Interfaces:**
- Documents: enterprise audit boundary, context ownership, run recovery and known deployment limits

- [ ] **Step 1: Update project and interview documentation**

Document that business audit excludes ordinary chat, Agent run storage provides idempotency/recovery, SQL audit remains a separate detail layer, and no benchmark claims are added without measured evidence.

- [ ] **Step 2: Run complete verification**

Run: `.venv/Scripts/python.exe -m pytest`  
Run: `.venv/Scripts/python.exe -m ruff check src tests`  
Run: `npm run build` in `frontend`  
Run: `npm run smoke:storage` in `frontend`  
Run: `docker compose -f compose.vps.yaml config`  
Expected: all commands exit 0.

- [ ] **Step 3: Build the production container**

Run: `docker build -t zhishu-nexus:ci .`  
Expected: image build exits 0 and includes migration 010 plus the current static bundle.

- [ ] **Step 4: Commit documentation and push**

```bash
git add README.md docs/PROJECT_HANDOFF.md docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md docs/RESUME_EVIDENCE_AGENT.md docs/superpowers/plans/2026-08-15-agent-audit-context-hardening-plan.md
git commit -m "docs: explain agent audit and recovery boundaries"
git push origin main
```

- [ ] **Step 5: Wait for CI and VPS deployment**

Confirm the CI and deployment workflows for the pushed commit both conclude `success`.

- [ ] **Step 6: Run online acceptance**

Verify `/health`, `/ready`, OpenAPI title, login, Agent identity, one non-audited general request, one audited knowledge/data request, admin audit visibility, duplicate request replay, and desktop/mobile horizontal mark rendering. Do not report completion until these checks pass.
