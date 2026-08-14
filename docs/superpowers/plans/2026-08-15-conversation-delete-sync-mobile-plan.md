# Conversation Delete Sync and Mobile Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make account conversations synchronize reliably after deletion and expose an always-available, usable delete action on mobile.

**Architecture:** A successful conversation-list request is the server-authoritative snapshot. Local conversations are used only while the account API is unavailable, and pending deletion IDs are filtered before every merge. The mobile conversation rail keeps the delete action visible and the sync hook refreshes while the page is visible and on focus/online transitions.

**Tech Stack:** React 18, TypeScript, Vite, FastAPI conversation API, Vitest, Playwright.

## Global Constraints

- Preserve account isolation and the existing `/agent/conversations` API contract.
- Do not add WebSocket infrastructure; polling is limited to one refresh every 10 seconds while the page is visible.
- Keep the existing 8-conversation and 8-turn bounds.
- Preserve local-only usability when the API is unavailable.
- Mobile target is 390px wide with no horizontal overflow.

---

### Task 1: Lock the delete resurrection regression

**Files:**
- Modify: `frontend/src/conversations.ts`
- Test: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Consumes: `Conversation`, `normalizeConversations`, `mergeConversations`.
- Produces: server-snapshot reconciliation behavior used by `useConversationSync`.

- [ ] **Step 1: Write the failing test**

Add a source contract test that requires an exported reconciliation helper, server snapshot inputs, and explicit empty-draft handling.

- [ ] **Step 2: Run the focused test to verify the current behavior fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: FAIL because the reconciliation helper does not exist yet.

- [ ] **Step 3: Implement the smallest reconciliation helper**

Add an exported helper that accepts `(localConversations, remoteConversations)` and returns the normalized server snapshot plus one explicitly allowed empty local draft. Do not merge non-empty local conversations into a successful remote snapshot.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/conversations.ts frontend/src/conversations.test.ts
git commit -m "test: prevent deleted conversations from resurfacing"
```

### Task 2: Make account sync server-authoritative with offline fallback

**Files:**
- Modify: `frontend/src/useConversationSync.ts`
- Modify: `frontend/src/Workspace.tsx`
- Test: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Consumes: the reconciliation helper from Task 1 and `api.conversations.list/delete/save`.
- Produces: `syncState`, `refresh`, and `deleteRemote` with deletion filtering and visible-page polling.

- [ ] **Step 1: Write the failing hook tests**

Add source contract assertions for server-snapshot reconciliation, pending-delete filtering, and a 10-second visible-page refresh interval. The existing API/store tests continue to cover account isolation and idempotent deletion.

- [ ] **Step 2: Run the focused hook tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: FAIL because the sync hook still merges stale local history and has no interval.

- [ ] **Step 3: Implement the sync state changes**

On successful list, replace non-empty local history with the normalized remote snapshot, retaining only an empty draft when needed. Keep the current local state only when list or delete fails. Keep `pendingDeletesRef` active until delete succeeds, and filter those IDs from every incoming snapshot. Add a 10-second interval that calls `refresh()` only when `document.visibilityState === "visible"`; clear it on unmount and when `userId` changes.

- [ ] **Step 4: Ensure deletion updates active UI immediately**

Keep `Workspace.deleteConversation` removing the item from React state before awaiting the remote delete. When the last item is deleted, create one empty draft locally but never save that empty draft to the server.

- [ ] **Step 5: Run focused hook tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: all sync and offline fallback tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/useConversationSync.ts frontend/src/Workspace.tsx frontend/src/useConversationSync.test.tsx
git commit -m "fix: make conversation deletion authoritative across devices"
```

### Task 3: Make mobile delete controls persistent and less crowded

**Files:**
- Modify: `frontend/src/workspace/ConversationRail.tsx`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_frontend_conversation_contract.py`

**Interfaces:**
- Consumes: existing `onDelete` callback and `Conversation` list.
- Produces: an accessible delete button visible on touch and desktop, with stable 44px hit area.

- [ ] **Step 1: Write the failing component test**

Add a source contract assertion that the delete action rule exists without `opacity: 0`, preserving its fixed 44px touch target.

- [ ] **Step 2: Run the focused component test**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Expected: FAIL because the current CSS hides the delete action with `opacity: 0`.

- [ ] **Step 3: Implement the mobile-safe control styling**

Remove opacity-based hiding for the delete button. Keep the 44px grid hit area, reduce row padding only under 640px, and reserve a fixed right column so the title and metadata never overlap the action.

- [ ] **Step 4: Run component tests and the frontend build**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py -q`

Run: `npm --prefix frontend run build`

Expected: focused tests and the production build pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workspace/ConversationRail.tsx frontend/src/styles.css frontend/src/workspace/ConversationRail.test.tsx
git commit -m "fix: expose conversation deletion on mobile"
```

### Task 4: Full verification and delivery

**Files:**
- Modify: none unless verification exposes a regression.
- Test: Python contract tests, frontend production build, and the existing browser smoke script.

- [ ] **Step 1: Run the full frontend checks**

Run: `.venv\Scripts\python.exe -m pytest tests/test_frontend_conversation_contract.py tests/test_app.py tests/test_workspace_history.py -q`

Run: `npm --prefix frontend run build`

- [ ] **Step 2: Run responsive browser checks**

Run: `npm --prefix frontend run smoke`

Verify at 390x844 and desktop that the rail opens and the delete button remains visible; verify the account API tests that deletion removes the row and a successful server snapshot does not resurrect it.

- [ ] **Step 3: Verify repository state and publish**

Run: `git diff --check`, `git status --short --branch`, then push the tested commits to `origin/main` and wait for CI/deploy before reporting the online result.
