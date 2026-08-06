from pathlib import Path
from unittest.mock import Mock

import pytest

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationCase,
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_observation import (
    AnalysisEvaluationObservation,
)
from retail_analytics_agent.evaluation_runs import EvaluationVariant
from retail_analytics_agent.evaluation_variants import (
    create_variant_executors,
    create_variant_retrieval_adapters,
)
from retail_analytics_agent.models import (
    AnalysisResultStatus,
    ApprovalStatus,
)
from retail_analytics_agent.retrieval_adapters import (
    CatalogEvidenceAdapter,
    MetricCandidateEvidenceAdapter,
)


EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def _case() -> BusinessEvaluationCase:
    suite = load_business_evaluation_suite(
        EVALUATION_ROOT / "business_development.json"
    )
    return next(case for case in suite.cases if case.expected_plan is not None)


def _observation(case: BusinessEvaluationCase) -> AnalysisEvaluationObservation:
    return AnalysisEvaluationObservation(
        request_id="variant-run",
        plan=case.expected_plan,
        evidence_source_ids=case.expected_source_ids,
        generated_sql=case.gold_sql,
        sql_safe=True,
        business_sql_valid=True,
        rows=case.expected_rows,
        chart_type=case.expected_chart_type,
        final_answer="table result",
        result_status=AnalysisResultStatus.SUCCEEDED,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        retry_count=0,
        trace=("plan", "retrieve", "execute_sql", "summarize"),
        database_called=True,
    )


class _Workflow:
    def __init__(self, observation: AnalysisEvaluationObservation) -> None:
        self.observation = observation

    def run_case(self, case, *, request_id):
        return self.observation


def test_variant_adapters_change_only_the_metric_retriever() -> None:
    retrieval_retriever = Mock()
    reranker_retriever = Mock()

    adapters = create_variant_retrieval_adapters(
        retrieval_retriever=retrieval_retriever,
        reranker_retriever=reranker_retriever,
        candidate_k=3,
    )

    assert isinstance(adapters[EvaluationVariant.BASELINE], CatalogEvidenceAdapter)
    retrieval = adapters[EvaluationVariant.RETRIEVAL]
    reranker = adapters[EvaluationVariant.RERANKER]
    assert isinstance(retrieval, MetricCandidateEvidenceAdapter)
    assert isinstance(reranker, MetricCandidateEvidenceAdapter)
    assert retrieval.metric_retriever is retrieval_retriever
    assert reranker.metric_retriever is reranker_retriever
    assert retrieval.candidate_k == reranker.candidate_k == 3


def test_variant_factory_builds_one_executor_per_variant() -> None:
    case = _case()
    adapters = []

    def workflow_factory(adapter):
        adapters.append(adapter)
        return _Workflow(_observation(case))

    executors = create_variant_executors(
        execution_id="EXP-FACTORY-001",
        workflow_factory=workflow_factory,
        retrieval_retriever=Mock(),
        reranker_retriever=Mock(),
        candidate_k=5,
    )

    assert set(executors) == set(EvaluationVariant)
    assert len(adapters) == 3
    for variant, executor in executors.items():
        run = executor.execute(case, variant=variant, run_index=1)
        assert run.variant is variant
        assert run.case_id == case.case_id


def test_variant_factory_rejects_invalid_shared_configuration() -> None:
    with pytest.raises(ValueError, match="execution_id"):
        create_variant_executors(
            execution_id=" ",
            workflow_factory=Mock(),
            retrieval_retriever=Mock(),
            reranker_retriever=Mock(),
        )

    with pytest.raises(ValueError, match="candidate_k"):
        create_variant_retrieval_adapters(
            retrieval_retriever=Mock(),
            reranker_retriever=Mock(),
            candidate_k=0,
        )
