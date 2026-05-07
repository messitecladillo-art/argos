from __future__ import annotations

from flask import Blueprint, render_template

from ..models.store import store


bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    snapshot = store.snapshot()
    leader = next(
        (
            agent
            for agent in snapshot["agents"]
            if agent.get("role") == "leader"
            and (agent.get("readiness_status") or "ready") == "ready"
        ),
        next(
            (
                agent
                for agent in snapshot["agents"]
                if (agent.get("readiness_status") or "ready") == "ready"
            ),
            None,
        ),
    )
    snapshot["events"] = [
        event
        for event in snapshot["events"]
        if event.get("event_type")
        not in {"agent.terminal.output", "agent.terminal.snapshot"}
    ]
    snapshot["kanban_task_links"] = [
        link
        for link in snapshot.get("kanban_task_links", [])
        if (link.get("kanban_status") or "").lower() != "archived"
    ]
    return render_template("index.html", **snapshot, message_target=leader)
