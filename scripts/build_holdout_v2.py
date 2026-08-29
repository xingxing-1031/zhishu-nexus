"""Create a new independent holdout after the prior split was accidentally replayed."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = root / "evaluation/final/agent-live-holdout-final.jsonl"
dst = root / "evaluation/final/agent-live-holdout-final-v2.jsonl"
rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
for row in rows:
    row["case_id"] = "v2-" + row["case_id"]
    row["question"] = "请在本次独立验收中回答：" + row["question"]
dst.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
print(f"wrote {len(rows)} cases to {dst}")
