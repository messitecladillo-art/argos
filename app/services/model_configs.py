from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import now_iso
from ..db.models import ModelConfigRecord
from ..db.session import SessionLocal
from ..models.store import store
from . import profiles


class ModelConfigError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _serialize(record: ModelConfigRecord) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "model": record.model,
        "base_url": record.base_url,
        "api_key": record.api_key,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _validate_payload(payload: dict[str, Any]) -> dict:
    name = str(payload.get("name") or "").strip()
    model = str(payload.get("model") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not name:
        raise ModelConfigError("name is required")
    if not model:
        raise ModelConfigError("model is required")
    if not base_url:
        raise ModelConfigError("base_url is required")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ModelConfigError("base_url must start with http:// or https://")
    if not api_key:
        raise ModelConfigError("api_key is required")
    return {"name": name, "model": model, "base_url": base_url, "api_key": api_key}


def list_model_configs() -> list[dict]:
    with SessionLocal() as session:
        records = session.scalars(select(ModelConfigRecord).order_by(ModelConfigRecord.name)).all()
        return [_serialize(record) for record in records]


def get_model_config(config_id: int) -> dict | None:
    with SessionLocal() as session:
        record = session.get(ModelConfigRecord, config_id)
        return _serialize(record) if record is not None else None


def create_model_config(payload: dict[str, Any]) -> dict:
    values = _validate_payload(payload)
    timestamp = now_iso()
    with SessionLocal.begin() as session:
        record = ModelConfigRecord(**values, created_at=timestamp, updated_at=timestamp)
        session.add(record)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ModelConfigError("name already exists") from exc
        return _serialize(record)


def update_model_config(config_id: int, payload: dict[str, Any]) -> dict:
    values = _validate_payload(payload)
    with SessionLocal.begin() as session:
        record = session.get(ModelConfigRecord, config_id)
        if record is None:
            raise ModelConfigError("model config not found", status_code=404)
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_at = now_iso()
        try:
            session.flush()
        except IntegrityError as exc:
            raise ModelConfigError("name already exists") from exc
        return _serialize(record)


def delete_model_config(config_id: int) -> None:
    with SessionLocal.begin() as session:
        record = session.get(ModelConfigRecord, config_id)
        if record is None:
            raise ModelConfigError("model config not found", status_code=404)
        session.delete(record)


def apply_to_agent(agent_id: str, config_id: int) -> dict:
    agent = store.find_agent(agent_id)
    if agent is None:
        raise ModelConfigError("agent not found", status_code=404)
    config = get_model_config(config_id)
    if config is None:
        raise ModelConfigError("model config not found", status_code=404)
    summary = profiles.apply_model_config(agent["profile_name"], config)
    store.push_event(
        "agent.model.updated",
        agent_id,
        None,
        {"text": f"模型配置已保存：{config['name']} / {config['model']}，重启 Agent 后生效。"},
    )
    store.push_agents_changed()
    return {"agent": agent, "model": summary, "restart_required": agent.get("runtime_status") == "running"}


def current_agent_model(agent_id: str) -> dict:
    agent = store.find_agent(agent_id)
    if agent is None:
        raise ModelConfigError("agent not found", status_code=404)
    return {
        "agent": agent,
        "model": profiles.read_model_summary(agent["profile_name"]),
    }


def test_model_config(config_id: int, *, timeout: float = 10.0) -> dict:
    config = get_model_config(config_id)
    if config is None:
        raise ModelConfigError("model config not found", status_code=404)
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Accept": "application/json",
    }
    url = config["base_url"].rstrip("/") + "/models"
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "fail", "detail": f"HTTP request failed: {exc.__class__.__name__}"}
    if 200 <= response.status_code < 300:
        return {"ok": True, "status": "ok", "detail": f"HTTP {response.status_code} from {url}"}
    return {"ok": False, "status": "fail", "detail": f"HTTP {response.status_code} from {url}"}
