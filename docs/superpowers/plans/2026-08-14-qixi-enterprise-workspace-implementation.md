# Qixi Enterprise Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the card-heavy analytics console with a conversation-first enterprise AI workspace that embeds results in messages and exposes evidence through a responsive inspector.

**Architecture:** Keep the existing FastAPI endpoints, SSE client, approval flow, conversation persistence, and response types. Refactor the React workspace into focused conversation, response, inspector, and composer components; derive all new UI state from the existing `AgentResponse` and `AnalysisOutcome` models.

**Tech Stack:** React 18, TypeScript 5.7, Vite 6, ECharts 6, Lucide React, CSS design tokens, existing browser smoke test.

## Global Constraints

- Do not change backend API contracts, permissions, approval semantics, audit behavior, or metric definitions.
- The main experience is a continuous conversation, not a KPI dashboard.
- Body text is 15-16px; required content must not be smaller than 12px.
- Use `#0F766E` for brand interaction, `#2563EB` for data emphasis, and semantic green/amber/red states.
- Do not use purple-pink AI gradients, glassmorphism, decorative blobs, nested cards, or marketing hero layouts.
- Use 6px regular radii and no more than 8px for panels and drawers.
- ECharts and admin pages remain lazy or route-loaded where practical.
- Support 375px, 768px, 1024px, and 1440px viewport widths.
- Preserve keyboard operation, visible focus, reduced motion, and text alternatives for charts.

---

### Task 1: Introduce Conversation Message View Models

**Files:**
- Modify: `frontend/src/conversations.ts`
- Modify: `frontend/src/types.ts`
- Create: `frontend/src/chatModels.ts`
- Test: `frontend/smoke/console-smoke.mjs`

**Interfaces:**
- Consumes: existing `Conversation`, `ConversationTurn`, `AgentResponse`, `AnalysisOutcome`.
- Produces: `ChatMessage`, `AssistantMessageState`, `buildAssistantMessage()`, and stable per-turn inspector data.

- [ ] **Step 1: Add smoke assertions for restored conversation messages**

Extend the browser smoke flow to assert that a submitted user question and the resulting assistant answer both remain visible after a second question.

- [ ] **Step 2: Run smoke test to capture the current failure**

Run: `npm run smoke`

Expected: FAIL because the current workspace restores one selected result rather than rendering a continuous message thread.

- [ ] **Step 3: Add explicit message view models**

Create models shaped like:

```ts
export type ChatMessage =
  | { id: string; role: "user"; content: string; createdAt: string }
  | {
      id: string;
      role: "assistant";
      requestId: string;
      status: "running" | "succeeded" | "degraded" | "pending" | "rejected" | "failed";
      answer: string;
      outcome: AnalysisOutcome | null;
      response: AgentResponse | null;
      failure: string;
      stageState: StoredStageState;
      createdAt: string;
      durationMs: number | null;
    };
```

Add deterministic conversion helpers from stored turns and active streaming state.

- [ ] **Step 4: Run TypeScript build**

Run: `npm run build`

Expected: PASS with no changes to backend response types.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/chatModels.ts frontend/src/conversations.ts frontend/src/types.ts frontend/smoke/console-smoke.mjs
git commit -m "refactor: model qixi conversations as chat messages"
```

### Task 2: Build the Workspace Shell and Conversation Rail

**Files:**
- Create: `frontend/src/workspace/WorkspaceShell.tsx`
- Create: `frontend/src/workspace/ConversationRail.tsx`
- Create: `frontend/src/workspace/WorkspaceHeader.tsx`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/components.tsx`

**Interfaces:**
- Consumes: `SessionInfo`, `Conversation[]`, active conversation id, existing create/select/delete callbacks.
- Produces: responsive three-region shell with `main`, `nav`, and inspector slots.

- [ ] **Step 1: Move conversation navigation into `ConversationRail`**

Reuse the existing persistence callbacks while replacing the separate sidebar query panel with a rail containing brand context, new conversation, history, and admin shortcuts.

- [ ] **Step 2: Add shell state for responsive panels**

Use explicit state:

```ts
const [railOpen, setRailOpen] = useState(false);
const [inspectorOpen, setInspectorOpen] = useState(true);
```

Desktop renders the inspector as a column. Tablet uses a right drawer. Mobile uses a bottom sheet.

- [ ] **Step 3: Remove the KPI strip from the default workspace**

Keep overview data available through a compact workspace information popover or the empty conversation suggestions; do not render six top-level overview cards.

- [ ] **Step 4: Verify semantic layout**

Ensure one `main` landmark, labeled navigation, sequential headings, and a skip-to-content link.

- [ ] **Step 5: Run build**

Run: `npm run build`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/workspace frontend/src/Workspace.tsx frontend/src/components.tsx
git commit -m "feat: add enterprise conversation workspace shell"
```

### Task 3: Render Continuous Chat and Inline Analysis Results

**Files:**
- Create: `frontend/src/workspace/ChatThread.tsx`
- Create: `frontend/src/workspace/AssistantResponse.tsx`
- Create: `frontend/src/workspace/AgentProgress.tsx`
- Create: `frontend/src/workspace/ResultTable.tsx`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/ResultChart.tsx`

**Interfaces:**
- Consumes: `ChatMessage[]`, active streaming state, `AnalysisResult`, `AgentResponse`.
- Produces: continuous messages, result modules, status summary, follow-up actions, and inspector selection callbacks.

- [ ] **Step 1: Render stored turns as user/assistant message pairs**

The current conversation must render every turn in chronological order. New streaming messages append to the end and update in place.

- [ ] **Step 2: Add assistant answer hierarchy**

Render answer content in this order:

```text
status and mode
direct answer
limitations or risk note
chart and table when present
report findings when present
citations and evidence action
follow-up action
```

- [ ] **Step 3: Add compact Agent progress**

Show only the current message and terminal status in the thread. The “查看过程” action selects the execution tab in the inspector.

- [ ] **Step 4: Add inline chart and accessible table**

Keep `ResultChart` lazy-loaded. Add a concise text summary and ensure the table remains present as the accessible alternative.

- [ ] **Step 5: Preserve scroll behavior**

Auto-scroll only when the user is already near the bottom. Do not pull the user away from an earlier answer while they are reading.

- [ ] **Step 6: Run build and smoke**

Run: `npm run build`

Run: `npm run smoke`

Expected: both PASS, with two consecutive questions visible in one thread.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/workspace frontend/src/Workspace.tsx frontend/src/ResultChart.tsx frontend/smoke/console-smoke.mjs
git commit -m "feat: render qixi analysis as continuous chat"
```

### Task 4: Add Evidence Inspector, Composer, and Approval Sheet

**Files:**
- Create: `frontend/src/workspace/EvidenceInspector.tsx`
- Create: `frontend/src/workspace/MessageComposer.tsx`
- Create: `frontend/src/workspace/ApprovalSheet.tsx`
- Modify: `frontend/src/Workspace.tsx`
- Modify: `frontend/src/api.ts`

**Interfaces:**
- Consumes: selected assistant message, knowledge evidence, data evidence, tool calls, trace events, approval state.
- Produces: `InspectorTab = "sources" | "execution" | "audit"`, keyboard composer actions, and in-thread approval entry.

- [ ] **Step 1: Build inspector tabs**

Sources shows citations, version, effective time, and quotes. Execution shows route, agents, tools, and timing. Audit shows metric evidence, SQL/approval data, request id, and review status.

- [ ] **Step 2: Connect citation and process actions**

Clicking “查看引用” opens `sources`; clicking “查看过程” opens `execution`; clicking the request id or audit action opens `audit`.

- [ ] **Step 3: Build sticky composer**

Implement Enter to submit, Shift+Enter for newline, a visible loading state, disabled duplicate submission, maximum row settings in a compact options menu, and contextual follow-up cancellation.

- [ ] **Step 4: Move approval UI into a responsive sheet**

Retain SQL preview, fingerprint, sensitive fields, approve, reject, and rejection reason. On completion, update the original assistant message rather than switching to a separate result page.

- [ ] **Step 5: Add recovery actions**

Network failure and timeout states include “重新执行”. Chart failure preserves text and table. Evidence failure displays the limitation without an empty inspector section.

- [ ] **Step 6: Run build and smoke**

Run: `npm run build`

Run: `npm run smoke`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/workspace frontend/src/Workspace.tsx frontend/src/api.ts frontend/smoke/console-smoke.mjs
git commit -m "feat: add qixi evidence inspector and composer"
```

### Task 5: Replace the Visual System and Responsive Rules

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/LoginPage.tsx`
- Modify: `frontend/src/AdminPages.tsx`
- Modify: `frontend/src/components.tsx`

**Interfaces:**
- Consumes: component class names introduced in Tasks 2-4.
- Produces: shared color, typography, spacing, elevation, focus, motion, and responsive behavior.

- [ ] **Step 1: Replace root tokens**

Define the approved neutral, teal, blue, and semantic tokens. Set 15px desktop body and 16px mobile form controls.

- [ ] **Step 2: Style the three-region workspace**

Use stable grid tracks, one primary page scroll, 6-8px radii, subtle borders, and shadows only for floating surfaces.

- [ ] **Step 3: Style messages and result modules**

Assistant content remains unframed. User messages use a compact tinted block. Result modules use separators and restrained surfaces rather than nested cards.

- [ ] **Step 4: Add responsive navigation and inspector behavior**

At 1024px the inspector becomes a drawer. At 768px the conversation rail becomes a drawer. At 640px the inspector becomes a bottom sheet and the composer respects mobile safe areas.

- [ ] **Step 5: Align login and admin pages**

Remove the blue-purple login gradient. Apply the same neutral/teal system while preserving the existing demo account and admin functionality.

- [ ] **Step 6: Verify accessibility CSS**

Keep visible `:focus-visible`, `prefers-reduced-motion`, touch targets, wrapping for long ids, and no body text below 12px.

- [ ] **Step 7: Run build**

Run: `npm run build`

Expected: PASS and no new bundle-size regression beyond the existing lazy ECharts chunk.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/styles.css frontend/src/LoginPage.tsx frontend/src/AdminPages.tsx frontend/src/components.tsx
git commit -m "style: redesign qixi as an enterprise ai workspace"
```

### Task 6: Visual QA, Regression, and Deployment

**Files:**
- Modify as required by QA findings: `frontend/src/**`
- Modify: `frontend/smoke/console-smoke.mjs`
- Update: `docs/superpowers/specs/2026-08-14-qixi-enterprise-workspace-design.md` only if implementation intentionally changes an approved rule.

**Interfaces:**
- Consumes: completed workspace.
- Produces: verified production build and deployed UI.

- [ ] **Step 1: Run repository verification**

Run: `npm run build`

Run: `npm run smoke`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `.\.venv\Scripts\python.exe -m ruff check src tests scripts mcp_server`

- [ ] **Step 2: Start the local application**

Run the existing local application stack on unused ports and confirm `/health` and `/ready` before browser testing.

- [ ] **Step 3: Capture and inspect desktop/tablet/mobile screenshots**

Verify 1440x900, 1024x768, 768x1024, and 390x844. Check login, empty conversation, running state, general answer, knowledge answer, data chart/table, collaboration answer, degraded state, and inspector.

- [ ] **Step 4: Fix visual defects and repeat verification**

Reject text overlap, horizontal page scroll, hidden focus, clipped controls, nested scrolling, blank charts, and inaccessible icon controls.

- [ ] **Step 5: Commit QA fixes**

```bash
git add frontend docs/superpowers/specs/2026-08-14-qixi-enterprise-workspace-design.md
git commit -m "fix: complete qixi workspace visual qa"
```

- [ ] **Step 6: Push and monitor CI/deployment**

Run: `git push origin main`

Wait for both CI and `Deploy VPS release` to complete successfully.

- [ ] **Step 7: Run online regression**

Verify health/readiness and execute one general, one knowledge, one data, and one collaboration request through the deployed interface.

