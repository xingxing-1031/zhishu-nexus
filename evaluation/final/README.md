# Final Evaluation Artifacts

This directory is reserved for the one authoritative evaluation release for
the current project. It is intentionally separate from historical reports.

Expected files:

- `release-manifest.json`: commit, data, model and command identities;
- `database-snapshot.json`: seed and exported snapshot metadata;
- `knowledge-corpus-manifest.json`: document hashes, versions and permissions;
- `agent_development_final.jsonl` and `agent_holdout_final.jsonl`;
- `reports/`: raw run records and aggregate reports;
- `browser/`: Playwright traces, screenshots and journey summaries.

Do not hand-edit aggregate numbers. Rebuild reports from raw run records.
