from __future__ import annotations

import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging() -> None:
    level = _log_level()
    json_fmt = os.environ.get("LOG_FORMAT", "").lower() == "json"
    log_dir = os.environ.get("LOG_DIR")

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any pre-existing handlers so we don't double-log.
    root.handlers.clear()

    if log_dir:
        _setup_file_handler(root, Path(log_dir), level, json_fmt)
    else:
        _setup_console_handler(root, level, json_fmt)

    # Quiet noisy third-party loggers.
    for name in ("sqlalchemy.engine", "alembic", "httpcore", "httpx", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Ensure our app loggers are at the configured level.
    for name in ("argos", "argos.agent_state", "argos"):
        logging.getLogger(name).setLevel(level)


def request_id() -> str:
    return uuid.uuid4().hex[:12]


def _log_level() -> int:
    name = os.environ.get("LOG_LEVEL", "").upper()
    return getattr(logging, name, logging.DEBUG if _is_debug() else logging.INFO)


def _is_debug() -> bool:
    return os.environ.get("FLASK_DEBUG", "0") == "1"


def _setup_console_handler(logger: logging.Logger, level: int, json_fmt: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(_json_formatter() if json_fmt else _console_formatter())
    logger.addHandler(handler)


def _setup_file_handler(logger: logging.Logger, log_dir: Path, level: int, json_fmt: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "argos.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_json_formatter() if json_fmt else _console_formatter())
    logger.addHandler(handler)

    # Also keep errors in a separate file.
    err_handler = RotatingFileHandler(
        log_dir / "argos_error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(_json_formatter() if json_fmt else _console_formatter())
    logger.addHandler(err_handler)


def _console_formatter() -> logging.Formatter:
    return logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _json_formatter() -> logging.Formatter:
    class _JSONFormatter(logging.Formatter):
        def format(self, record):
            import json

            payload = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[1]:
                payload["exc"] = str(record.exc_info[1])
            req_id = _get_request_id()
            if req_id:
                payload["req"] = req_id
            return json.dumps(payload, ensure_ascii=False)

    return _JSONFormatter()


def _get_request_id() -> str | None:
    import contextvars

    return contextvars.ContextVar("request_id", default=None).get(None)
