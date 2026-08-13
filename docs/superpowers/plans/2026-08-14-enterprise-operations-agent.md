# 企业经营分析 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the auditable retail Text-to-SQL workflow into a measurable enterprise operations Agent with Skills, server-side context, governed tools, internal SQL/RAG joint analysis, one MCP export tool, and a deployable report workflow.

**Architecture:** Keep `retail-analytics-agent` as the main runtime. Add bounded Python modules for conversation context, Skills, tool registration, task planning, report composition, and Agent evaluation. Integrate the enterprise RAG repository through a stable adapter/HTTP contract; do not duplicate its database or consume its frozen holdout. Keep existing LangGraph safety, approval, checkpoint, idempotency, SSE, and trace boundaries.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Pydantic, PostgreSQL, SQLGlot, existing React/TypeScript frontend, Docker Compose, pytest, GitHub Actions, Qwen OpenAI-compatible API, one Python MCP SDK integration.

## Global Constraints

- Never commit or print API keys; `.env` remains untracked.
- Preserve existing user/Claude changes in both repositories.
- Add or update tests with every behavior change.
- Do not modify or reread the consumed `enterprise-knowledge-rag/evaluation/frozen_holdout.json` for tuning.
- Do not claim benchmark improvements until sample-level reports exist.
- Keep the main project focused on auditable enterprise operations analysis; no multi-agent team or plugin marketplace.

### Task 1: Add versioned Agent domain contracts

**Files:**
- Create: `src/retail_analytics_agent/agent_models.py`
- Create: `tests/test_agent_models.py`
- Modify: `src/retail_analytics_agent/models.py` only when a shared type is required

**Interfaces:**
- `SkillId`, `ToolRisk`, `TaskStatus` enums.
- `TaskPlan(goal, skill_id, subtasks, completion_criteria, max_steps)`.
- `ContextSnapshot(conversation_id, summary, confirmed_constraints, evidence_ids, token_budget, token_estimate)`.
- `ToolCallRecord(tool_name, input_hash, status, duration_ms, error_type)`.
- `OperationsReport(title, executive_summary, findings, charts, data_evidence, document_evidence, limitations)`.

- [ ] Write validation tests for strict fields, bounded lists, empty evidence, invalid step budgets, and JSON round trips.
- [ ] Run `pytest tests/test_agent_models.py -q` and confirm the new tests fail before implementation.
- [ ] Implement frozen/strict Pydantic contracts with stable enum values and no `Any` for public report fields.
- [ ] Run the focused tests and the existing model tests.
- [ ] Commit `feat: add enterprise agent domain contracts`.

### Task 2: Implement server-side conversation and context layers

**Files:**
- Create: `src/retail_analytics_agent/context_store.py`
- Create: `src/retail_analytics_agent/context_builder.py`
- Create: `tests/test_context_builder.py`
- Modify: `src/retail_analytics_agent/db/migrations/` with the next numbered migration and wire it through existing migration loading

**Interfaces:**
- `ConversationStore.create_or_get(conversation_id, user_id)`.
- `ConversationStore.append_turn(...)`.
- `ConversationStore.save_summary(...)`.
- `ContextBuilder.build(conversation_id, question, task_plan, access_context, evidence, tool_calls, token_budget)`.

- [ ] Write tests for user isolation, confirmed constraint inheritance, conflict detection, oldest-turn summarization, evidence priority, and token-budget truncation.
- [ ] Run the focused tests and confirm the failure is due to missing store/builder behavior.
- [ ] Add a PostgreSQL-backed store with an in-memory test implementation; persist only structured fields and evidence IDs, not arbitrary model hidden reasoning.
- [ ] Implement deterministic token estimation and a context packing order: goal/constraints, current plan, evidence, recent tool outputs, summary, oldest raw turns.
- [ ] Run focused tests plus request/auth tests.
- [ ] Commit `feat: add server-side agent context`.

### Task 3: Add Skill Registry and task router

**Files:**
- Create: `src/retail_analytics_agent/skills.py`
- Create: `src/retail_analytics_agent/task_planner.py`
- Create: `tests/test_skills_and_planner.py`

**Interfaces:**
- `SkillDefinition(id, description, required_tools, completion_criteria, output_schema)`.
- `SkillRegistry.register(definition)` and `.route(question, context)`.
- `TaskPlanner.plan(question, context, available_skills) -> TaskPlan`.

- [ ] Add tests for refund, channel, product, weekly-report routing, out-of-scope refusal, and planner step limits.
- [ ] Run the focused tests and verify no route/plan implementation exists.
- [ ] Register four skills with explicit tool allowlists and refusal conditions.
- [ ] Implement structured planner adapter using the existing model client/retry boundary; provide deterministic fallback for known demo questions.
- [ ] Run tests with fake model responses and no network dependency.
- [ ] Commit `feat: add skill routing and task planning`.

### Task 4: Unify internal Tool Registry

**Files:**
- Create: `src/retail_analytics_agent/tool_registry.py`
- Create: `tests/test_tool_registry.py`
- Modify: `src/retail_analytics_agent/workflow_tools.py`
- Modify: `src/retail_analytics_agent/workflow.py`

**Interfaces:**
- `ToolSpec(name, description, input_model, output_model, required_roles, risk, timeout_seconds, idempotent)`.
- `ToolRegistry.register(spec, handler)`.
- `ToolRegistry.call(name, payload, access_context, request_id) -> ToolCallResult`.

- [ ] Test schema rejection, unknown tools, role denial, timeout classification, retryable errors, idempotency keys, and trace records.
- [ ] Run focused tests and confirm the new registry rejects calls until handlers are connected.
- [ ] Adapt existing catalog retrieval, SQL validation/execution, chart construction, and trace/status tools to the registry without changing their safety rules.
- [ ] Enforce Skill tool allowlists before execution and attach conversation/task IDs to every call.
- [ ] Run all workflow, approval, request registry, and trace tests.
- [ ] Commit `feat: govern agent tool calls with registry`.

### Task 5: Integrate project-two RAG through a knowledge adapter

**Files:**
- Create: `src/retail_analytics_agent/knowledge_adapter.py`
- Create: `tests/test_knowledge_adapter.py`
- Modify: `.env.example`, `settings.py`, and dependency/config docs

**Interfaces:**
- `KnowledgeQuery(query, user_id, role, departments, as_of, top_k)`.
- `KnowledgeEvidence(source_id, title, version, effective_from, quote, score, permissions)`.
- `KnowledgeAdapter.retrieve(query) -> KnowledgeEvidence[]`.

- [ ] Test response validation, permission propagation, unavailable-service degradation, timeout, and evidence ID preservation with fake HTTP responses.
- [ ] Run focused tests and confirm the adapter fails closed without a configured endpoint.
- [ ] Implement an internal HTTP adapter compatible with project-two `/chat` or a small dedicated evidence endpoint; do not copy project-two internals or expose raw restricted content.
- [ ] Add an optional local fixture adapter for deterministic unit/evaluation runs and a configuration flag for live Qwen/RAG.
- [ ] Run adapter, auth, and citation boundary tests.
- [ ] Commit `feat: connect governed enterprise knowledge evidence`.

### Task 6: Implement multi-step operations workflow and report composer

**Files:**
- Create: `src/retail_analytics_agent/operations_workflow.py`
- Create: `src/retail_analytics_agent/reporting.py`
- Create: `tests/test_operations_workflow.py`
- Modify: `analysis_service.py`, `workflow.py`, `models.py`, and `app.py`

**Interfaces:**
- `OperationsState` with task plan, context snapshot, subtask results, tool calls, evidence ledger, report, and budget fields.
- `build_operations_graph(...)` using existing checkpoint and interrupt boundaries.
- `ReportComposer.compose(state) -> OperationsReport`.

- [ ] Write tests for a refund diagnosis that calls database then knowledge tools, continues after incomplete evidence, refuses on missing evidence, and pauses for high-risk SQL.
- [ ] Run focused tests and verify the new graph fails before implementation.
- [ ] Add bounded loop routing: execute next subtask, inspect evidence coverage, choose supplemental SQL/RAG, finalize, refuse, or request approval; enforce max steps and workflow deadline.
- [ ] Reuse existing SQL safety, business consistency, approval, checkpoint, idempotency, and SSE code rather than bypassing it.
- [ ] Compose reports with findings tied to data query IDs and document source IDs; include limitations and degraded states.
- [ ] Run all existing tests plus the focused operations suite.
- [ ] Commit `feat: add multi-step enterprise operations workflow`.

### Task 7: Add one real MCP export/template tool

**Files:**
- Create: `mcp_server/operations_export_server.py`
- Create: `src/retail_analytics_agent/mcp_client.py`
- Create: `tests/test_mcp_export.py`
- Modify: `pyproject.toml`, `.env.example`, `tool_registry.py`, and deployment docs

**Interfaces:**
- MCP server tool `read_report_template(template_name)`.
- MCP server tool `export_operations_report(report, format)`.
- `McpToolClient.discover()` and `.call(tool_name, payload, access_context)`.

- [ ] Test allowlisted template names, format validation, no path traversal, timeout, server-unavailable degradation, and Trace metadata.
- [ ] Run focused tests and verify the MCP client refuses unconfigured servers.
- [ ] Implement one stdio or Streamable HTTP MCP server with an allowlisted template directory and Markdown export first; PDF can be a later adapter only if the runtime is stable.
- [ ] Discover the tools at startup, mirror them into Tool Registry with explicit risk and permission metadata, and keep exports separate from core RAG/SQL execution.
- [ ] Run MCP tests without requiring a live external server, then one local integration smoke.
- [ ] Commit `feat: add governed operations export MCP tool`.

### Task 8: Build Agent development evaluation and baselines

**Files:**
- Create: `evaluation/agent_development.jsonl`
- Create: `src/retail_analytics_agent/agent_evaluation.py`
- Create: `scripts/run_agent_development.py`
- Create: `tests/test_agent_evaluation.py`
- Create: `evaluation/reports/agent-development-*.json`
- Modify: `README.md`, `docs/EVALUATION_PROTOCOL.md`, and evaluation docs

**Interfaces:**
- `AgentEvaluationCase` with expected skill, subtasks, tools, evidence needs, refusal and key claims.
- `AgentEvaluationRunner.run(cases, runtime, label) -> AgentEvaluationReport`.

- [ ] Add a deterministic starter set covering the four skills, multi-turn inheritance, permissions, tool failures, and full reports; keep synthetic data labels explicit.
- [ ] Test metric aggregation and sample-level failure records using fake runtime outputs.
- [ ] Implement baseline labels: `fixed_workflow`, `skill_planner`, `context_multisource`.
- [ ] Run a smoke evaluation and inspect raw samples before any full run.
- [ ] Run the full development set with fixed model/configuration; save counts, means, ranges, p50/p95, token usage, and config hashes.
- [ ] Only write resume metrics that are present in the saved reports and record the exact dataset/model/config in interview docs.
- [ ] Commit `feat: add agent development evaluation baselines`.

### Task 9: Update frontend, deployment, and documentation

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/Workspace.tsx`, and relevant components/styles
- Modify: `Dockerfile`, `compose.vps.yaml`, `.env.vps.example`, and `Caddyfile` only as needed
- Modify: `README.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT_*.md`
- Create: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`

**Interfaces:**
- Stream events expose Skill, subtask, tool, context budget, evidence, report, and trace states without exposing restricted raw evidence.
- Deployment supports remote Qwen and a configured project-two knowledge endpoint; local deterministic mode remains available for CI.

- [ ] Add frontend tests/smoke assertions for Skill, subtask, evidence, report and degraded states.
- [ ] Implement compact workspace sections for task plan, tool timeline, evidence ledger, report and trace; keep existing login and public-demo boundaries.
- [ ] Update Compose/env docs with endpoint, API key names, MCP configuration and health checks; never include secret values.
- [ ] Write interview guide with exact architecture, failure modes, measured metrics, known limitations and “implemented vs future” boundaries.
- [ ] Run frontend build, smoke tests, backend tests, and local Docker readiness.
- [ ] Commit `docs: document enterprise operations agent and deployment`.

### Task 10: Verify, deploy, and produce resume-ready evidence

**Files:**
- Modify: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`, `README.md`, and final evaluation reports only after fresh evidence
- Deployment target: existing Tencent Cloud VPS, with user-managed secret values

- [ ] Run the full backend test suite and frontend build from clean working trees; record exact pass counts and known unrelated failures.
- [ ] Run live API smoke for database analysis, internal knowledge retrieval, MCP export, SSE reconnect/status, and permission refusal.
- [ ] Run the development evaluation with remote API configuration and archive raw report/config fingerprint.
- [ ] Deploy the versioned image/compose configuration to the existing VPS without exposing keys; verify public demo and health endpoints.
- [ ] Re-render/read the project README and interview guide, then write final resume bullets only from measured reports.
- [ ] Commit `chore: verify and package resume evidence`.
