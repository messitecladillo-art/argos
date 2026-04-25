from __future__ import annotations

from flask import Blueprint, render_template

from ..models.store import store


bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    snapshot = store.snapshot()
    leader = next(
        (agent for agent in snapshot["agents"] if agent.get("role") == "leader"),
        snapshot["agents"][0] if snapshot["agents"] else None,
    )
    terminal_events = []
    seen_terminal_agents = set()
    for event in snapshot["events"]:
        event_type = event.get("event_type")
        if event_type == "agent.terminal.output":
            terminal_events.append(event)
            continue
        if event_type == "agent.terminal.snapshot":
            agent_id = event.get("agent_id")
            if agent_id in seen_terminal_agents:
                continue
            terminal_events.append(event)
            seen_terminal_agents.add(agent_id)
    snapshot["events"] = terminal_events
    return render_template("index.html", **snapshot, message_target=leader)
