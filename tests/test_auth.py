from fastapi.testclient import TestClient
from pydantic import SecretStr

from retail_analytics_agent.app import app, login_rate_limiter
from retail_analytics_agent.auth import (
    hash_password,
    issue_session,
    read_session,
    verify_password,
)
from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.settings import Settings, get_settings


def _password_settings() -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        auth_mode="password",
        auth_user_id="ANALYST-LOGIN",
        auth_username="operator",
        auth_role="analyst",
        auth_password_hash=hash_password("correct-password"),
        auth_session_secret=SecretStr("session-secret-with-at-least-32-characters"),
        _env_file=None,
    )


def test_password_hash_verification_rejects_wrong_password() -> None:
    encoded = hash_password("correct-password")

    assert verify_password("correct-password", encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password("correct-password", "invalid")


def test_signed_session_rejects_tampering() -> None:
    token = issue_session(
        user_id="USER-001",
        role=AccessRole.ANALYST,
        secret="session-secret",
        ttl_seconds=60,
    )

    assert read_session(token, "session-secret") is not None
    assert read_session(token + "tampered", "session-secret") is None


def test_password_mode_requires_login_and_logout_revokes_browser_cookie() -> None:
    settings = _password_settings()
    app.dependency_overrides[get_settings] = lambda: settings

    try:
        with TestClient(app) as client:
            assert client.get("/session").status_code == 401
            rejected = client.post(
                "/auth/login",
                json={"username": "operator", "password": "wrong"},
            )
            assert rejected.status_code == 401

            accepted = client.post(
                "/auth/login",
                json={
                    "username": "operator",
                    "password": "correct-password",
                },
            )
            assert accepted.status_code == 200
            assert accepted.json()["user_id"] == "ANALYST-LOGIN"
            assert "HttpOnly" in accepted.headers["set-cookie"]

            session = client.get("/session")
            assert session.status_code == 200
            assert session.json()["role"] == "analyst"

            assert client.post("/auth/logout").status_code == 204
            assert client.get("/session").status_code == 401
    finally:
        login_rate_limiter.clear()
        app.dependency_overrides.clear()


def test_demo_mode_does_not_offer_password_login() -> None:
    settings = Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password=SecretStr("test_password"),
        _env_file=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    try:
        response = TestClient(app).post(
            "/auth/login",
            json={"username": "analyst", "password": "anything"},
        )
    finally:
        login_rate_limiter.clear()
        app.dependency_overrides.clear()

    assert response.status_code == 404
