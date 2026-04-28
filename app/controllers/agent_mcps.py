from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services import mcp_installer
from ..services.acp import pool as session_pool

bp = Blueprint("agent_mcps", __name__, url_prefix="/api")


def _get_agent_or_404(agent_id: str) -> dict | None:
    return store.find_agent(agent_id)


def _reveal_secrets() -> bool:
    return str(request.args.get("reveal") or "0").lower() in {"1", "true", "yes"}


@bp.get("/agents/<agent_id>/mcps")
def list_agent_mcps(agent_id: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        mcps = mcp_installer.list_installed(
            agent["profile_name"],
            reveal_secrets=_reveal_secrets(),
        )
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(
        {
            "ok": True,
            "mcps": mcps,
            "agent": {
                "agent_id": agent["agent_id"],
                "profile_name": agent["profile_name"],
                "name": agent["name"],
            },
        }
    )


@bp.get("/agents/<agent_id>/mcps/<name>")
def get_agent_mcp(agent_id: str, name: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        mcp = mcp_installer.get_mcp(
            agent["profile_name"],
            name,
            reveal_secrets=_reveal_secrets(),
        )
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    if mcp is None:
        return jsonify({"ok": False, "error": "mcp not found"}), 404
    return jsonify({"ok": True, "mcp": mcp})


@bp.post("/agents/<agent_id>/mcps")
def add_agent_mcp(agent_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        mcp = mcp_installer.add_mcp(
            agent_id,
            name=payload.get("name") or "",
            transport=payload.get("transport") or "",
            url=payload.get("url"),
            headers=payload.get("headers"),
            command=payload.get("command"),
            args=payload.get("args"),
            env=payload.get("env"),
            description=payload.get("description") or "",
            takeover=bool(payload.get("takeover")),
        )
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "mcp": mcp, "requires_restart": True}), 201


@bp.put("/agents/<agent_id>/mcps/<name>")
def update_agent_mcp(agent_id: str, name: str):
    payload = request.get_json(silent=True) or {}
    try:
        mcp = mcp_installer.update_mcp(agent_id, name, patch=payload)
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "mcp": mcp, "requires_restart": True})


@bp.post("/agents/<agent_id>/mcps/<name>/test")
def test_agent_mcp(agent_id: str, name: str):
    try:
        result = mcp_installer.test_mcp(agent_id, name)
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(result)


@bp.delete("/agents/<agent_id>/mcps/<name>")
def delete_agent_mcp(agent_id: str, name: str):
    if request.args.get("confirm") != "1":
        return jsonify({"ok": False, "error": "confirm=1 is required"}), 400
    try:
        mcp_installer.remove_mcp(agent_id, name)
    except mcp_installer.McpError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "requires_restart": True})


@bp.post("/agents/<agent_id>/restart")
def restart_agent(agent_id: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    ok = session_pool.restart(agent)
    if not ok:
        return jsonify({"ok": False, "error": "agent restart failed"}), 500
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})
