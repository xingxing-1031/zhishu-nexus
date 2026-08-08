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


def test_vps_compose_keeps_database_private_and_uses_caddy() -> None:
    compose = (PROJECT_ROOT / "compose.vps.yaml").read_text(encoding="utf-8")
    caddyfile = (PROJECT_ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert 'expose:\n      - "5432"' in compose
    assert '"5432:5432"' not in compose
    assert '"${HTTP_PORT:-80}:80"' in compose
    assert '"${HTTPS_PORT:-443}:443"' in compose
    assert "reverse_proxy api:8000" in caddyfile


def test_vps_compose_requires_server_secrets_and_configurable_access_mode() -> None:
    compose = (PROJECT_ROOT / "compose.vps.yaml").read_text(encoding="utf-8")

    assert "MODEL_API_KEY:?set MODEL_API_KEY" in compose
    assert "PUBLIC_DEMO_MODE: ${PUBLIC_DEMO_MODE:-true}" in compose
    assert "AUTH_MODE: ${AUTH_MODE:-demo}" in compose
    assert "SITE_ADDRESS:?set SITE_ADDRESS" in compose
