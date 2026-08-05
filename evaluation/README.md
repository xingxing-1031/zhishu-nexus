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
