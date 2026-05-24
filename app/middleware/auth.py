from __future__ import annotations

import os
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..logging_config import request_id as new_request_id

# Paths that do not require authentication.
_PUBLIC_PATHS = {
    "/",
    "/hermes_status/",
    "/api/hermes/status",
}
_PUBLIC_PREFIXES = ("/mcp/", "/static/")


def _is_public(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in _PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication and request ID middleware.

    - Injects ``X-Request-ID`` header if not provided by the client.
    - Authenticates requests when ``API_TOKEN`` is configured.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Request ID
        req_id = request.headers.get("X-Request-ID") or new_request_id()
        request.state.request_id = req_id

        path = urlparse(str(request.url)).path

        if _is_public(path):
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response

        # Authentication
        token = os.environ.get("API_TOKEN")
        if not token:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response

        provided = (
            request.headers.get("X-API-Key") or
            _bearer_token(request.headers.get("Authorization", ""))
        )
        if not provided or provided != token:
            return JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=401,
                headers={"X-Request-ID": req_id},
            )

        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


def _bearer_token(header: str) -> str | None:
    if header.startswith("Bearer "):
        return header[7:]
    return None
