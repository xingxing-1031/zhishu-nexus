from argparse import ArgumentParser
from pathlib import Path

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationSuite,
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_runs import (
    ControlledExperiment,
    EvaluationVariant,
    ExperimentConditions,
    run_development_experiment,
)
from retail_analytics_agent.evaluation_runtime import (
    open_real_evaluation_executors,
)
from retail_analytics_agent.settings import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_SUITE = PROJECT_ROOT / "evaluation" / "business_development.json"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--case-id", default="dev-basic-sales-total")
    parser.add_argument("--execution-id", default="w6-2-smoke")
    args = parser.parse_args()

    full_suite = load_business_evaluation_suite(DEVELOPMENT_SUITE)
    selected = tuple(
        case for case in full_suite.cases if case.case_id == args.case_id
    )
    if len(selected) != 1:
        raise ValueError(f"development case not found: {args.case_id}")
    suite = BusinessEvaluationSuite.model_validate(
        {**full_suite.model_dump(), "cases": selected}
    )
    settings = get_settings()
    conditions = ExperimentConditions(
        model_id=settings.ollama_model,
        dataset_version=suite.dataset_version,
        seed_snapshot_id=suite.seed_snapshot_id,
        reference_time=suite.reference_time,
        timezone=suite.timezone,
        safety_policy_version="sqlglot-and-business-v1",
        access_policy_version="retail-access-v1",
        timeout_ms=int(settings.workflow_timeout_seconds * 1000),
    )
    experiment = ControlledExperiment(
        experiment_id=args.execution_id,
        conditions=conditions,
        variants=tuple(EvaluationVariant),
        repetitions=1,
    )
    with open_real_evaluation_executors(
        execution_id=args.execution_id,
        settings=settings,
    ) as executors:
        report = run_development_experiment(experiment, suite, executors)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
