from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services import agents as agents_service
from ..services.profiles import ProfileError, list_hermes_profiles


bp = Blueprint("agents", __name__, url_prefix="/api")


@bp.get("/dashboard")
def dashboard():
    return jsonify(store.snapshot())


@bp.get("/profiles")
def list_profiles():
    return jsonify({"profiles": list_hermes_profiles()})


@bp.post("/agents")
def create_agent():
    payload = request.get_json(silent=True) or {}
    try:
        agent = agents_service.create_agent(
            store,
            name=payload.get("name") or "",
            profile_name=payload.get("profile_name") or "",
            role=payload.get("role") or "worker",
            description=payload.get("description") or "",
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent}), 201


@bp.delete("/agents/<agent_id>")
def delete_agent(agent_id: str):
    try:
        agent = agents_service.delete_agent(store, agent_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent})
