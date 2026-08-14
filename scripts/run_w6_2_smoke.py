from argparse import ArgumentParser
from pathlib import Path

from retail_analytics_agent.business_evaluation import (
    BusinessEvaluationSuite,
    EvaluationCategory,
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
    parser.add_argument(
        "--case-id",
        default=None,
        help="run one development case; omit to run the full development suite",
    )
    parser.add_argument(
        "--category",
        choices=[item.value for item in EvaluationCategory],
        default=None,
        help="run one development category; cannot be combined with --case-id",
    )
    parser.add_argument("--execution-id", default="w6-2-smoke")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")
    if args.case_id is not None and args.category is not None:
        raise ValueError("--case-id and --category cannot be combined")

    full_suite = load_business_evaluation_suite(DEVELOPMENT_SUITE)
    if args.case_id is None and args.category is None:
        selected = full_suite.cases
    elif args.category is not None:
        selected = tuple(
            case
            for case in full_suite.cases
            if case.category.value == args.category
        )
        if not selected:
            raise ValueError(f"development category not found: {args.category}")
    else:
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
        model_retry_max_attempts=settings.model_retry_max_attempts,
        model_retry_initial_backoff_seconds=(
            settings.model_retry_initial_backoff_seconds
        ),
    )
    experiment = ControlledExperiment(
        experiment_id=args.execution_id,
        conditions=conditions,
        variants=tuple(EvaluationVariant),
        repetitions=args.repetitions,
    )
    with open_real_evaluation_executors(
        execution_id=args.execution_id,
        settings=settings,
        reference_time=suite.reference_time,
    ) as executors:
        report = run_development_experiment(experiment, suite, executors)
    rendered = report.model_dump_json(indent=2)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"evaluation report written to {args.output}")


if __name__ == "__main__":
    main()
