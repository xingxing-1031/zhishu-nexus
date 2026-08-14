# Qixi Enterprise Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `retail-analytics-agent` the complete Qixi enterprise agent system and restore `enterprise-knowledge-rag` to an independent, one-way RAG evidence service.

**Architecture:** Project one owns Supervisor routing, bounded planning, general MCP tools, context, data analysis, collaboration, review, SSE, and the unified UI. It calls project two only through the authenticated `/internal/evidence` API. Project two runs governed RAG directly and has no runtime dependency on project one.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, LangGraph, MCP Python SDK/FastMCP, httpx, PostgreSQL, React, TypeScript, Vitest, Playwright, Docker Compose.

## Global Constraints

- Keep the project-one Text-to-SQL, SQLGlot, approval, report export, and audit paths backward compatible.
- Keep the project-two RAG ingestion, retrieval, permission, version, citation, refusal, and evaluation paths backward compatible.
- Project dependency direction is only `retail-analytics-agent -> enterprise-knowledge-rag`.
- External MCP tools are read-only, allowlisted, bounded by timeout and response size, and never receive database credentials.
- Do not add multi-tenancy, arbitrary database adapters, calendar OAuth, model training, or arbitrary remote MCP installation.
- Preserve the user-owned untracked `docs/PROJECT_HANDOFF.md` file.

---

### Task 1: Unified Agent Contract and Supervisor

**Files:**
- Modify: `src/retail_analytics_agent/agent_models.py`
- Create: `src/retail_analytics_agent/supervisor.py`
- Test: `tests/test_qixi_supervisor.py`
- Test: `tests/test_agent_models.py`

**Interfaces:**
- Produces: `AgentMode`, `AgentStep`, `AgentReview`, `KnowledgeEvidenceView`, and backward-compatible additions to `AgentResponse`.
- Produces: `Supervisor.plan(question: str, history: Sequence[dict[str, str]]) -> AgentPlan`.

- [ ] **Step 1: Write failing model and routing tests**

```python
def test_routes_general_knowledge_data_and_collaboration():
    supervisor = Supervisor()
    assert supervisor.plan("现在北京时间几点").mode is AgentMode.GENERAL
    assert supervisor.plan("公司的报销制度是什么").mode is AgentMode.KNOWLEDGE
    assert supervisor.plan("最近30天退款率是多少").mode is AgentMode.DATA
    assert supervisor.plan("结合退款数据和售后制度给出复盘").mode is AgentMode.COLLABORATION
```

- [ ] **Step 2: Run the new tests and confirm they fail because the types and Supervisor do not exist**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_qixi_supervisor.py tests/test_agent_models.py -q`

- [ ] **Step 3: Add bounded routing types and deterministic safety-first routing**

```python
class AgentMode(StrEnum):
    GENERAL = "general"
    KNOWLEDGE = "knowledge"
    DATA = "data"
    COLLABORATION = "collaboration"

class AgentStep(AgentStrictModel):
    agent: str
    task: str
    status: AgentTaskStatus = AgentTaskStatus.PENDING
```

- [ ] **Step 4: Run focused tests and existing model tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_qixi_supervisor.py tests/test_agent_models.py -q`

- [ ] **Step 5: Commit the contract and Supervisor**

```bash
git add src/retail_analytics_agent/agent_models.py src/retail_analytics_agent/supervisor.py tests/test_qixi_supervisor.py tests/test_agent_models.py
git commit -m "feat: add qixi supervisor contract"
```

### Task 2: Common MCP Server and Governed Tool Adapter

**Files:**
- Create: `mcp_server/common_tools_server.py`
- Create: `src/retail_analytics_agent/common_tools.py`
- Modify: `src/retail_analytics_agent/settings.py`
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `Dockerfile`
- Test: `tests/test_common_mcp_tools.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces MCP tools `time_now`, `weather_current`, `web_search`, `web_fetch_summary`, and `exchange_rate`.
- Produces `CommonToolGateway.discover()` and `CommonToolGateway.call(tool_name, arguments)` with normalized failures.

- [ ] **Step 1: Write failing deterministic tests with mocked HTTP transports**

```python
def test_time_now_defaults_to_shanghai():
    result = time_now("Asia/Shanghai")
    assert result["timezone"] == "Asia/Shanghai"
    assert result["source"] == "system_clock"

def test_fetch_rejects_private_network_urls():
    with pytest.raises(MCPToolInputError):
        fetch_public_page("http://127.0.0.1/admin")
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_common_mcp_tools.py tests/test_settings.py -q`

- [ ] **Step 3: Implement schemas, public API clients, SSRF checks, response bounds, and FastMCP registration**

Use `zoneinfo.ZoneInfo`, Open-Meteo geocoding/weather, Frankfurter exchange rates, a configured search endpoint, and an HTML text extractor based on `html.parser`. Reject non-HTTP schemes, literal private IPs, private DNS resolutions, redirects, and responses above the configured byte limit.

- [ ] **Step 4: Wire the bundled MCP process through existing `McpToolClient` and settings**

Add `MCP_COMMON_ENABLED`, `MCP_COMMON_TIMEOUT_SECONDS`, `MCP_HTTP_TIMEOUT_SECONDS`, `MCP_MAX_RESPONSE_BYTES`, and optional search configuration without exposing secrets in tool output.

- [ ] **Step 5: Run focused MCP and settings tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_common_mcp_tools.py tests/test_mcp_export.py tests/test_settings.py -q`

- [ ] **Step 6: Commit the MCP tool layer**

```bash
git add mcp_server/common_tools_server.py src/retail_analytics_agent/common_tools.py src/retail_analytics_agent/settings.py src/retail_analytics_agent/app.py Dockerfile tests/test_common_mcp_tools.py tests/test_settings.py
git commit -m "feat: add governed common MCP tools"
```

### Task 3: General Tool Loop, Knowledge Agent, and Collaboration Runtime

**Files:**
- Create: `src/retail_analytics_agent/general_agent.py`
- Create: `src/retail_analytics_agent/qixi_service.py`
- Modify: `src/retail_analytics_agent/knowledge_adapter.py`
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `src/retail_analytics_agent/agent_models.py`
- Test: `tests/test_general_agent.py`
- Test: `tests/test_qixi_service.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces `GeneralAgent.answer(question, history, request_id, conversation_id, access_context) -> GeneralAgentResult`.
- Produces `QixiAgentService.run(request, access_context) -> AgentResponse` and `stream(...) -> Iterator[AgentStreamEvent]`.
- Consumes: existing `EnterpriseAgentService` for data mode and `KnowledgeRetriever` for RAG evidence.

- [ ] **Step 1: Write failing tests for tool selection, knowledge-only, data-only, collaboration, review, and degradation**

```python
def test_weather_question_calls_weather_tool():
    result = make_general_agent(decision="weather_current").answer(
        "重庆今天天气怎么样", [], "r1", "c1", analyst()
    )
    assert result.tool_calls[0].tool_name == "weather.current"
    assert "重庆" in result.answer

def test_knowledge_mode_never_runs_sql():
    response = make_qixi_service().run(request("公司的报销制度是什么"), analyst())
    assert response.agent_mode is AgentMode.KNOWLEDGE
    assert response.analysis is None
    assert response.knowledge_evidence
```

- [ ] **Step 2: Run focused tests and confirm missing runtime failures**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_general_agent.py tests/test_qixi_service.py tests/test_app.py -q`

- [ ] **Step 3: Implement a maximum-three-step structured tool loop**

The model decision schema has `action`, `tool_name`, `arguments`, and `answer`. Validate tool names against discovery, validate arguments through MCP Schema, append only bounded tool summaries to context, and stop after three calls.

- [ ] **Step 4: Implement one-way knowledge execution and evidence-grounded synthesis**

Knowledge mode calls only `HttpKnowledgeAdapter`; collaboration runs knowledge and existing data analysis concurrently, synthesizes only verified evidence, and adds a review failure when either evidence class is missing.

- [ ] **Step 5: Make `/agent/run` and `/agent/stream` use `QixiAgentService`; keep `/internal/agent` data-only**

The internal endpoint remains a compatibility adapter for old callers and must continue forcing `include_knowledge=False`.

- [ ] **Step 6: Run focused runtime and API tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_general_agent.py tests/test_qixi_service.py tests/test_agent_service.py tests/test_app.py -q`

- [ ] **Step 7: Commit unified Agent runtime**

```bash
git add src/retail_analytics_agent/general_agent.py src/retail_analytics_agent/qixi_service.py src/retail_analytics_agent/knowledge_adapter.py src/retail_analytics_agent/app.py src/retail_analytics_agent/agent_models.py tests/test_general_agent.py tests/test_qixi_service.py tests/test_app.py
git commit -m "feat: make qixi the unified enterprise agent"
```

### Task 4: Project Two Pure RAG Runtime Boundary

**Files:**
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/src/enterprise_knowledge_rag/bootstrap.py`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/src/enterprise_knowledge_rag/runtime.py`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/src/enterprise_knowledge_rag/config.py`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/compose.vps.yaml`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/.env.example`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/.env.vps.example`
- Test: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/tests/test_bootstrap.py`
- Test: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/tests/test_runtime_service.py`
- Test: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/tests/test_app.py`

**Interfaces:**
- `RuntimeChatService.run()` always executes governed RAG.
- `/internal/evidence` remains authenticated and returns the same schema.
- Project two no longer reads `RETAIL_AGENT_URL` or `RETAIL_AGENT_TOKEN`.

- [ ] **Step 1: Add failing tests proving general and data-looking questions stay inside RAG boundaries**

```python
def test_runtime_has_no_agent_or_retail_dependency(tmp_path):
    service = make_service(tmp_path)
    assert not hasattr(service, "_retail_agent")
    service.run(ChatRequest(question="最近30天退款率"), employee())
    assert chat_runner.calls == 1
```

- [ ] **Step 2: Run the focused RAG boundary tests and confirm failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bootstrap.py tests/test_runtime_service.py tests/test_app.py -q`

- [ ] **Step 3: Remove Supervisor/general/retail/synthesis construction from bootstrap and runtime dispatch**

Keep RAG conversation history and document administration unchanged. Remove reverse service configuration from Compose and environment examples.

- [ ] **Step 4: Run the full project-two backend suite and Ruff**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts`

- [ ] **Step 5: Commit the pure RAG boundary in project two**

```bash
git add src/enterprise_knowledge_rag/bootstrap.py src/enterprise_knowledge_rag/runtime.py src/enterprise_knowledge_rag/config.py compose.vps.yaml .env.example .env.vps.example tests/test_bootstrap.py tests/test_runtime_service.py tests/test_app.py
git commit -m "refactor: restore standalone RAG service boundary"
```

### Task 5: Qixi Product UI and Streaming Contract

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components.tsx`
- Modify: `frontend/src/LoginPage.tsx`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/localization.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/**/*.test.tsx`

**Interfaces:**
- Consumes expanded `AgentResponse` fields `agent_mode`, `agents`, `task_steps`, `answer`, `knowledge_evidence`, `review`, and existing data/report fields.
- Shows one stable Qixi workspace without nested cards or a separate marketing landing page.

- [ ] **Step 1: Update component tests for Qixi branding and four execution modes**

Expect “企析”, “你的企业专业智能助理”, General/Knowledge/Data/Collaboration state labels, tool calls, knowledge citations, data evidence, and degradation messages.

- [ ] **Step 2: Run component tests and confirm expected failures**

Run: `npm test -- --run`

- [ ] **Step 3: Update types, streaming event handling, branding, prompt examples, and result panels**

Keep existing approval, trace, chart, and report drawers. Replace the “Agent复盘/提问分析” split with a single Qixi conversation input; Supervisor chooses the path.

- [ ] **Step 4: Run unit tests and production build**

Run: `npm test -- --run`

Run: `npm run build`

- [ ] **Step 5: Commit the Qixi UI**

```bash
git add frontend/src
git commit -m "feat: present qixi unified agent workspace"
```

### Task 6: Evaluation, Deployment, and Recruiting Evidence

**Files:**
- Create: `evaluation/qixi_development.jsonl`
- Create: `src/retail_analytics_agent/qixi_evaluation.py`
- Create: `scripts/run_qixi_evaluation.py`
- Modify: `compose.vps.yaml`
- Modify: `.env.example`
- Modify: `.env.vps.example`
- Modify: `README.md`
- Modify: `docs/RESUME_EVIDENCE_AGENT.md`
- Modify: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/README.md`
- Modify: `E:/qiuzhaoxiangmu/enterprise-knowledge-rag/docs/RESUME_EVIDENCE_MULTI_AGENT.md`
- Test: `tests/test_qixi_evaluation.py`
- Test: `tests/test_deployment_assets.py`

**Interfaces:**
- Evaluation records per-case expected mode, expected tools, actual mode, actual tools, evidence presence, review result, latency, and degradation.

- [ ] **Step 1: Add deterministic evaluation cases covering all four modes and every common tool**

Include direct, ambiguous, follow-up, missing-tool, timeout, insufficient-RAG-evidence, missing-data-evidence, and collaboration cases.

- [ ] **Step 2: Implement evaluator and run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_qixi_evaluation.py tests/test_deployment_assets.py -q`

- [ ] **Step 3: Update deployment configuration and one-way service tokens**

Project one receives `KNOWLEDGE_SERVICE_URL` and `KNOWLEDGE_SERVICE_TOKEN`. Project two receives only `INTERNAL_SERVICE_TOKEN`; remove all project-two reverse Agent variables.

- [ ] **Step 4: Update README and recruiting evidence without claiming unmeasured performance**

Project one documents Agent architecture, tool loop, context, MCP, data analysis, collaboration, and evaluation. Project two documents only RAG ingestion, retrieval, governance, evidence API, and RAG evaluation.

- [ ] **Step 5: Commit evaluation and documentation in each repository**

```bash
git add evaluation src/retail_analytics_agent/qixi_evaluation.py scripts/run_qixi_evaluation.py compose.vps.yaml .env.example .env.vps.example README.md docs tests/test_qixi_evaluation.py tests/test_deployment_assets.py
git commit -m "docs: validate qixi agent system"
```

### Task 7: Full Verification and Public Deployment

**Files:**
- Verify all changed files in both repositories.

- [ ] **Step 1: Run project-one backend tests and Ruff**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts mcp_server`

- [ ] **Step 2: Run project-one frontend tests, build, and responsive Playwright suite**

Run: `npm test -- --run`

Run: `npm run build`

Run: `npm run test:e2e`

- [ ] **Step 3: Run project-two backend, frontend, RAG evaluation contract, and Ruff**

Run the repository-defined backend, frontend, Playwright, and development evaluation commands from its README/package scripts.

- [ ] **Step 4: Build both VPS Compose configurations locally**

Run: `docker compose -f compose.vps.yaml config`

Run: `docker compose -f compose.vps.yaml build`

- [ ] **Step 5: Push both repositories and verify GitHub Actions/deployment**

Confirm project one is the Qixi public entry, project two remains the RAG demo and Evidence API, `/health` and `/ready` return 200, and representative General/Knowledge/Data/Collaboration requests pass.

- [ ] **Step 6: Record only measured evaluation and deployment evidence in the final handoff**

