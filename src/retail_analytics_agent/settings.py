from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.structured_chat import StructuredChatProtocol


class Settings(BaseSettings):
    database_url: SecretStr | None = None
    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    database_pool_min_size: int = Field(default=1, ge=1, le=10)
    database_pool_max_size: int = Field(default=4, ge=1, le=20)
    database_pool_timeout_seconds: float = Field(default=10, gt=0, le=60)
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
    auth_mode: str = "demo"
    auth_user_id: str = "ANALYST-001"
    auth_username: str = "analyst"
    auth_role: AccessRole = AccessRole.ANALYST
    auth_password_hash: str | None = None
    auth_admin_user_id: str = "ADMIN-001"
    auth_admin_username: str = "admin"
    auth_admin_password_hash: str | None = None
    auth_session_secret: SecretStr | None = None
    auth_session_ttl_seconds: int = Field(default=28800, ge=300, le=604800)
    auth_cookie_secure: bool = False
    knowledge_service_url: str | None = None
    knowledge_service_token: SecretStr | None = None
    internal_service_token: SecretStr | None = None
    knowledge_departments: str = "admin"
    agent_context_token_budget: int = Field(default=4000, ge=256, le=32000)
    agent_max_steps: int = Field(default=8, ge=1, le=30)
    mcp_export_enabled: bool = True
    mcp_export_timeout_seconds: float = Field(default=15, gt=0, le=60)
    mcp_common_enabled: bool = True
    mcp_common_timeout_seconds: float = Field(default=15, gt=0, le=60)
    mcp_http_timeout_seconds: float = Field(default=10, gt=0, le=60)
    mcp_max_response_bytes: int = Field(default=1_000_000, ge=10_000, le=10_000_000)
    dataset_upload_root: Path = Field(
        default_factory=lambda: Path.cwd() / "data" / "uploads"
    )
    dataset_max_upload_bytes: int = Field(
        default=50_000_000,
        ge=1_024,
        le=2_000_000_000,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_remote_model_configuration(self) -> "Settings":
        if not self.dataset_upload_root.is_absolute():
            raise ValueError("DATASET_UPLOAD_ROOT must be an absolute path")
        has_database_url = bool(
            self.database_url
            and self.database_url.get_secret_value().strip()
        )
        has_split_database_config = all(
            (
                self.postgres_db,
                self.postgres_user,
                self.postgres_password
                and self.postgres_password.get_secret_value().strip(),
            )
        )
        if not has_database_url and not has_split_database_config:
            raise ValueError(
                "configure DATABASE_URL or complete POSTGRES_DB, "
                "POSTGRES_USER and POSTGRES_PASSWORD"
            )
        if self.database_pool_min_size > self.database_pool_max_size:
            raise ValueError("DATABASE_POOL_MIN_SIZE cannot exceed DATABASE_POOL_MAX_SIZE")
        if (
            self.public_demo_mode
            and self.local_access_role is not AccessRole.ANALYST
        ):
            raise ValueError(
                "PUBLIC_DEMO_MODE requires LOCAL_ACCESS_ROLE=analyst"
            )
        if self.auth_mode not in {"demo", "password"}:
            raise ValueError("AUTH_MODE must be demo or password")
        if self.auth_mode == "password":
            if not self.auth_password_hash or not self.auth_session_secret:
                raise ValueError(
                    "AUTH_PASSWORD_HASH and AUTH_SESSION_SECRET are required"
                )
            if self.public_demo_mode and not self.auth_admin_password_hash:
                raise ValueError(
                    "PUBLIC_DEMO_MODE with password auth requires AUTH_ADMIN_PASSWORD_HASH"
                )
            if len(self.auth_session_secret.get_secret_value()) < 32:
                raise ValueError("AUTH_SESSION_SECRET must contain at least 32 characters")
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

    @model_validator(mode="after")
    def validate_agent_service_configuration(self) -> "Settings":
        if self.knowledge_service_url and not self.knowledge_service_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("KNOWLEDGE_SERVICE_URL must be an HTTP(S) URL")
        if self.knowledge_service_url and (
            self.knowledge_service_token is None
            or not self.knowledge_service_token.get_secret_value().strip()
        ):
            raise ValueError(
                "KNOWLEDGE_SERVICE_TOKEN is required when knowledge service is enabled"
            )
        return self

    @property
    def active_knowledge_departments(self) -> tuple[str, ...]:
        return tuple(
            item.strip()
            for item in self.knowledge_departments.split(",")
            if item.strip()
        )

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
        if self.database_url and self.database_url.get_secret_value().strip():
            return {"conninfo": self.database_url.get_secret_value()}
        if (
            self.postgres_db is None
            or self.postgres_user is None
            or self.postgres_password is None
        ):
            raise ValueError("database connection configuration is incomplete")
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
