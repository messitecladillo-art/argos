from __future__ import annotations

import os

from starlette.middleware.cors import CORSMiddleware


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


def cors_middleware(app, **overrides) -> CORSMiddleware:
    origins = _cors_origins()
    if origins:
        allow_origins = origins
    elif os.environ.get("FLASK_DEBUG") == "1":
        allow_origins = ["*"]
    else:
        allow_origins = []

    return CORSMiddleware(
        app,
        allow_origins=overrides.pop("allow_origins", allow_origins),
        allow_methods=overrides.pop("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
        allow_headers=overrides.pop("allow_headers", ["X-API-Key", "Authorization", "Content-Type"]),
        allow_credentials=overrides.pop("allow_credentials", True),
        **overrides,
    )
