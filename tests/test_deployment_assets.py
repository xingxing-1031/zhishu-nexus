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


def test_managed_database_url_is_wired_only_to_api_service() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "DATABASE_URL: ${DATABASE_URL:-}" in compose
    postgres_block, api_block = compose.split("  api:", maxsplit=1)
    assert "DATABASE_URL:" not in postgres_block
    assert "DATABASE_URL: ${DATABASE_URL:-}" in api_block


def test_image_contains_database_migrations_for_release_command() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY db ./db" in dockerfile
