from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from argos.controllers import kanban as kanban_controller
from argos.db.models import SettingRecord
from argos.db.session import Base
from argos.services.settings import SettingsService


def _session_local(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'settings-test.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    return session_local


def test_settings_service_persists_kanban_auto_dispatch(monkeypatch, tmp_path):
    session_local = _session_local(tmp_path)
    monkeypatch.setattr("argos.db.repositories.SessionLocal", session_local)
    service = SettingsService()

    assert service.get_kanban_auto_dispatch_enabled() is False

    service.set_kanban_auto_dispatch_enabled(True)

    assert SettingsService().get_kanban_auto_dispatch_enabled() is True
    with session_local() as session:
        record = session.query(SettingRecord).filter_by(key="kanban_auto_dispatch_enabled").one()
        assert record.value == "1"


def test_kanban_settings_api_get_put(monkeypatch, tmp_path):
    session_local = _session_local(tmp_path)
    monkeypatch.setattr("argos.db.repositories.SessionLocal", session_local)
    monkeypatch.setattr(kanban_controller, "settings_service", SettingsService())
    app = Flask(__name__)
    app.register_blueprint(kanban_controller.bp)
    client = app.test_client()

    response = client.get("/api/kanban/settings")
    assert response.status_code == 200
    assert response.get_json()["settings"] == {
        "auto_dispatch_enabled": False,
        "auto_dispatch_interval_ms": 2000,
    }

    response = client.put("/api/kanban/settings", json={"auto_dispatch_enabled": True})
    assert response.status_code == 200
    assert response.get_json()["settings"]["auto_dispatch_enabled"] is True

    response = client.get("/api/kanban/settings")
    assert response.get_json()["settings"]["auto_dispatch_enabled"] is True


def test_kanban_settings_api_rejects_non_boolean(monkeypatch, tmp_path):
    session_local = _session_local(tmp_path)
    monkeypatch.setattr("argos.db.repositories.SessionLocal", session_local)
    monkeypatch.setattr(kanban_controller, "settings_service", SettingsService())
    app = Flask(__name__)
    app.register_blueprint(kanban_controller.bp)
    client = app.test_client()

    response = client.put("/api/kanban/settings", json={"auto_dispatch_enabled": "yes"})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
