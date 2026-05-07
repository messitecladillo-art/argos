from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services.kanban import KanbanError, kanban_service
from ..services.kanban_sync import sync_worker
from ..services.settings import settings_service


bp = Blueprint("kanban", __name__, url_prefix="/api/kanban")


@bp.get("/tasks")
def list_tasks():
    sync_worker.sync_once()
    return jsonify({"ok": True, "links": store.snapshot().get("kanban_task_links", [])})


@bp.get("/tasks/<task_id>/runs")
def task_runs(task_id: str):
    try:
        return jsonify({"ok": True, "runs": kanban_service.runs(task_id)})
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.get("/tasks/<task_id>/log")
def task_log(task_id: str):
    tail = request.args.get("tail", type=int)
    try:
        return jsonify({"ok": True, "log": kanban_service.log(task_id, tail=tail)})
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.post("/dispatch")
def dispatch_once():
    max_workers = request.get_json(silent=True) or {}
    try:
        return jsonify(
            {
                "ok": True,
                "result": kanban_service.dispatch_once(
                    max_workers=max_workers.get("max_workers")
                ),
            }
        )
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.get("/settings")
def get_settings():
    return jsonify(
        {
            "ok": True,
            "settings": {
                "auto_dispatch_enabled": settings_service.get_kanban_auto_dispatch_enabled(),
                "auto_dispatch_interval_ms": 5000,
            },
        }
    )


@bp.put("/settings")
def update_settings():
    payload = request.get_json(silent=True) or {}
    if "auto_dispatch_enabled" not in payload or not isinstance(payload["auto_dispatch_enabled"], bool):
        return jsonify({"ok": False, "error": "auto_dispatch_enabled must be boolean"}), 400
    enabled = settings_service.set_kanban_auto_dispatch_enabled(payload["auto_dispatch_enabled"])
    return jsonify(
        {
            "ok": True,
            "settings": {
                "auto_dispatch_enabled": enabled,
                "auto_dispatch_interval_ms": 5000,
            },
        }
    )
