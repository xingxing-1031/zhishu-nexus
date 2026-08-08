"""Minimal structured observability for a single-VPS deployment."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "event",
            "request_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_host",
            "error_type",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_retail_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler._retail_json = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
