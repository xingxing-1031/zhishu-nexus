"""Build the second controlled synthetic sales dataset for cross-dataset evaluation.

Column names, date range, channel/region values and null patterns intentionally
differ from the fixed public demo tables so the migration claim rests on the
onboarding contract, not on a hard-coded schema. Output is deterministic for a
fixed seed and a SHA-256 snapshot hash is written next to the CSV.
"""

from __future__ import annotations

import csv
import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path

_SEED = 20260826
_ROW_COUNT = 1000
_OUTPUT = Path(__file__).resolve().parents[1] / "evaluation" / "data"

_PRODUCTS = {
    "electronics": ("无线耳机", "智能手表", "蓝牙音箱", "机械键盘", "USB 充电器"),
    "apparel": ("纯棉T恤", "牛仔裤", "卫衣", "运动外套", "针织毛衣"),
    "home": ("保温杯", "台灯", "收纳盒", "地毯", "挂钟"),
}
_CATEGORY_WEIGHTS = (("electronics", 0.40), ("apparel", 0.35), ("home", 0.25))
_SOURCE_WEIGHTS = (("e_commerce", 0.55), ("retail_store", 0.35), ("catalog", 0.10))
_REGION_WEIGHTS = (("north", 0.30), ("south", 0.25), ("east", 0.25), ("west", 0.20))
_CATEGORY_PREFIX = {"electronics": "ELE", "apparel": "APP", "home": "HOM"}


def _weighted(rng: random.Random, weights: tuple[tuple[str, float], ...]) -> str:
    values, probabilities = zip(*weights)
    return rng.choices(values, weights=probabilities, k=1)[0]


def _sale_date(rng: random.Random) -> str:
    day_offset = rng.randint(0, 364)
    moment = datetime(2025, 1, 1, rng.randint(8, 21)) + timedelta(days=day_offset)
    return f"{moment.year}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:00:00Z"


def _rows() -> list[dict[str, object]]:
    rng = random.Random(_SEED)
    rows: list[dict[str, object]] = []
    for index in range(_ROW_COUNT):
        category = _weighted(rng, _CATEGORY_WEIGHTS)
        source = _weighted(rng, _SOURCE_WEIGHTS)
        region = _weighted(rng, _REGION_WEIGHTS)
        if rng.random() < 0.03:
            region = ""
        qty = int(rng.choices((1, 2, 3, 4, 5, 6), weights=(30, 26, 18, 12, 9, 5))[0])
        unit_price = round(rng.uniform(5.0, 120.0), 2)
        gross_amount = round(unit_price * qty, 2)
        cost_amount = "" if rng.random() < 0.08 else round(gross_amount * rng.uniform(0.60, 0.85), 2)
        rows.append(
            {
                "order_no": f"CS-{index + 1:05d}",
                "sku": f"SKU-{_CATEGORY_PREFIX[category]}-{rng.randint(1001, 9999)}",
                "product_name": rng.choice(_PRODUCTS[category]),
                "product_category": category,
                "source": source,
                "region_code": region,
                "qty": qty,
                "gross_amount": gross_amount,
                "cost_amount": cost_amount,
                "sale_date": _sale_date(rng),
            }
        )
    return rows


def main() -> None:
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    csv_path = _OUTPUT / "cross_dataset_sales.csv"
    columns = (
        "order_no",
        "sku",
        "product_name",
        "product_category",
        "source",
        "region_code",
        "qty",
        "gross_amount",
        "cost_amount",
        "sale_date",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(_rows())
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    (_OUTPUT / "cross_dataset_sales.csv.sha256").write_text(
        f"{digest}  cross_dataset_sales.csv\n",
        encoding="utf-8",
    )
    print(f"wrote {csv_path} ({_ROW_COUNT} rows)")
    print(f"sha256={digest}")


if __name__ == "__main__":
    main()
