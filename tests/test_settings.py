from pydantic import SecretStr

from retail_analytics_agent.settings import Settings


def test_settings_builds_postgres_connection_kwargs() -> None:
    settings = Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        postgres_host="database.example",
        postgres_port=55432,
        _env_file=None,
    )

    assert settings.postgres_connection_kwargs == {
        "dbname": "test_db",
        "user": "test_user",
        "password": "test_password",
        "host": "database.example",
        "port": 55432,
    }
    assert settings.model_retry_max_attempts == 3
    assert settings.model_retry_initial_backoff_seconds == 0.25
    assert settings.workflow_timeout_seconds == 120
