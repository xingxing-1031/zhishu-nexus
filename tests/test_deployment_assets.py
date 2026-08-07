from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_platform_port_and_non_root_user() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER appuser" in dockerfile
    assert "${PORT:-8000}" in dockerfile


def test_public_demo_environment_is_documented_and_wired_to_compose() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    for name in (
        "PUBLIC_DEMO_MODE",
        "PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE",
        "PUBLIC_DEMO_MAX_ROWS",
    ):
        assert name in env_example
        assert name in compose
