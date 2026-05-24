from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask

from app.controllers import agents as agents_controller
from app.models.store import RuntimeStore


def _client(monkeypatch):
    monkeypatch.setattr(agents_controller, "store", RuntimeStore())
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute = MagicMock()
    monkeypatch.setattr(agents_controller, "SessionLocal", lambda: mock_session)
    app = Flask(__name__)
    app.register_blueprint(agents_controller.bp)
    return app.test_client()


def test_hermes_status_ready(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        agents_controller,
        "check_hermes_ready",
        lambda: {"ok": True, "profiles": ["default"], "message": "Hermes 已就绪"},
    )

    response = client.get("/api/hermes/status")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["status"] == "ok"
    assert data["components"]["hermes_cli"]["ok"] is True
    assert data["components"]["hermes_cli"]["profiles"] == ["default"]
    assert data["components"]["database"]["ok"] is True


def test_hermes_status_not_found(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        agents_controller,
        "check_hermes_ready",
        lambda: {
            "ok": False,
            "reason": "not_found",
            "message": "未检测到 hermes CLI，请先安装并配置 Hermes Agent。",
        },
    )

    response = client.get("/api/hermes/status")

    assert response.status_code == 503
    data = response.get_json()
    assert data["ok"] is False
    assert data["status"] == "degraded"
    assert data["components"]["hermes_cli"]["ok"] is False
    assert data["components"]["hermes_cli"]["reason"] == "not_found"
