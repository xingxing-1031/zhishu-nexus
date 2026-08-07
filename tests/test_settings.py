from pydantic import SecretStr
import pytest

from retail_analytics_agent.settings import Settings
from retail_analytics_agent.structured_chat import StructuredChatProtocol


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
    assert settings.model_provider is StructuredChatProtocol.OLLAMA
    assert settings.active_model_base_url == "http://127.0.0.1:11434"
    assert settings.active_model_name == "qwen3:4b"
    assert settings.active_model_timeout_seconds == 120
    assert settings.model_client_headers == {}
    assert settings.public_demo_mode is False
    assert settings.public_demo_rate_limit_per_minute == 6
    assert settings.public_demo_max_rows == 20


def test_settings_prefers_managed_database_url_without_exposing_secret() -> None:
    settings = Settings(
        database_url=SecretStr(
            "postgresql://cloud_user:cloud_password@db.example:5432/retail"
        ),
        _env_file=None,
    )

    assert settings.postgres_connection_kwargs == {
        "conninfo": (
            "postgresql://cloud_user:cloud_password@db.example:5432/retail"
        )
    }
    assert "cloud_password" not in repr(settings)


def test_settings_rejects_incomplete_database_configuration() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL or complete"):
        Settings(postgres_db="only_db", _env_file=None)


def test_settings_builds_remote_model_configuration() -> None:
    settings = Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        model_provider="openai_compatible",
        model_base_url="https://dashscope.example/v1",
        model_name="qwen-plus",
        model_api_key=SecretStr("remote-secret"),
        model_timeout_seconds=45,
        _env_file=None,
    )

    assert settings.model_provider is StructuredChatProtocol.OPENAI_COMPATIBLE
    assert settings.active_model_base_url == "https://dashscope.example/v1"
    assert settings.active_model_name == "qwen-plus"
    assert settings.active_model_timeout_seconds == 45
    assert settings.model_client_headers == {
        "Authorization": "Bearer remote-secret"
    }
    assert "remote-secret" not in repr(settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "model_base_url": None,
            "model_name": "qwen-plus",
            "model_api_key": SecretStr("secret"),
        },
        {
            "model_base_url": "https://dashscope.example/v1",
            "model_name": None,
            "model_api_key": SecretStr("secret"),
        },
        {
            "model_base_url": "https://dashscope.example/v1",
            "model_name": "qwen-plus",
            "model_api_key": None,
        },
    ],
)
def test_settings_rejects_incomplete_remote_model_configuration(overrides) -> None:
    with pytest.raises(ValueError):
        Settings(
            postgres_db="test_db",
            postgres_user="test_user",
            postgres_password=SecretStr("test_password"),
            model_provider="openai_compatible",
            _env_file=None,
            **overrides,
        )


def test_settings_rejects_admin_role_in_public_demo() -> None:
    with pytest.raises(
        ValueError,
        match="PUBLIC_DEMO_MODE requires LOCAL_ACCESS_ROLE=analyst",
    ):
        Settings(
            postgres_db="test_db",
            postgres_user="test_user",
            postgres_password=SecretStr("test_password"),
            local_access_role="admin",
            public_demo_mode=True,
            _env_file=None,
        )
