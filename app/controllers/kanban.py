from __future__ import annotations

import logging
import time

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services.kanban import KanbanError, kanban_service
from ..services.kanban_dispatch import dispatch_worker
from ..services.kanban_sync import sync_worker
from ..services.settings import settings_service


bp = Blueprint("kanban", __name__, url_prefix="/api/kanban")
logger = logging.getLogger("hermes.agent_state")


@bp.get("/tasks")
def list_tasks():
    sync_worker.sync_once_async()
    return jsonify({"ok": True, "links": _visible_kanban_links()})


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


@bp.get("/tasks/<task_id>/details")
def task_details(task_id: str):
    tail = request.args.get("tail", 4000, type=int)
    try:
        return jsonify(
            {
                "ok": True,
                "task": kanban_service.show_task(task_id),
                "runs": kanban_service.runs(task_id),
                "context": kanban_service.context(task_id),
                "log": kanban_service.log(task_id, tail=tail),
            }
        )
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.delete("/tasks/done")
def archive_done_tasks():
    return _archive_column("done")


@bp.delete("/tasks/column/<column_key>")
def archive_column_tasks(column_key: str):
    return _archive_column(column_key)


_COLUMN_STATUS_MAP = {
    "ready": {"pending_dispatch", "ready", "todo", "triage"},
    "running": {"running"},
    "blocked": {"blocked", "failed", "crashed", "timed_out", "gave_up"},
    "done": {"done"},
}


def _column_for_status(status: str) -> str:
    value = (status or "").lower()
    for column, statuses in _COLUMN_STATUS_MAP.items():
        if value in statuses:
            return column
    return "unknown"


def _archive_column(column_key: str):
    started = time.perf_counter()
    column_key = (column_key or "").lower()
    matched = [
        link
        for link in _visible_kanban_links()
        if _column_for_status(link.get("kanban_status") or "") == column_key
    ]
    task_ids = [link["kanban_task_id"] for link in matched if link.get("kanban_task_id")]
    if not task_ids:
        return jsonify({"ok": True, "archived_count": 0, "links": _visible_kanban_links()})
    try:
        cli_started = time.perf_counter()
        output = kanban_service.archive_tasks(task_ids)
        cli_elapsed = time.perf_counter() - cli_started
        for task_id in task_ids:
            store.update_kanban_task_link(task_id, kanban_status="archived")
        sync_worker.sync_once_async()
        logger.warning(
            "[kanban-archive] column=%s count=%s cli=%.3fs total=%.3fs",
            column_key,
            len(task_ids),
            cli_elapsed,
            time.perf_counter() - started,
        )
        return jsonify(
            {
                "ok": True,
                "output": output,
                "archived_count": len(task_ids),
                "links": _visible_kanban_links(),
            }
        )
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.post("/tasks/<task_id>/unblock")
def unblock_task(task_id: str):
    try:
        output = kanban_service.unblock_task(task_id)
        link = store.find_kanban_task_link(kanban_task_id=task_id)
        if link:
            metadata = dict(link.get("metadata") or {})
            metadata.pop("dispatch_started_at", None)
            metadata.pop("running_housekeeping_at", None)
            store.update_kanban_task_link(task_id, kanban_status="ready", metadata=metadata)
        sync_worker.sync_once()
        dispatch_worker.trigger_async()
        return jsonify({"ok": True, "output": output, "links": _visible_kanban_links()})
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.delete("/tasks/<task_id>")
def archive_task(task_id: str):
    started = time.perf_counter()
    try:
        cli_started = time.perf_counter()
        output = kanban_service.archive_task(task_id)
        cli_elapsed = time.perf_counter() - cli_started
        store.update_kanban_task_link(task_id, kanban_status="archived")
        sync_worker.sync_once_async()
        logger.warning(
            "[kanban-archive] task=%s cli=%.3fs total=%.3fs",
            task_id,
            cli_elapsed,
            time.perf_counter() - started,
        )
        return jsonify({"ok": True, "output": output, "links": _visible_kanban_links()})
    except KanbanError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _visible_kanban_links() -> list[dict]:
    return [
        link
        for link in store.snapshot().get("kanban_task_links", [])
        if (link.get("kanban_status") or "").lower() != "archived"
    ]


@bp.post("/dispatch")
def dispatch_once():
    payload = request.get_json(silent=True) or {}
    try:
        outcome = dispatch_worker.dispatch_now(max_workers=payload.get("max_workers"))
        return jsonify(
            {
                "ok": True,
                "released_count": outcome.get("released_count", 0),
                "result": outcome.get("result"),
                "skipped": outcome.get("skipped", False),
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
                "auto_dispatch_interval_ms": 2000,
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
                "auto_dispatch_interval_ms": 2000,
            },
        }
    )
