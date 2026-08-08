"""Small, dependency-free password authentication for the hosted demo."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from getpass import getpass

from fastapi import HTTPException, Request

from retail_analytics_agent.models import AccessContext, AccessRole


SESSION_COOKIE = "retail_session"
_PBKDF2_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        _b64(salt),
        _b64(digest),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            _unb64(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest, _unb64(expected))
    except (ValueError, TypeError):
        return False


def issue_session(
    *, user_id: str, role: AccessRole, secret: str, ttl_seconds: int
) -> str:
    payload = {"user_id": user_id, "role": role.value, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_signature(body, secret)}"


def read_session(token: str | None, secret: str) -> AccessContext | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _signature(body, secret)):
        return None
    try:
        payload = json.loads(_unb64(body))
        if int(payload["exp"]) < int(time.time()):
            return None
        return AccessContext(user_id=payload["user_id"], role=AccessRole(payload["role"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def require_session(request: Request, secret: str) -> AccessContext:
    context = read_session(request.cookies.get(SESSION_COOKIE), secret)
    if context is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return context


def _signature(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def main() -> int:
    password = getpass("新密码：")
    confirmation = getpass("再次输入：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
