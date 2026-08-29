"""Create the post-Trace-fix holdout without mutating v2 history."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = root / "evaluation/final/agent-live-holdout-final-v2.jsonl"
dst = root / "evaluation/final/agent-live-holdout-final-v3.jsonl"
rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
for row in rows:
    row["case_id"] = "v3-" + row["case_id"]
    row["question"] = "请在修复 Trace 后的独立验收中回答：" + row["question"]
dst.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
print(f"wrote {len(rows)} cases to {dst}")
