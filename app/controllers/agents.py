from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services import agents as agents_service
from ..services.acp import pool as session_pool
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
        status_code = 404 if str(exc) == "agent not found" else 400
        return jsonify({"ok": False, "error": str(exc)}), status_code
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent})


@bp.post("/agents/<agent_id>/start")
def start_agent(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    ok = session_pool.start(agent)
    return jsonify({"ok": ok, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/stop")
def stop_agent(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    session_pool.stop(agent_id)
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/interactions/<request_id>/respond")
def respond_interaction(agent_id: str, request_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.respond_interaction(
            agent_id,
            request_id,
            payload.get("response") or "",
        )
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/terminal-input")
def send_terminal_input(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.send_terminal_input(agent_id, payload.get("text") or "")
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/terminal-data")
def send_terminal_data(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.send_terminal_data(agent_id, payload.get("data") or "")
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/terminal-resize")
def resize_terminal(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        rows = int(payload.get("rows") or 0)
        cols = int(payload.get("cols") or 0)
        if rows <= 0 or cols <= 0:
            raise ValueError("rows and cols are required")
        session_pool.resize_terminal(agent_id, rows, cols)
    except (RuntimeError, ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})
