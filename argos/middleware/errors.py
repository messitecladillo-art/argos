from __future__ import annotations

import logging
import signal
import sys
from typing import Any

logger = logging.getLogger("argos.shutdown")


def register_error_handlers(app) -> None:
    """Register Flask error handlers that return JSON instead of HTML."""

    @app.errorhandler(400)
    def bad_request(exc):
        return {"ok": False, "error": str(exc) or "bad request"}, 400

    @app.errorhandler(401)
    def unauthorized(exc):
        return {"ok": False, "error": "unauthorized"}, 401

    @app.errorhandler(403)
    def forbidden(exc):
        return {"ok": False, "error": "forbidden"}, 403

    @app.errorhandler(404)
    def not_found(exc):
        return {"ok": False, "error": "not found"}, 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return {"ok": False, "error": "method not allowed"}, 405

    @app.errorhandler(429)
    def rate_limited(exc):
        return {"ok": False, "error": "rate limited"}, 429

    @app.errorhandler(500)
    def internal_error(exc):
        logger.exception("Unhandled internal error")
        return {"ok": False, "error": "internal server error"}, 500


# ── Graceful shutdown ──────────────────────────────────────────

_shutdown_hooks: list[tuple[str, Any]] = []


def register_shutdown_hook(name: str, hook) -> None:
    """Register a callable to be invoked during graceful shutdown."""
    _shutdown_hooks.append((name, hook))


def _run_shutdown_hooks() -> None:
    for name, hook in _shutdown_hooks:
        try:
            logger.info("Shutting down: %s", name)
            hook()
        except Exception:
            logger.exception("Error shutting down %s", name)


def _handle_signal(signum, frame) -> None:
    logger.info("Received signal %s, shutting down gracefully", signum)
    _run_shutdown_hooks()
    sys.exit(0)


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
