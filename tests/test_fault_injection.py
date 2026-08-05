import httpx
import pytest

from retail_analytics_agent.fault_injection import (
    FaultRule,
    ScriptedFaultInjector,
    fault_injection_context,
    inject_fault,
)


def test_scripted_fault_injector_fails_only_configured_occurrence() -> None:
    injector = ScriptedFaultInjector(
        (
            FaultRule(
                component="model.plan",
                occurrence=2,
                error=httpx.ConnectTimeout("planned timeout"),
            ),
        )
    )

    with fault_injection_context(injector):
        inject_fault("model.plan")
        with pytest.raises(httpx.ConnectTimeout, match="planned timeout"):
            inject_fault("model.plan")
        inject_fault("model.plan")

    assert injector.calls_for("model.plan") == 3


def test_scripted_fault_injector_rejects_duplicate_rules() -> None:
    with pytest.raises(ValueError, match="unique occurrences"):
        ScriptedFaultInjector(
            (
                FaultRule("model.plan", 1, RuntimeError("first")),
                FaultRule("model.plan", 1, RuntimeError("duplicate")),
            )
        )
