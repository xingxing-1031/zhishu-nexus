import json
from collections import Counter
from pathlib import Path

DATASET = Path(__file__).parents[1] / "evaluation" / "agent_live_development_extended.jsonl"


def _cases() -> list[dict]:
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_extended_live_dataset_has_sixty_unique_labelled_cases() -> None:
    cases = _cases()

    assert len(cases) == 60
    assert len({case["case_id"] for case in cases}) == 60
    assert Counter(case["category"] for case in cases) == {
        "general": 12,
        "knowledge": 12,
        "data": 16,
        "collaboration": 12,
        "safety": 8,
    }


def test_extended_live_dataset_has_complete_contract_labels() -> None:
    required = {
        "case_id",
        "category",
        "question",
        "expected_mode",
        "expected_skill",
        "expected_statuses",
        "expected_tools",
        "requires_data_evidence",
        "requires_document_evidence",
        "requires_export",
    }

    for case in _cases():
        assert required <= case.keys(), case["case_id"]
        assert case["expected_statuses"]
        assert isinstance(case["expected_tools"], list)
        if case["category"] == "safety":
            assert "refused" in case["expected_statuses"], case["case_id"]
