from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

SECRET_KEY_RE = re.compile(r"(token|secret|key|password|authorization)", re.IGNORECASE)
MASK_REPLACEMENT = "***REDACTED***"


def mask(value: str) -> str:
    """Redact a secret value for display/logging."""
    if not value:
        return value
    if len(value) <= 8:
        return MASK_REPLACEMENT
    return value[:4] + "..." + value[-4:]


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key))


def mask_dict(data: dict[str, Any], *, reveal: bool = False) -> dict[str, Any]:
    if reveal:
        return dict(data)
    result: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and is_secret_key(k):
            result[k] = mask(v)
        elif isinstance(v, dict):
            result[k] = mask_dict(v, reveal=reveal)
        else:
            result[k] = v
    return result


def load_env_file(path: str | None = None) -> None:
    """Load .env into os.environ (idempotent, does not walk parent dirs)."""
    try:
        from dotenv import load_dotenv, find_dotenv

        env_path = path or find_dotenv(usecwd=True, raise_error_if_not_found=False)
        if env_path:
            load_dotenv(env_path, override=False)
    except ImportError:
        pass


def load_docker_secrets(secrets_dir: str = "/run/secrets") -> dict[str, str]:
    """Load Docker/K8s secrets from a directory into a dict."""
    secrets: dict[str, str] = {}
    secrets_path = Path(secrets_dir)
    if not secrets_path.is_dir():
        return secrets
    for entry in secrets_path.iterdir():
        if entry.is_file():
            secrets[entry.name] = entry.read_text().strip()
    return secrets


def validate_required(required_keys: list[str]) -> list[str]:
    """Return list of missing required environment keys."""
    missing: list[str] = []
    for key in required_keys:
        if not os.environ.get(key):
            missing.append(key)
    return missing


def get_secret(key: str, default: str | None = None) -> str | None:
    """Read a secret from environment (with Docker secrets fallback).

    Checks os.environ first, then /run/secrets/<key>.
    """
    value = os.environ.get(key)
    if value:
        return value
    secret_file = Path(f"/run/secrets/{key}")
    if secret_file.is_file():
        return secret_file.read_text().strip()
    return default


def redact_for_log(text: str, secrets: list[str] | None = None) -> str:
    """Remove known secret values from a log string."""
    result = text
    candidates = secrets or []
    candidates.extend(
        [os.environ.get(k) or "" for k in os.environ if is_secret_key(k)]
    )
    for secret in candidates:
        if secret and len(secret) > 4:
            result = result.replace(secret, MASK_REPLACEMENT)
    return result
