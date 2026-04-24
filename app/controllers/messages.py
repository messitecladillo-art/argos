from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services import messages as messages_service


bp = Blueprint("messages", __name__, url_prefix="/api")


@bp.post("/messages")
def create_message():
    payload = request.get_json(silent=True) or {}
    try:
        message = messages_service.send_user_task(
            store,
            content=payload.get("content") or "",
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "message": message}), 201
