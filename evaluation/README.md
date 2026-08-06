# Evaluation artifacts

The repository keeps development data separate from frozen holdout data. A
holdout result is only valid while its questions and labels have not been used
to tune prompts, retrieval thresholds, model selection or business rules.

## W6-1 end-to-end business benchmark

| File | Cases | Purpose |
|---|---:|---|
| `business_development.json` | 40 | Diagnose failures and improve the system |
| `business_holdout.json` | 20 | One-time final evaluation after the system is fixed |

The 60 independent cases cover 15 basic analyses, 15 complex analyses, 10
unsupported requests, 10 access-control boundaries and 10 deterministic
resilience scenarios. Gold labels were written before model execution.

Every case records the user question, trusted role, expected outcome and the
stage-level expectations needed to locate a failure. Successful and degraded
cases additionally contain:

- a human-labelled `AnalysisPlan`;
- expected metric and Schema evidence source IDs;
- human-reviewed parameterized Gold SQL;
- exact rows from the fixed PostgreSQL snapshot;
- the deterministic chart type.

Rejected, failed and approval-required cases store a reason code instead of
inventing a result. Resilience cases also identify the component, occurrence
and error type to inject.

### Fixed snapshot

```text
reference_time = 2026-08-16T12:00:00+08:00
timezone = Asia/Shanghai
seed_snapshot_id = retail-demo-evaluation-2026-08-16-v1
```

Relative ranges are evaluated as `[reference_time - days, reference_time)`.
The Gold verifier temporarily replaces the relative seed timestamps with
absolute snapshot timestamps inside one transaction. It executes every trusted
Gold query, compares ordered rows exactly, and always rolls the transaction
back so the development database is unchanged.

```powershell
python scripts/build_w6_1_dataset.py
python scripts/verify_w6_1_gold.py
```

Model SQL is not required to match the Gold SQL string. W6-2 will score the
plan, retrieved evidence, safety outcome, exact result rows and final response
semantics separately. This allows an equivalent SQL query to pass while still
showing which stage caused a wrong final answer.

### Holdout leakage rule

Do not inspect a holdout failure and then tune the current system against that
case while continuing to report the same file as a final holdout. Once a
holdout example influences implementation, move it into development evidence
and create a new independent holdout before reporting another final score.

## W4-3 retrieval benchmark

| File | Purpose |
|---|---|
| `retrieval_gold.json` | Human-labelled `AnalysisPlan` to complete evidence evaluation |
| `metric_query_gold.json` | Natural-language development set for keyword, vector and hybrid comparison |
| `metric_query_validation.json` | Independent development set used only for distance-threshold selection |
| `metric_query_holdout.json` | Final 20-case holdout, evaluated once after prompts and thresholds were fixed |

The `reports` directory contains the W4-3 retrieval baselines and the one-time
holdout result. Those reports measure retrieval only; they are separate from
the W6 end-to-end business benchmark.

## W6-2 run records and scoring

`EvaluationRunRecord` stores one raw Agent execution. `variant` identifies the
controlled comparison (`baseline`, `retrieval` or `reranker`) and `run_index`
identifies a repeated run of the same case. Every run is kept; the evaluator
must not select only the best output.

`score_case` evaluates these stages independently:

```text
plan -> evidence -> SQL/safety -> outcome -> rows -> chart -> answer
```

`core_result_score` covers the plan, evidence, SQL/safety, outcome, rows and
chart stages. `answer_score` is separate because a correct database result can
still be degraded when the summarizer fails. `summarize_variant` reports all
runs for one variant, including stage pass rates, latency range and total
retries. These functions are pure and do not call a model or PostgreSQL.

`ControlledExperiment` is the comparison contract. It only permits the
development split and requires identical model, dataset version, PostgreSQL
snapshot, reference time, safety policy, access policy and timeout settings
across variants. A mismatch is rejected before any comparison is reported.

`run_development_experiment` is the orchestration layer for this contract. It
checks that the suite is an unfrozen development suite, verifies the snapshot
and reference conditions, invokes each supplied executor for every case and
repetition, scores each raw run, and aggregates every run into an
`ExperimentReport`. It does not implement retrieval, SQL generation, model
calls or database access itself; those remain behind the variant executors.

The real executors are intentionally still a follow-up task. The current
`CatalogRetrievalTool` runs after an `AnalysisPlan` and returns deterministic
catalog evidence, while the Hybrid/Reranker path recalls metrics from the raw
natural-language query. They have different input and output contracts, so
they cannot be swapped into the same method and called a fair baseline,
retrieval and reranker comparison without first defining the exact variable
that each variant changes.

`AnalysisEvaluationObservation` is the internal observation boundary between
the LangGraph checkpoint and an evaluation executor. It copies the plan,
evidence source IDs, generated SQL, SQL safety result, rows, chart, answer,
errors, retries and trace from the trusted snapshot. These fields are not
added to the public `AnalysisResponse`. The observation deliberately has no
`evidence_match` field because runtime SQL-to-evidence consistency validation
has not been implemented; an executor must not invent a passing value.
