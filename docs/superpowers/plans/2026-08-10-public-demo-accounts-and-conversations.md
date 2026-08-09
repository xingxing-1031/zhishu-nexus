# Public Demo Accounts and Conversations Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with verification after each task.

**Goal:** Turn the public retail analytics demo into a complete two-role, multi-conversation workspace with trustworthy workflow states, low-risk assistant replies, bounded context, and deployable verification.

**Architecture:** Keep the existing FastAPI authentication, LangGraph analysis, SSE stream, and React workspace boundaries. Enable password authentication in public demo mode with two fixed demo identities, while keeping data and server-side audit behavior bounded to the seeded demo database. Store the user-visible conversation cache in browser storage, pass only a validated structured previous-result summary for explicit follow-ups, and leave the storage interface ready for a future server-backed `user_id` implementation.

**Tech Stack:** FastAPI, Pydantic settings, PBKDF2/HMAC cookie sessions, LangGraph, PostgreSQL, React 18, TypeScript, ECharts 6, Vitest-free focused TypeScript/browser tests, pytest.

## Global Constraints

- Public demo remains read-only and capped at 20 returned rows.
- The backend remains authoritative for identity, role, approval, SQL safety, business consistency, and audit records.
- The public UI never exposes model hidden reasoning or raw internal traces.
- Analyst and admin sessions must be isolated; browser deletion cannot delete compliance audit rows.
- Existing `docs/PROJECT_HANDOFF.md` is user-owned and must remain unmodified.

---

### Task 1: Enable Two Fixed Public Demo Accounts

**Files:**
- Modify: `src/retail_analytics_agent/settings.py`
- Modify: `src/retail_analytics_agent/app.py`
- Modify: `src/retail_analytics_agent/access_control.py`
- Modify: `compose.yml` and deployment environment documentation where auth defaults are defined
- Modify: `frontend/src/LoginPage.tsx`, `frontend/src/components.tsx`, `frontend/src/App.tsx`
- Test: `tests/test_settings.py`, `tests/test_auth.py`, `tests/test_app.py`

**Interfaces:**
- `Settings` exposes fixed demo credentials as hashed values/configuration for analyst and admin identities.
- `/auth/login` accepts either demo username and returns the corresponding `SessionInfo`.
- `/session` reports the authenticated role while retaining `public_demo_mode=true` and `max_rows=20`.

- [ ] Write failing tests for both demo accounts, role-specific session payloads, logout, and public row cap.
- [ ] Run `pytest tests/test_auth.py tests/test_settings.py tests/test_app.py -q` and confirm the new account cases fail against the single-account/public-identity implementation.
- [ ] Extend settings/auth resolution to validate two PBKDF2 hashes and two user/role pairs without storing plaintext passwords.
- [ ] Remove the configuration contradiction that forbids password auth in public demo mode; keep public demo restricted to seeded read-only data and analyst local fallback when no cookie exists.
- [ ] Update `/auth/login` to rate-limit attempts and issue the correct role in the signed HttpOnly cookie.
- [ ] Render a login card that lists both identities, their permitted capabilities, and the fixed demo passwords with a copy-friendly but non-secret demo notice.
- [ ] Show logout for authenticated public demo sessions and keep admin navigation conditional on the backend role.
- [ ] Run the focused auth/settings/app tests and confirm all pass.
- [ ] Commit as `feat: add role-aware public demo login`.

### Task 2: Add Deterministic Low-Risk Assistant Replies

**Files:**
- Modify: `src/retail_analytics_agent/request_routing.py`
- Modify: `src/retail_analytics_agent/analysis_service.py`
- Modify: `frontend/src/Workspace.tsx`, `frontend/src/localization.ts`
- Test: `tests/test_request_routing.py`, `tests/test_analysis_service.py`, `tests/test_workflow.py`, `frontend/smoke/console-smoke.mjs`

**Interfaces:**
- `classify_preflight_request(question, now=...)` returns an assistant decision for capability, greeting, acknowledgement, and Shanghai-time questions.
- `AssistantResult` continues to use `reason_code`, `answer`, and `trace`, with no SQL or database result.

- [ ] Add failing routing tests for `你能做什么`, `现在几点`, `上海现在几点`, and unsupported operational questions.
- [ ] Run the focused routing/workflow tests and confirm time/capability cases currently fail or enter the wrong route.
- [ ] Implement deterministic Asia/Shanghai time formatting and capability copy; do not call the model or database for these routes.
- [ ] Keep unsupported metrics and unsafe requests on the existing rejection path, and keep ambiguous analytics on clarification.
- [ ] Render assistant replies as a compact answer state with only `scope -> respond` active and all analysis stages gray.
- [ ] Run focused backend tests and the frontend build.
- [ ] Commit as `feat: answer low-risk assistant questions`.

### Task 3: Make Workflow State Event-Accurate

**Files:**
- Modify: `src/retail_analytics_agent/analysis_service.py`
- Modify: `frontend/src/Workspace.tsx`, `frontend/src/components.tsx`, `frontend/src/styles.css`
- Test: `tests/test_analysis_service.py`, `tests/test_workflow.py`, `frontend/smoke/console-smoke.mjs`

**Interfaces:**
- Rejection stream events carry the actual terminal node (`scope`, `validate_sql`, or `request_approval`) instead of the synthetic `fail` alias.
- Frontend stage state is `idle | running | success | warning | danger | skipped` and never infers success from ordinal position.

- [ ] Add a regression test asserting a rejected approval emits no successful `execute_sql` or `summarize` stage.
- [ ] Run the regression test and confirm the current `fail -> summarize` alias produces the bad state.
- [ ] Remove ordinal auto-success behavior and map each received status/result/rejection event to its exact node.
- [ ] Mark unvisited stages gray/skipped on terminal rejection, assistant response, empty result, and transport failure.
- [ ] Add explicit copy stating “未访问数据库” for scope, permission, and approval rejection.
- [ ] Add a muted gray CSS state and preserve responsive horizontal scrolling on small screens.
- [ ] Run backend regression tests and a production frontend build.
- [ ] Commit as `fix: render workflow states from actual events`.

### Task 4: Improve Row Limits and Trend Chart Labels

**Files:**
- Modify: `frontend/src/Workspace.tsx`, `frontend/src/ResultChart.tsx`, `frontend/src/styles.css`
- Test: `frontend/smoke/console-smoke.mjs` plus the production TypeScript build

**Interfaces:**
- The max-row control clamps values to `1..session.max_rows` and displays the public limit.
- ECharts x-axis retains all categories, formats date-like values as `MM-DD`, uses calculated label intervals, and keeps full values in tooltip.

- [ ] Add failing assertions for `0888` clamping and date label formatting/interval selection.
- [ ] Implement a shared clamp and date-label formatter that handles ISO dates without changing non-date dimensions.
- [ ] Set ECharts `axisLabel.interval` from point count, hide overflow, and configure tooltip formatter with the original full date.
- [ ] Update visible copy to explain `1-20` public rows and aggregation defaults.
- [ ] Run TypeScript build and the browser smoke path at desktop and mobile widths.
- [ ] Commit as `fix: clarify public row limits and chart dates`.

### Task 5: Add Browser-Local Multi-Conversation Storage

**Files:**
- Create: `frontend/src/conversations.ts`
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/Workspace.tsx`, `frontend/src/components.tsx`, `frontend/src/styles.css`
- Test: `frontend/smoke/console-smoke.mjs` with a browser-local storage contract assertion

**Interfaces:**
- `ConversationStore` exposes `load(userId)`, `save(userId, conversations)`, `create(userId)`, `remove(userId, conversationId)`, and `appendTurn(userId, conversationId, turn)`.
- `Conversation` contains `id`, `title`, `createdAt`, `updatedAt`, bounded `turns`, and derived `auditSummary`.
- `ConversationTurn` contains question, request id, timestamp, outcome status, answer summary, rows/chart when safe to restore, and structured `followUpContext`.

- [ ] Add a browser smoke assertion for account namespacing, bounded history, create/remove, malformed JSON recovery, and audit summary counts.
- [ ] Run the smoke assertion and confirm it fails before the storage module is wired.
- [ ] Implement versioned `localStorage` serialization with a per-user key, size-safe truncation, and graceful fallback when storage is unavailable.
- [ ] Add a conversation rail with new, select, and delete actions; use familiar icons with accessible labels and confirmation for delete.
- [ ] Persist completed assistant, rejected, pending, failed, and successful analysis turns without storing raw SQL or hidden trace.
- [ ] Restore a selected turn into the workspace and show the conversation audit summary.
- [ ] Run frontend type/build checks and storage tests.
- [ ] Commit as `feat: add browser-local conversation history`.

### Task 6: Add Explicit Structured Context Follow-Up

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/Workspace.tsx`, `src/retail_analytics_agent/models.py` only if request metadata needs a backward-compatible field
- Test: `tests/test_app.py`, `tests/test_workflow.py`, frontend conversation tests

**Interfaces:**
- `streamAnalysis` accepts optional `conversation_id` and `previous_context` metadata; the server treats it as untrusted context and still runs the normal workflow.
- `FollowUpContext` contains only metric/dimension/time/filter/result-column summaries and a bounded prior answer.

- [ ] Add failing API tests proving context metadata is accepted, bounded, and cannot replace `user_id`, role, or generated SQL.
- [ ] Implement the optional request metadata without changing existing clients or audit identity rules.
- [ ] Add a “基于此结果继续” action that injects the selected turn’s context into the next question and disables it for rejected/failed turns.
- [ ] Route ambiguous follow-ups to clarification rather than guessing missing metric or date range.
- [ ] Persist the new turn and update the conversation audit summary after stream completion.
- [ ] Run focused API/workflow tests and the frontend build.
- [ ] Commit as `feat: support bounded context follow-ups`.

### Task 7: Full Verification, Documentation, Push, and Deployment

**Files:**
- Modify: `README.md`, `docs/INTERVIEW_DEMO_SCRIPT.md`, deployment/smoke documentation as needed
- Test: full repository test and frontend build/smoke commands

- [ ] Run the isolated `.venv-codex` full `pytest` suite and record the result.
- [ ] Run `npm run build` in `frontend` and `npm run smoke` against the local/public configuration.
- [ ] Inspect `git diff --check`, changed-file status, and ensure `docs/PROJECT_HANDOFF.md` remains untracked and untouched.
- [ ] Update the interview script with the two accounts, role contrast, conversation audit summary, and bounded context explanation.
- [ ] Commit documentation and verification changes as `docs: document public demo walkthrough`.
- [ ] Push `main` to `origin` and monitor the deploy workflow until it completes.
- [ ] Recheck the public URL for analyst login, admin login, rejection gray states, time/capability replies, refresh history, and mobile layout.
