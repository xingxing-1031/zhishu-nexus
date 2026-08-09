# Retail Demo Experience Design

**Goal:** Make the recruiting-facing retail analytics demo feel intentional, fast to understand, and trustworthy without expanding the product into a larger platform.

## Audience And Success Criteria

- Primary audience: an interviewer opening the public URL for the first time, without credentials.
- Secondary audience: the project owner demonstrating the protected administrator flow locally or on a private HTTPS environment.
- The first screen must remain a usable analysis workspace, not a marketing landing page.
- A visitor should understand the value of real data, constrained analysis, and auditability within one minute.
- The public mode must not expose administrator approval, sensitive refund reasons, or raw execution Trace.
- The protected mode must continue to expose the existing approval, audit, metrics, and Trace capabilities without changing their server authority.

## Chosen Direction

Use a calm operations-console visual system with one memorable interaction: a compact "演示路径" rail that turns three real capabilities into explicit actions:

1. `先看一个真实结果` runs an ordinary sales query using the existing SSE workflow.
2. `看一次安全拒绝` runs a public-safe request that ends before database execution and explains the boundary.
3. `查看可信依据` keeps the existing result, chart, plan, evidence, and business rules visible in a deliberate evidence panel.

The rail is part of the workbench and does not replace the query form. It uses real server responses; it must never fabricate rows, SQL, or model reasoning. The ordinary case remains the default action.

## Public And Protected Presentation

- Public demo remains no-login, analyst-only, rate-limited, and max-20-rows.
- Public UI labels the environment as a demonstration and explains that sensitive administrator actions are intentionally unavailable.
- The public UI may show a sanitized security explanation and the deterministic rejection result, but not a simulated approval action.
- Protected password mode remains a separate route/configuration for private demonstration after HTTPS is available. No client-side role switching is added.
- The approval drawer stays server-triggered and only renders for an authenticated administrator.

## Visual System

- Palette: ink navy `#121B2E`, teal `#0F766E`, electric blue `#2563EB`, canvas `#F5F7FA`, warm warning `#B54708`, danger `#B42318`.
- Typography: Noto Sans SC for Chinese UI text; JetBrains Mono/Cascadia Code for request ids, SQL, and numeric values.
- Layout: persistent desktop sidebar, sticky query panel, evidence-led result area, bottom navigation on mobile.
- Motion: only stage transitions, button progress, and drawer entry; respect `prefers-reduced-motion`.
- Signature: the workflow rail changes from idle to verified states as the real request progresses, giving the interviewer a visible explanation of the agent pipeline.

## Data And Test Scope

- Keep the current 130-order demo dataset unless verification shows that a scenario lacks meaningful variation.
- Add only deterministic, business-meaningful fixture assertions for channel contrast, trend coverage, refund status distribution, empty results, rejection, approval-required, degradation, and row limits.
- Add frontend smoke/e2e coverage for public bootstrap, the three demo paths, responsive layout, and the protected approval drawer using mocked API responses. Do not make tests dependent on the live VPS or a model API.
- Verify that the static bundle served by the application matches the current frontend source after a clean build.

## Out Of Scope

- No multi-tenant authentication, billing, real-time collaboration, exports, or notification system.
- No public administrator account and no weakening of the current SQL/security boundaries.
- No arbitrary increase in demo data volume solely to make KPI numbers larger.
