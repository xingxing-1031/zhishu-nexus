# Remove Guided Demo Rail Design

## Goal

Keep the public analysis workspace focused on real analyst work instead of a
scripted product tour. An interviewer can drive the existing questions and
scenarios directly; the application should make the resulting workflow,
business result, and audit evidence easy to read.

## Scope

- Remove the three-button guided demo rail from the query panel.
- Remove its click handlers, focused-evidence hint, styles, and smoke-check
  marker.
- Keep the standard question input, example scenarios, row limit, and run
  action unchanged.
- Keep the existing result hierarchy: workflow status, conclusion, chart,
  result table, and audit evidence.

## Interaction Model

Before a request, the workspace presents a quiet empty state and lets the
user choose an example scenario or enter a question. During a request, the
workflow remains the visible progress indicator. After a request, the result
and its plan, retrieval evidence, and business constraints remain visible in
their existing cards without requiring a separate tour action.

## Non-Goals

- Do not change backend APIs, access roles, approvals, or public-demo
  security boundaries.
- Do not add a mock approval path or any new presentation-only data.
- Do not change the existing demo dataset.

## Data Decision

The current dataset is sufficient for a recruiting demo and must not be
expanded in this change. The richer seed deterministically adds 120 orders
across four channels and a 75-day window, with 16 products and varied order
states. It also adds 24 refunds across a 70-day window, five reasons, and four
refund states. Together with the baseline records, the public overview shows
130 orders, 30 refunds, and 73 coverage days. This supports rankings, daily
trends, product comparisons, refund-status comparisons, and access-boundary
demonstrations without inflating the project scope.

## Recruiting Readiness

- Re-check the public homepage, mobile layout, public-demo identity message,
  and public security boundary after the simplified frontend is published.
- Preserve the public analyst-only boundary. The public demo proves a
  pre-execution rejection; the approval drawer remains a controlled
  administrator demonstration and is not exposed to visitors.
- Add a concise three-minute interview walkthrough covering real analysis,
  safety rejection, approval/SQL/audit correspondence, and degraded or failed
  result handling. The walkthrough must distinguish what is publicly
  demonstrable from what requires the protected administrator environment.

## Verification

- TypeScript checks and production asset build pass.
- The static-asset test continues to validate the current stylesheet contract
  without depending on the removed rail.
- The public smoke check continues to verify the packaged JavaScript bundle,
  public-demo session boundary, and demo dataset counts.
- Public-page verification confirms the workspace no longer renders the rail
  and a real analysis still shows result and audit evidence.
- The interview walkthrough names the exact questions and observable UI
  states, rather than claiming unverified capabilities.
