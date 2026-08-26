"""Shared test configuration.

Force demo auth for the whole test session so locally configured
``AUTH_MODE=password`` (public VPS demo setup) never leaks into tests:
legacy endpoint tests do not override identity dependencies and would
otherwise fail with 401 depending on ambient .env contents.
Environment variables take precedence over .env values in pydantic-settings.
"""

from __future__ import annotations

import os

os.environ["AUTH_MODE"] = "demo"
