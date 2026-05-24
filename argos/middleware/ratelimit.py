from __future__ import annotations

import os
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_DEFAULT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX", "300"))
_DEFAULT_WINDOW_S = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP sliding-window rate limiter.

    Configure via environment:
      RATE_LIMIT_MAX    — max requests per window (default 300)
      RATE_LIMIT_WINDOW — window size in seconds (default 60)
    Set RATE_LIMIT_MAX=0 to disable.
    """

    def __init__(self, app, max_requests: int | None = None, window_s: int | None = None) -> None:
        super().__init__(app)
        self.max_requests = max_requests if max_requests is not None else _DEFAULT_MAX_REQUESTS
        self.window_s = window_s if window_s is not None else _DEFAULT_WINDOW_S
        self._clients: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.max_requests <= 0:
            return await call_next(request)

        client_ip = _client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_s

        # Evict expired entries
        window = self._clients[client_ip]
        while window and window[0] < cutoff:
            window.pop(0)

        if len(window) >= self.max_requests:
            retry_after = int(self.window_s - (now - window[0]) + 1) if window else self.window_s
            return JSONResponse(
                {"ok": False, "error": "rate limited", "retry_after": retry_after},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        return await call_next(request)

    def cleanup(self) -> None:
        """Remove stale entries to free memory. Call periodically."""
        now = time.monotonic()
        cutoff = now - self.window_s
        stale: list[str] = []
        for ip, window in self._clients.items():
            while window and window[0] < cutoff:
                window.pop(0)
            if not window:
                stale.append(ip)
        for ip in stale:
            del self._clients[ip]


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    if client:
        return client.host if hasattr(client, "host") else str(client)
    return "unknown"
