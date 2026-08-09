# Interview Readiness Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the scripted demo rail, retain the real analysis experience,
and leave the public demo with verified data readiness and a concise interview
walkthrough.

**Architecture:** The React workspace remains the single interaction surface.
Only presentation-layer rail code, its generated-asset assertions, and its
documentation change; backend APIs, access control, and seeds remain intact.
The interview script documents existing public and protected flows without
changing runtime authority.

**Tech Stack:** React 18, TypeScript, Vite, FastAPI, pytest, Node.js smoke
check, GitHub Actions VPS deployment.

## Global Constraints

- Do not expose public administrator approval, raw traces, sensitive refund
  reasons, or server credentials.
- Do not modify the 130-order public dataset.
- Do not alter `docs/PROJECT_HANDOFF.md`.
- Publish only after local checks and the public smoke check pass.

---

### Task 1: Remove Scripted Demo Presentation

**Files:**
- Modify: `frontend/src/Workspace.tsx:12-250`
- Modify: `frontend/src/components.tsx:131-168`
- Modify: `frontend/src/styles.css:97-116`
- Modify: `frontend/smoke/console-smoke.mjs:14-20`
- Modify: `frontend/smoke/README.md:1-13`
- Modify: `tests/test_app.py:59-77`

**Interfaces:**
- Consumes: the existing `runQuestion(question)` workflow and the existing
  result/evidence cards.
- Produces: a workspace whose query panel starts with the real input form;
  neither source nor packaged bundle contains `DemoPathRail` or
  `demo-path-rail`.

- [ ] **Step 1: Change the smoke contract before implementation**

Replace the positive bundle assertion with an absence assertion:

```js
if (script.body.includes("demo-path-rail")) {
  throw new Error("bundle still contains the removed guided demo rail");
}
```

Run:

```powershell
$env:VITE_BASE_URL = "http://106.52.176.63/"
npm run smoke
```

Expected: fail against the currently published rail, proving the check detects
the obsolete presentation layer.

- [ ] **Step 2: Remove the component and its call site**

Delete `DemoPathRail` and its icon-only imports from `components.tsx`. Remove
its import and JSX from `Workspace.tsx`, then delete `focusEvidence()` because
it has no remaining consumer. Keep the form, scenario buttons, `runQuestion`,
workflow, result cards, and evidence card unchanged.

- [ ] **Step 3: Remove rail-only CSS and update static-asset tests**

Delete only the `.demo-path-*` selector block and the rail-specific
reduced-motion rules. In `test_demo_homepage_and_static_assets_are_available`,
retain the current `--teal` stylesheet assertion and replace the rail presence
assertion with:

```python
assert ".demo-path-rail" not in stylesheet.text
```

This checks the packaged CSS matches the streamlined UI.

- [ ] **Step 4: Update the smoke documentation**

Describe the smoke check as validating the packaged workspace, public-session
boundary, data-size guardrails, and absence of the removed scripted rail.

- [ ] **Step 5: Verify the frontend contract**

Run:

```powershell
npx tsc --noEmit --incremental false
npx vite build --configLoader runner --outDir C:\Users\21078\Documents\Codex\2026-08-10\new-chat\work\frontend-build-streamlined
$py = "E:\qiuzhaoxiangmu\retail-analytics-agent\.venv-codex\Scripts\python.exe"
& $py -m pytest tests/test_app.py::test_demo_homepage_and_static_assets_are_available -p no:cacheprovider --basetemp C:\Users\21078\Documents\Codex\2026-08-10\new-chat\work\pytest-temp-streamlined
```

Expected: all commands exit `0`.

### Task 2: Record Data Readiness And Interview Script

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-remove-guided-demo-rail-design.md`
- Create: `docs/INTERVIEW_DEMO_SCRIPT.md`

**Interfaces:**
- Consumes: the public demo data boundary, existing public analyst experience,
  and protected administrator approval flow.
- Produces: a three-minute, fact-based walkthrough with exact questions and
  observables.

- [ ] **Step 1: Preserve the data decision in the design record**

State the deterministic coverage already available: 130 orders, 30 refunds,
four channels, 16 products, 73 public coverage days, varied order/refund
states. State explicitly that no dataset expansion is required.

- [ ] **Step 2: Write the three-minute interview walkthrough**

Create a Chinese document with timed sections:

```text
0:00-0:25  Name the problem and point out the public analyst boundary.
0:25-1:10  Ask for recent-30-day channel sales; point out workflow, result,
            chart, table, plan, evidence, and business constraints.
1:10-1:40  Ask for refund reasons as the public analyst; point out the
            pre-execution rejection and the absence of returned sensitive data.
1:40-2:20  In a protected administrator environment, explain the existing SQL
            preview, approval decision, result, and audit linkage. Do not
            claim this is available on the public URL.
2:20-3:00  Explain error/degraded-result behaviour and give the project scope
            boundary: demo-grade public access, not multi-tenant production.
```

Include the actual public URL, exact question text, the expected visible
result, and a short list of claims not to make.

- [ ] **Step 3: Review copy against the implementation**

Verify every script claim against source, tests, or the live public page. Keep
approval wording scoped to a protected administrator environment.

### Task 3: Release And Verify The Public Experience

**Files:**
- Modify: `src/retail_analytics_agent/static/` generated by the frontend build

**Interfaces:**
- Consumes: the rebuilt Vite assets and existing VPS release workflow.
- Produces: a live public workspace without scripted buttons, retaining the
  public analyst boundary and useful demo dataset.

- [ ] **Step 1: Rebuild and synchronize packaged assets**

Build the frontend using the repository's existing production process, then
ensure the generated assets copied into `src/retail_analytics_agent/static/`
are the exact current Vite output. Remove only superseded hashed assets.

- [ ] **Step 2: Run complete verification**

Run:

```powershell
$py = "E:\qiuzhaoxiangmu\retail-analytics-agent\.venv-codex\Scripts\python.exe"
& $py -m pytest -p no:cacheprovider --basetemp C:\Users\21078\Documents\Codex\2026-08-10\new-chat\work\pytest-temp-release
& "E:\qiuzhaoxiangmu\retail-analytics-agent\.venv-codex\Scripts\ruff.exe" check --no-cache tests/test_app.py
git diff --check
```

Expected: full pytest has zero failures, changed test file is Ruff-clean, and
the diff check is clean. Report unrelated repository-wide Ruff failures
without mass-formatting scripts.

- [ ] **Step 3: Commit and publish only scoped files**

Commit the component, workspace, styles, smoke files, packaged assets, static
test, design record, and interview script. Exclude the untracked handoff.
Push `main` to trigger the existing VPS workflow only after the checks pass.

- [ ] **Step 4: Verify the deployed public experience**

Wait for the successful `Deploy VPS release` workflow, then run:

```powershell
$env:VITE_BASE_URL = "http://106.52.176.63/"
npm run smoke
```

Inspect the public page at desktop and `390px` width. Confirm the rail is
absent, the public analyst trust message is visible, a channel-sales request
returns a chart/table/evidence, and a refund-reason request is rejected before
data execution.
