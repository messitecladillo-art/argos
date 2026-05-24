from __future__ import annotations

import os

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from argos.middleware.auth import AuthMiddleware
from argos.middleware.ratelimit import RateLimitMiddleware


# ── Test ASGI app factories ────────────────────────────────────


def _public_endpoint(request: Request) -> Response:
    return JSONResponse({"ok": True})


def _protected_endpoint(request: Request) -> Response:
    return JSONResponse({"ok": True})


def _auth_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/", _public_endpoint, methods=["GET"]),
            Route("/api/argos/status", _public_endpoint, methods=["GET"]),
            Route("/api/agents", _protected_endpoint, methods=["GET", "POST"]),
            Route("/static/test.js", _public_endpoint, methods=["GET"]),
            Route("/mcp/test", _public_endpoint, methods=["GET"]),
        ],
        middleware=[Middleware(AuthMiddleware)],
    )


def _ratelimit_app(max_req: int = 3, window: int = 60) -> Starlette:
    return Starlette(
        routes=[Route("/api/test", _protected_endpoint, methods=["GET"])],
        middleware=[Middleware(RateLimitMiddleware, max_requests=max_req, window_s=window)],
    )


# ── Auth middleware tests ──────────────────────────────────────


class TestAuthMiddleware:
    def test_public_path_bypasses_auth(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/api/argos/status")
        assert resp.status_code == 200

    def test_dashboard_bypasses_auth(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/")
        assert resp.status_code == 200

    def test_static_path_bypasses_auth(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/static/test.js")
        assert resp.status_code == 200

    def test_mcp_path_bypasses_auth(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/mcp/test")
        assert resp.status_code == 200

    def test_protected_path_returns_401_without_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/api/agents")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_protected_path_accepts_x_api_key_header(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/api/agents", headers={"X-API-Key": "secret"})
        assert resp.status_code == 200

    def test_protected_path_accepts_bearer_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/api/agents", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_protected_path_rejects_wrong_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        client = TestClient(_auth_app())
        resp = client.get("/api/agents", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_auth_disabled_when_api_token_not_set(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        client = TestClient(_auth_app())
        resp = client.get("/api/agents")
        assert resp.status_code == 200

    def test_request_id_injected_in_response(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        client = TestClient(_auth_app())
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers

    def test_request_id_forwarded_from_client(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        client = TestClient(_auth_app())
        resp = client.get("/api/agents", headers={"X-Request-ID": "my-custom-id"})
        assert resp.headers["X-Request-ID"] == "my-custom-id"


# ── Rate limit middleware tests ────────────────────────────────


class TestRateLimitMiddleware:
    def test_allows_requests_within_limit(self):
        client = TestClient(_ratelimit_app(max_req=5))
        for _ in range(5):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_blocks_requests_beyond_limit(self):
        client = TestClient(_ratelimit_app(max_req=2))
        # First 2 pass
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 200
        # Third is rate-limited
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate limited"

    def test_disabled_when_max_is_zero(self):
        client = TestClient(_ratelimit_app(max_req=0))
        for _ in range(10):
            resp = client.get("/api/test")
            assert resp.status_code == 200


# ── CORS middleware tests ──────────────────────────────────────


class TestCORSMiddleware:
    def test_cors_headers_in_debug_mode(self, monkeypatch):
        monkeypatch.setenv("FLASK_DEBUG", "1")
        from argos.middleware.cors import cors_middleware

        app = Starlette(routes=[Route("/api/test", _public_endpoint, methods=["GET"])])
        app = cors_middleware(app)
        client = TestClient(app)
        resp = client.options("/api/test", headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        })
        # In debug mode, allows all origins
        assert resp.status_code == 200

    def test_explicit_cors_origins_honored_in_production(self, monkeypatch):
        monkeypatch.setenv("FLASK_DEBUG", "0")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
        from argos.middleware.cors import cors_middleware

        app = Starlette(routes=[Route("/api/test", _public_endpoint, methods=["GET"])])
        app = cors_middleware(app)
        client = TestClient(app)
        # Allowed origin
        resp = client.options("/api/test", headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
        # Disallowed origin
        resp2 = client.options("/api/test", headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        })
        # CORS middleware returns 400 or no Allow-Origin for disallowed origins
        assert resp2.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"

    def test_production_no_cors_origins_blocks_all(self, monkeypatch):
        monkeypatch.setenv("FLASK_DEBUG", "0")
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        from argos.middleware.cors import cors_middleware

        app = Starlette(routes=[Route("/api/test", _public_endpoint, methods=["GET"])])
        app = cors_middleware(app)
        client = TestClient(app)
        resp = client.options("/api/test", headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        })
        # In production without CORS_ORIGINS, no origins are allowed
        assert resp.headers.get("Access-Control-Allow-Origin") != "http://example.com"


class TestWebSocketAuth:
    def test_ws_auth_disabled_when_api_token_not_set(self, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}
        assert _ws_authenticate(ws) is True

    def test_ws_auth_accepts_valid_x_api_key(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {"X-API-Key": "secret"}
        ws.query_params = {}
        assert _ws_authenticate(ws) is True

    def test_ws_auth_accepts_valid_query_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {"token": "secret"}
        assert _ws_authenticate(ws) is True

    def test_ws_auth_accepts_bearer_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {"Authorization": "Bearer secret"}
        ws.query_params = {}
        assert _ws_authenticate(ws) is True

    def test_ws_auth_rejects_wrong_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {"X-API-Key": "wrong"}
        ws.query_params = {}
        assert _ws_authenticate(ws) is False

    def test_ws_auth_rejects_missing_token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        from argos.asgi import _ws_authenticate
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}
        assert _ws_authenticate(ws) is False
