from __future__ import annotations

from collections.abc import Callable, Iterable
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.agent_models import AgentMode, AgentResponse


class QixiEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=4000)
    expected_mode: AgentMode
    expected_tools: tuple[str, ...] = ()
    expect_knowledge_evidence: bool = False
    expect_data_evidence: bool = False


class QixiEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_mode: AgentMode
    actual_mode: AgentMode | None = None
    expected_tools: tuple[str, ...] = ()
    actual_tools: tuple[str, ...] = ()
    mode_passed: bool = False
    tools_passed: bool = False
    knowledge_evidence_present: bool = False
    data_evidence_present: bool = False
    evidence_passed: bool = False
    review_passed: bool = False
    status: str = "failed"
    latency_ms: int = 0
    error_type: str | None = None


class QixiEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    cases: tuple[QixiEvaluationRecord, ...]
    total: int
    executed: int
    mode_accuracy: float
    tool_accuracy: float
    evidence_accuracy: float
    review_pass_rate: float
    p50_latency_ms: int
    p95_latency_ms: int


def load_qixi_cases(lines: Iterable[str]) -> list[QixiEvaluationCase]:
    return [
        QixiEvaluationCase.model_validate_json(line)
        for line in lines
        if line.strip()
    ]


def evaluate_qixi_cases(
    cases: Iterable[QixiEvaluationCase],
    execute: Callable[[QixiEvaluationCase], AgentResponse],
    *,
    dataset: str,
) -> QixiEvaluationReport:
    records: list[QixiEvaluationRecord] = []
    for case in cases:
        started = monotonic()
        try:
            response = execute(case)
            actual_tools = tuple(item.tool_name for item in response.tool_calls)
            knowledge_present = bool(response.knowledge_evidence)
            data_present = bool(response.report and response.report.data_evidence)
            expected_tools = set(case.expected_tools)
            evidence_passed = (
                (not case.expect_knowledge_evidence or knowledge_present)
                and (not case.expect_data_evidence or data_present)
            )
            records.append(
                QixiEvaluationRecord(
                    case_id=case.case_id,
                    expected_mode=case.expected_mode,
                    actual_mode=response.agent_mode,
                    expected_tools=case.expected_tools,
                    actual_tools=actual_tools,
                    mode_passed=response.agent_mode is case.expected_mode,
                    tools_passed=expected_tools.issubset(actual_tools),
                    knowledge_evidence_present=knowledge_present,
                    data_evidence_present=data_present,
                    evidence_passed=evidence_passed,
                    review_passed=bool(response.review and response.review.passed),
                    status=response.status.value,
                    latency_ms=int((monotonic() - started) * 1000),
                )
            )
        except Exception as exc:
            records.append(
                QixiEvaluationRecord(
                    case_id=case.case_id,
                    expected_mode=case.expected_mode,
                    expected_tools=case.expected_tools,
                    latency_ms=int((monotonic() - started) * 1000),
                    error_type=type(exc).__name__,
                )
            )
    total = len(records)
    executed = sum(item.error_type is None for item in records)
    latencies = sorted(item.latency_ms for item in records)
    return QixiEvaluationReport(
        dataset=dataset,
        cases=tuple(records),
        total=total,
        executed=executed,
        mode_accuracy=_rate(records, "mode_passed"),
        tool_accuracy=_rate(records, "tools_passed"),
        evidence_accuracy=_rate(records, "evidence_passed"),
        review_pass_rate=_rate(records, "review_passed"),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
    )


def _rate(records: list[QixiEvaluationRecord], field: str) -> float:
    if not records:
        return 0.0
    return round(sum(bool(getattr(item, field)) for item in records) / len(records), 4)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile)))
    return values[index]
