# Live Agent Evaluation and Resume Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible live development evaluation for the deployed operations Agent and derive defensible resume and interview evidence from its saved sample-level report.

**Architecture:** Run a small, explicitly non-holdout JSONL suite against the public VPS through the same authenticated API used by the UI. Evaluate routing, exact tool selection, evidence coverage, refusal, context budget and latency per case, then aggregate without mixing expected refusals into business execution rates. Store raw records and deployment conditions next to the code, and only quote metrics present in the final checked-in report.

**Tech Stack:** Python 3.11+, standard-library HTTP client, pytest, Ruff, FastAPI production API, Qwen-compatible remote model, PostgreSQL, enterprise RAG Evidence API, MCP export, GitHub Actions, Tencent Cloud VPS.

## Global Constraints

- Treat all 12 cases as a live development set, not a frozen holdout or general accuracy benchmark.
- Never commit the demo password, model key, internal service token, cookie or SSH key.
- Do not modify project two's frozen holdout or tune against it.
- Preserve the untracked `docs/PROJECT_HANDOFF.md` file.
- Every resume number must link to a saved report and include its sample size and conditions in the interview guide.

---

### Task 1: Correct the live evaluation runner

**Files:**
- Modify: `scripts/run_agent_live_development.py`
- Modify: `tests/test_agent_live_development.py`
- Validate: `evaluation/agent_live_development.jsonl`

**Interfaces:**
- `_evaluate_case(case, response) -> dict[str, Any]` adds `context_budget_pass` to the per-case gate.
- `_aggregate(records) -> dict[str, Any]` excludes any expected refusal from business execution denominators.
- `_git_commit(root) -> str` reads the local release candidate SHA; `--runtime-commit` overrides it when production runs a different SHA.

- [x] Cache the parsed cases before the request loop and validate 12 unique case IDs.
- [x] Add context-budget compliance to the case gate and aggregate report.
- [x] Separate expected refusal cases from executable business cases.
- [x] Replace the stale hard-coded commit with automatic or explicit runtime version capture.
- [x] Run `pytest tests/test_agent_live_development.py -q` and Ruff on the changed files.

### Task 2: Publish and run the production development suite

**Files:**
- Create: `evaluation/reports/agent-live-development-<UTC timestamp>.json`
- Create or update: `evaluation/reports/agent-live-development-latest.json`

**Interfaces:**
- Production input is `POST /agent/run` after `POST /auth/login`.
- Every report records `runtime_commit`, runtime conditions, 12 sample-level records and aggregate metrics.

- [x] Run the full backend suite and `ruff check src tests` before publishing.
- [x] Commit and push the runner, tests, cases and this plan; wait for the VPS deployment to complete.
- [x] Verify the production health endpoint and deployed commit before evaluation.
- [x] Set `AGENT_DEMO_PASSWORD` only in the process environment and run all 12 cases.
- [x] Inspect every failed case instead of relying only on aggregate metrics.

### Task 3: Fix evidence-backed development failures

**Files:**
- Modify only the minimal runtime, prompt, Skill or corpus files implicated by sample-level evidence.
- Update focused regression tests for every behavior change.

**Interfaces:**
- Safety refusal, SQL AST/business validation, RAG permission filtering and MCP idempotency remain hard boundaries.
- No case expectation may be weakened merely to increase a metric.

- [x] Classify each failure as implementation defect, external-service failure, ambiguous case or expected model variance.
- [x] Add a focused test before each justified runtime fix.
- [x] Run focused tests, the full suite and Ruff; publish and verify the new production SHA.
- [x] Rerun the complete 12-case suite once under the same configuration and archive the final raw report.

### Task 4: Package defensible recruiting evidence

**Files:**
- Modify: `docs/EVALUATION_PROTOCOL.md`
- Modify: `docs/INTERVIEW_GUIDE_OPERATIONS_AGENT.md`
- Create: `docs/RESUME_EVIDENCE_AGENT.md`
- Modify: `README.md` only where the live result materially changes project evidence.

**Interfaces:**
- Resume bullets contain project scope, concrete engineering choices and only measured metrics.
- Interview notes explain numerator/denominator, dataset size, environment, limitations and how to reproduce each number.

- [x] Document the distinction between deterministic fixtures, live development and project two's frozen holdout.
- [x] Record the final per-metric values, sample count, production commit and report path.
- [x] Write concise resume bullets and deeper follow-up answers without claiming causality or generalization beyond the suite.
- [x] Verify documentation against the JSON report field by field.
- [ ] Commit and push the evidence package, then perform final health, repository and deployment checks.
