# Expanded Agent Evaluation Implementation Plan

> **For agentic workers:** This plan is executed inline in the current task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the live Agent evaluation from 12 cases to a reproducible 60-case development suite and report category-level reliability metrics without presenting development results as general accuracy.

**Architecture:** Keep the existing authenticated VPS runner and per-case gates. Add 48 labelled cases to a separate live-development JSONL, add category aggregation to the runner, and write a protocol document that defines denominators, failure categories, and the distinction between development and frozen acceptance. No runtime behavior changes are needed.

**Tech Stack:** Python 3.11+, standard-library JSON/HTTP client, pytest, JSONL evaluation datasets, existing FastAPI VPS deployment.

## Global Constraints

- Do not inspect or tune against the existing consumed frozen holdout and do not relabel development output as general accuracy.
- Do not invent benchmark results; every resume number must come from a saved report.
- Preserve existing live 12-case report and dataset; the expanded suite is additive.
- Do not commit passwords, model keys, cookies or deployment tokens.

---

### Task 1: Expand labelled live development cases

**Files:**
- Create: `evaluation/agent_live_development_extended.jsonl`
- Test: `tests/test_agent_live_development_dataset.py`

- [x] Add 60 cases across general, knowledge, data, collaboration and safety behavior.
- [x] Require mode, Skill, tool set, evidence requirements, export requirements, and accepted degraded status where the runtime intentionally supports fallback.
- [x] Validate unique IDs, required fields, category distribution, and a total of 60 cases.

### Task 2: Add category-level metrics

**Files:**
- Modify: `scripts/run_agent_live_development.py`
- Modify: `tests/test_agent_live_development.py`

- [x] Read an optional `category` field and default older cases to `uncategorized`.
- [x] Aggregate case count, mode/Skill route accuracy, tool accuracy, evidence accuracy, refusal accuracy, business non-failure rate, and latency P50/P95 per category.
- [x] Keep refusal cases out of business execution denominators while retaining them in safety metrics.

### Task 3: Document and execute the expanded run

**Files:**
- Modify: `docs/EVALUATION_PROTOCOL.md`
- Create: `evaluation/reports/agent-live-development-extended-<UTC timestamp>.json`

- [x] Document the 60-case split and the metric denominators.
- [x] Run focused tests and the complete local test suite before the network run.
- [x] Run the expanded suite against the public VPS with the existing demo account and save the sample-level report.
- [x] Inspect failed cases and record limitations; retain external-tool and evidence-coverage failures in the denominator.
