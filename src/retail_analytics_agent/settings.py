from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.structured_chat import StructuredChatProtocol


class Settings(BaseSettings):
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)
    model_provider: StructuredChatProtocol = StructuredChatProtocol.OLLAMA
    model_base_url: str | None = None
    model_name: str | None = None
    model_api_key: SecretStr | None = None
    model_timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    model_retry_max_attempts: int = Field(default=3, ge=1, le=5)
    model_retry_initial_backoff_seconds: float = Field(
        default=0.25,
        ge=0,
        le=10,
    )
    workflow_timeout_seconds: float = Field(default=120, gt=0, le=900)
    local_access_user_id: str = "USER-001"
    local_access_role: AccessRole = AccessRole.ANALYST
    public_demo_mode: bool = False
    public_demo_rate_limit_per_minute: int = Field(default=6, ge=1, le=60)
    public_demo_max_rows: int = Field(default=20, ge=1, le=100)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_remote_model_configuration(self) -> "Settings":
        if (
            self.public_demo_mode
            and self.local_access_role is not AccessRole.ANALYST
        ):
            raise ValueError(
                "PUBLIC_DEMO_MODE requires LOCAL_ACCESS_ROLE=analyst"
            )
        if self.model_provider is StructuredChatProtocol.OLLAMA:
            return self
        if not self.model_base_url or not self.model_base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "MODEL_BASE_URL must be an HTTP(S) URL for remote models"
            )
        if not self.model_name:
            raise ValueError("MODEL_NAME is required for remote models")
        if (
            self.model_api_key is None
            or not self.model_api_key.get_secret_value().strip()
        ):
            raise ValueError("MODEL_API_KEY is required for remote models")
        return self

    @property
    def active_model_base_url(self) -> str:
        if self.model_provider is StructuredChatProtocol.OLLAMA:
            return self.ollama_base_url
        assert self.model_base_url is not None
        return self.model_base_url

    @property
    def active_model_name(self) -> str:
        if self.model_provider is StructuredChatProtocol.OLLAMA:
            return self.ollama_model
        assert self.model_name is not None
        return self.model_name

    @property
    def active_model_timeout_seconds(self) -> float:
        return self.model_timeout_seconds or self.ollama_timeout_seconds

    @property
    def model_client_headers(self) -> dict[str, str]:
        if self.model_provider is StructuredChatProtocol.OLLAMA:
            return {}
        assert self.model_api_key is not None
        return {
            "Authorization": (
                f"Bearer {self.model_api_key.get_secret_value()}"
            )
        }

    @property
    def postgres_connection_kwargs(self) -> dict[str, str | int]:
        return {
            "dbname": self.postgres_db,
            "user": self.postgres_user,
            "password": self.postgres_password.get_secret_value(),
            "host": self.postgres_host,
            "port": self.postgres_port,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
