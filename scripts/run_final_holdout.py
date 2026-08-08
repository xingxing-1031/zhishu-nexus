from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from retail_analytics_agent.business_evaluation import (
    load_business_evaluation_suite,
)
from retail_analytics_agent.evaluation_runtime import (
    open_deployed_evaluation_executor,
)
from retail_analytics_agent.final_acceptance import run_final_acceptance
from retail_analytics_agent.settings import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_SUITE = PROJECT_ROOT / "evaluation" / "business_holdout.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation" / "reports" / "final_holdout.json"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--execution-id", default="final-holdout-v1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(
            f"refusing to overwrite frozen report: {args.output}"
        )

    suite = load_business_evaluation_suite(HOLDOUT_SUITE)
    settings = get_settings()
    with open_deployed_evaluation_executor(
        execution_id=args.execution_id,
        settings=settings,
        reference_time=suite.reference_time,
    ) as executor:
        report = run_final_acceptance(
            execution_id=args.execution_id,
            model_id=settings.active_model_name,
            model_provider=settings.model_provider.value,
            suite=suite,
            executor=executor,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"final holdout report written to {args.output}")
    print(
        "core_pass_rate="
        f"{report.summary.core_pass_rate:.2%} "
        f"runs={report.summary.run_count}"
    )


if __name__ == "__main__":
    main()
