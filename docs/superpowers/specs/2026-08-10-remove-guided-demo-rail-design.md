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

## Verification

- TypeScript checks and production asset build pass.
- The static-asset test continues to validate the current stylesheet contract
  without depending on the removed rail.
- The public smoke check continues to verify the packaged JavaScript bundle,
  public-demo session boundary, and demo dataset counts.
- Public-page verification confirms the workspace no longer renders the rail
  and a real analysis still shows result and audit evidence.
