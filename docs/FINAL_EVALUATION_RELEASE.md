# Final Evaluation Release

This document defines the single evaluation release that may supply metrics for
the resume. Historical reports remain available for audit, but are not valid
resume evidence after this release is published.

## Release identity

The release is created from the final project commit and a clean, reproducible
data build. The release manifest must record:

- project commit SHA;
- database seed script SHA and database snapshot SHA;
- knowledge corpus manifest SHA and index build configuration;
- evaluation dataset SHAs;
- model IDs and runtime configuration;
- evaluation date, timezone, and reference time;
- commands used to build, verify, and run each suite.

The live demo database is not a valid evaluation database. The final run may
execute on the VPS so it uses the real model API and deployment network, but it
must target a separate evaluation database (or an exported immutable snapshot),
never the mutable public demo database.

## Data profile

The default final profile is intentionally realistic but bounded:

| Asset | Final size | Purpose |
|---|---:|---|
| Retail database | about 1,000 orders, 16 products, 4 channels, 150-180 days | realistic filters, aggregation, refund and empty-result cases |
| Enterprise corpus | about 30 policy documents, 150-300 indexed chunks | versioning, permissions, citations, stale-document refusal |
| Agent evaluation | 100 development + 30 independent holdout cases | broad capability coverage plus one final generalization check |
| Cross-dataset evaluation | 28 development + 13 independent holdout cases | schema mapping and migration behavior |
| Runtime/security probes | 21 development + 12 frozen probes + 10 injection probes | contracts, failure attribution and safety boundaries |
| Browser journeys | 8-12 scripted journeys | end-to-end UI, SSE, approval, recovery and permission behavior |

Synthetic data is acceptable and preferred for this portfolio project when it
is generated from explicit business rules, validated by constraints, and frozen
before evaluation. It must be described as controlled synthetic data, never as
production data.

## Build rules

1. Build the database from an empty PostgreSQL instance using the final seed
   scripts. Do not reuse a mutable demo database.
2. Generate timestamps from a fixed reference time and seed. Do not use
   `CURRENT_TIMESTAMP` in a final snapshot without recording the resulting
   export and reference time.
3. Import and index the knowledge corpus from a clean store. Record every file
   hash, document version, permission scope, embedding model and reranker.
4. Derive Gold SQL and expected rows with trusted SQL inside a read-only,
   rolled-back transaction. Never derive labels from model answers.
5. Freeze the holdout before running it. A holdout failure that influences code
   invalidates that holdout and requires a newly labelled one.

## Authoritative metrics

Only metrics from the final release report may be copied into the resume:

- Agent case pass rate and its denominator;
- mode routing and tool selection accuracy;
- business non-failure rate;
- safety refusal and permission leakage rate;
- evidence/citation accuracy;
- P50/P95 latency, with retry and timeout policy stated;
- RAG Recall@5 and independent holdout core pass rate;
- automated test and browser-journey pass counts.

Every metric must link to a raw JSON report and a reproducible command. A
single aggregate score is not used as the resume headline; vector metrics make
the result explainable in an interview.

## Archive boundary

Existing reports and datasets are historical evidence. They must remain
read-only under an archive or historical label and must not be silently edited
or mixed into the final summary. The final release directory is the only source
used when updating the resume.
