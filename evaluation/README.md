# Retrieval evaluation artifacts

W4-3 separates development evidence from the one-time final holdout result.

## Datasets

| File | Purpose |
|---|---|
| `retrieval_gold.json` | Human-labelled `AnalysisPlan` to complete evidence evaluation |
| `metric_query_gold.json` | Natural-language development set for keyword, vector and hybrid comparison |
| `metric_query_validation.json` | Independent development set used only for distance-threshold selection |
| `metric_query_holdout.json` | Final 20-case holdout, evaluated once after prompts and thresholds were fixed |

## Reports

| File | Meaning |
|---|---|
| `catalog_baseline.json` | Deterministic catalog evidence baseline |
| `keyword_metric_baseline.json` | Literal keyword baseline on the development set |
| `vector_metric_baseline.json` | Unthresholded `bge-m3` Top-5 baseline |
| `hybrid_metric_top1.json` / `hybrid_metric_top5.json` | RRF fusion baselines without hard distance filtering |
| `vector_threshold_validation.json` | Threshold selection experiment; diagnostic evidence, not the final retrieval policy |
| `llm_reranker_qwen3_0_6b_initial.json` | Initial 0.6B LLM reranker experiment |
| `llm_reranker_qwen3_4b.json` | 4B reranker-only development result |
| `domain_gated_development_only_qwen3_4b.json` | Development-only result affected by prompt/test overlap; not a final score |
| `domain_gated_metric_query_holdout_qwen3_4b.json` | One-time final holdout result: 85% exact match |

Do not tune prompts or thresholds against `metric_query_holdout.json` and continue to call it a holdout. Once a failure from that file is used for development, a new independent holdout is required for another final evaluation.
