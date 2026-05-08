from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services import model_configs
from ..services.model_configs import ModelConfigError
from ..services.profiles import ProfileError


bp = Blueprint("model_configs", __name__, url_prefix="/api")


def _json_error(exc: Exception, status_code: int = 400):
    return jsonify({"ok": False, "error": str(exc)}), status_code


@bp.get("/model-configs")
def list_model_configs():
    return jsonify({"ok": True, "items": model_configs.list_model_configs()})


@bp.post("/model-configs")
def create_model_config():
    payload = request.get_json(silent=True) or {}
    try:
        item = model_configs.create_model_config(payload)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    return jsonify({"ok": True, "item": item}), 201


@bp.put("/model-configs/<int:config_id>")
def update_model_config(config_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        item = model_configs.update_model_config(config_id, payload)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    return jsonify({"ok": True, "item": item})


@bp.delete("/model-configs/<int:config_id>")
def delete_model_config(config_id: int):
    try:
        model_configs.delete_model_config(config_id)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    return jsonify({"ok": True})


@bp.post("/model-configs/<int:config_id>/test")
def test_model_config(config_id: int):
    try:
        result = model_configs.test_model_config(config_id)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    return jsonify(result)


@bp.get("/agents/<agent_id>/model")
def get_agent_model(agent_id: str):
    try:
        result = model_configs.current_agent_model(agent_id)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    except ProfileError as exc:
        return _json_error(exc, 500)
    return jsonify({"ok": True, **result})


@bp.put("/agents/<agent_id>/model")
def update_agent_model(agent_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        config_id = int(payload.get("model_config_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "model_config_id is required"}), 400
    try:
        result = model_configs.apply_to_agent(agent_id, config_id)
    except ModelConfigError as exc:
        return _json_error(exc, exc.status_code)
    except ProfileError as exc:
        return _json_error(exc, 500)
    return jsonify({"ok": True, **result})
