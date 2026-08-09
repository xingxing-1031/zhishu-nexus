# Retail Demo Experience Implementation Plan

> **For agentic workers:** Implement task-by-task with a fresh verification gate after each task.

**Goal:** Improve the public retail analytics demo so an interviewer can understand real analysis, security boundaries, and auditability quickly while preserving the existing backend contracts.

**Architecture:** Keep the current React workspace and SSE API. Add a small presentation layer inside `Workspace` for guided demo paths, preserve server-controlled roles and outcomes, and strengthen the evidence hierarchy without adding a new backend workflow. Rebuild the packaged static bundle from `frontend/` so local and deployed assets match source.

**Tech Stack:** React 18, TypeScript, Vite, ECharts, Lucide, existing FastAPI SSE API, npm build.

## Global Constraints

- Public demo remains analyst-only, no-login, max 20 rows, and rate-limited.
- Do not expose administrator approval, sensitive refund reasons, raw Trace, credentials, or model internals in public mode.
- Demo actions must call the existing API and render its actual response.
- Keep the current API request/response shapes and backend authority boundaries.
- Respect responsive layout, keyboard focus, and `prefers-reduced-motion`.

### Task 1: Establish A Fresh Frontend Baseline

**Files:**
- Modify: `frontend/package.json` (add explicit typecheck/test entry points only if needed)
- Modify: `src/retail_analytics_agent/static/` (generated build output)
- Test: `frontend` build output and served static index

- [ ] Run `npm run build` from `frontend` and record the current result.
- [ ] Compare the generated asset names with `src/retail_analytics_agent/static/index.html`.
- [ ] Replace packaged static output using the clean build output, keeping only generated files.
- [ ] Verify the package static index points to files that exist and the source bundle contains the current sidebar markup.

### Task 2: Add Guided Demo Paths

**Files:**
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/components.tsx`
- Modify: `frontend/src/styles.css`
- Test: browser smoke checks for the public workspace

- [ ] Add a compact `DemoPathRail` component with three actions: real sales result, deterministic safety rejection, and evidence focus.
- [ ] Make the first two actions set the existing question and submit through the existing `run` handler; do not add direct SQL or mocked rows.
- [ ] Make the evidence action focus or scroll to the existing evidence section after a result exists, and explain when a result is needed.
- [ ] Add a public-mode note that administrator approval is intentionally protected and available only in the controlled environment.
- [ ] Add accessible labels, focus-visible styles, disabled states while running, and reduced-motion-safe transitions.
- [ ] Keep the query form as the primary interaction and keep the initial real-result path selected.

### Task 3: Strengthen Result Storytelling

**Files:**
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/components.tsx`
- Modify: `frontend/src/styles.css`
- Test: browser smoke checks for success, rejection, empty result, and degraded result states

- [ ] Give the current workflow rail a short explanatory caption that maps each stage to the visible evidence.
- [ ] Make the conclusion header expose the query status and the evidence action without competing with the result.
- [ ] Add stable anchors and headings for chart, table, evidence, and protected-capability note.
- [ ] Preserve the existing Chinese localization and avoid exposing backend English errors to ordinary users.
- [ ] Verify the layout at desktop, 920px, and 390px widths with no horizontal overflow.

### Task 4: Add High-Value Frontend Verification

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/smoke/console-smoke.mjs`
- Create: `frontend/smoke/README.md`
- Test: the smoke command against a local or staging server

- [ ] Add a deterministic smoke runner that checks the public page bootstrap, required headings, four KPI values, and the guided demo controls.
- [ ] Add a documented command for running the smoke check against `VITE_BASE_URL` without production credentials.
- [ ] Keep live-model calls out of the automated smoke test; use mocked API fixtures or a local demo server boundary.
- [ ] Add checks for responsive document width and protected controls remaining absent in public mode.

### Task 5: Verify Data Scenarios And Delivery

**Files:**
- Inspect and, only if a coverage gap is demonstrated, modify: `db/seeds/002_richer_demo_dataset.sql`
- Modify: `README.md` only after fresh verification evidence exists

- [ ] Query the current demo database for counts, channel distribution, time coverage, refund status distribution, and empty-result candidates.
- [ ] Keep 130 orders unless a real scenario lacks contrast; change fixtures only to improve demonstrated business meaning.
- [ ] Run backend tests relevant to workflow, approval, app routes, and final acceptance.
- [ ] Run frontend build and smoke verification.
- [ ] Check `git diff`, generated asset references, and public/protected boundary before any commit.
