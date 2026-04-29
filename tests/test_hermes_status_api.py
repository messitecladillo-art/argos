from __future__ import annotations

from flask import Flask

from app.controllers import agents as agents_controller
from app.models.store import RuntimeStore


def _client(monkeypatch):
    monkeypatch.setattr(agents_controller, "store", RuntimeStore())
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
    assert data["profiles"] == ["default"]


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

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is False
    assert data["reason"] == "not_found"
