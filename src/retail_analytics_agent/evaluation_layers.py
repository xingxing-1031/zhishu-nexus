"""八层失败归因指标聚合。

八层指标按 ``TraceErrorCategory``（model/context/tool/skill/state/
permission/memory/runtime）聚合执行 Trace 事件，回答「失败发生在哪一层」；
这与 ``EvaluationStage``（plan/evidence/sql/...，见 evaluation_runs.py）
按分析流程阶段打分正交：流程维度衡量「做到哪一步」，八层维度衡量「卡在哪一层」。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from retail_analytics_agent.tracing import TraceErrorCategory, TraceStatus

if TYPE_CHECKING:
    from retail_analytics_agent.tracing import ExecutionTraceEvent


_FAILED_STATUSES: frozenset[TraceStatus] = frozenset(
    {TraceStatus.FAILED, TraceStatus.REJECTED}
)

_LAYER_ORDER: tuple[TraceErrorCategory, ...] = tuple(TraceErrorCategory)


class LayerMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: TraceErrorCategory
    event_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)


class LayerMetricsReport(BaseModel):
    """八层汇总报告：保存版本号 + 每层指标，满足评测留存要求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    version: int = 1
    event_count: int = Field(ge=0)
    layers: tuple[LayerMetrics, ...]


def _tally(
    events: tuple[ExecutionTraceEvent, ...],
) -> tuple[Counter[TraceErrorCategory], Counter[TraceErrorCategory]]:
    counts: Counter[TraceErrorCategory] = Counter()
    failures: Counter[TraceErrorCategory] = Counter()
    for event in events:
        if event.error_category is None:
            continue
        counts[event.error_category] += 1
        if event.status in _FAILED_STATUSES:
            failures[event.error_category] += 1
    return counts, failures


def aggregate_layer_metrics(
    events: tuple[ExecutionTraceEvent, ...],
) -> tuple[LayerMetrics, ...]:
    """按八层聚合事件；仅返回有事件的层，按枚举顺序排序。"""
    counts, failures = _tally(events)
    layers = []
    for layer in _LAYER_ORDER:
        total = counts.get(layer, 0)
        if total == 0:
            continue
        failed = failures.get(layer, 0)
        layers.append(
            LayerMetrics(
                layer=layer,
                event_count=total,
                failure_count=failed,
                success_rate=(total - failed) / total,
            )
        )
    return tuple(layers)


def build_layer_metrics_report(
    request_id: str,
    events: tuple[ExecutionTraceEvent, ...],
) -> LayerMetricsReport:
    """构建覆盖全部 8 层的汇总报告；无事件层 success_rate=0.0。"""
    counts, failures = _tally(events)
    layers = []
    for layer in _LAYER_ORDER:
        total = counts.get(layer, 0)
        failed = failures.get(layer, 0)
        layers.append(
            LayerMetrics(
                layer=layer,
                event_count=total,
                failure_count=failed,
                success_rate=((total - failed) / total) if total else 0.0,
            )
        )
    return LayerMetricsReport(
        request_id=request_id,
        version=1,
        event_count=len(events),
        layers=tuple(layers),
    )
