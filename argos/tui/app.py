"""Argos Terminal UI — real-time agent & kanban dashboard powered by Textual."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

from rich.text import Text as RichText
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListView,
    ListItem,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from ..config import (
    AGENT_TEAM_WORKSPACE_ROOT,
    DATABASE_URL,
    HERMES_HOME,
    KANBAN_BOARD,
    MCP_BUS_URL,
    SECRET_KEY,
)

STATUS_ICONS = {
    "running": "●",
    "stopped": "○",
    "error": "✗",
    "ready": "◉",
    "busy": "◎",
}
STATUS_COLORS = {
    "running": "#22dd88",
    "stopped": "#666666",
    "error": "#ee4444",
    "ready": "#4488ff",
    "busy": "#ddaa00",
}


class AgentListItem(ListItem):
    """A single agent row in the sidebar list."""

    def __init__(self, agent: dict[str, Any]) -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        agent = self._agent
        runtime = agent.get("runtime_status", "stopped")
        icon = STATUS_ICONS.get(runtime, "?")
        color = STATUS_COLORS.get(runtime, "#888888")
        name = agent.get("name") or agent.get("agent_id", "?")
        role = agent.get("role", "?")
        yield Label(RichText(f" {icon} {name}", style=color))
        yield Label(RichText(f"   {role}", style="dim italic"))


class AgentSidebar(Static):
    """Sidebar listing all agents with status."""

    def compose(self) -> ComposeResult:
        yield Label(RichText("◆ AGENTS", style="bold #44aaff"))
        yield Static(id="agent-count")
        yield ListView(id="agent-list")

    def on_mount(self) -> None:
        self.refresh_agents()
        self.set_interval(3, self.refresh_agents)

    def refresh_agents(self) -> None:
        try:
            from ..models.store import store
            snapshot = store.snapshot()
            agents = snapshot.get("agents", [])
        except Exception:
            agents = []

        list_view = self.query_one("#agent-list", ListView)
        list_view.clear()
        count = self.query_one("#agent-count", Static)
        running = sum(1 for a in agents if a.get("runtime_status") == "running")
        count.update(RichText(
            f"{len(agents)} total · {running} running",
            style="dim #8899aa",
        ))

        for agent in agents:
            list_view.append(AgentListItem(agent))


class EventsPanel(Vertical):
    """Panel displaying recent events."""

    def compose(self) -> ComposeResult:
        yield RichLog(id="events-log", highlight=True, markup=True, max_lines=200)

    def on_mount(self) -> None:
        self.refresh_events()
        self.set_interval(2, self.refresh_events)

    def refresh_events(self) -> None:
        log = self.query_one("#events-log", RichLog)
        try:
            from ..models.store import store
            snapshot = store.snapshot()
            events = snapshot.get("events", [])
        except Exception:
            events = []

        log.clear()
        for ev in reversed(events[-60:]):
            ev_type = ev.get("type", "?")
            agent_id = ev.get("agent_id", "") or ""
            if agent_id:
                try:
                    agent = store.find_agent(agent_id)
                    name = (agent or {}).get("name", agent_id) if agent else agent_id
                except Exception:
                    name = agent_id
            else:
                name = ""
            ts = (ev.get("timestamp") or "")[:19].replace("T", " ")
            payload = ev.get("payload", {})
            text = str(payload.get("text", "") or ev_type)[:140]
            style = "dim #8899aa"
            if "error" in ev_type.lower() or "fail" in ev_type.lower():
                style = "#ee4444"
            elif "complete" in ev_type.lower() or "ready" in ev_type.lower():
                style = "#22dd88"

            if name:
                log.write(RichText(f"[{ts}] [{style}]{name}[/{style}] {text}"))
            else:
                log.write(RichText(f"[{ts}] [{style}]{ev_type}[/{style}] {text}"))


class KanbanPanel(Vertical):
    """Panel displaying Kanban task links."""

    def compose(self) -> ComposeResult:
        yield Static(id="kanban-board-label")
        yield DataTable(id="kanban-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#kanban-table", DataTable)
        table.add_columns("Agent", "Status", "Task ID", "Summary")
        self.refresh_kanban()
        self.set_interval(5, self.refresh_kanban)

    def refresh_kanban(self) -> None:
        label = self.query_one("#kanban-board-label", Static)
        label.update(RichText(f"◆ Board: {KANBAN_BOARD}", style="bold #44aaff"))

        table = self.query_one("#kanban-table", DataTable)
        table.clear()
        try:
            from ..models.store import store
            snapshot = store.snapshot()
            links = snapshot.get("kanban_task_links", [])
        except Exception:
            links = []

        for link in links[-50:]:
            assignee = link.get("assignee_profile", "") or "—"
            agent = None
            try:
                agent = store.find_agent(assignee)
            except Exception:
                pass
            name = (agent or {}).get("name", assignee) if agent else assignee
            status = link.get("kanban_status", "?")
            task_id = (link.get("kanban_task_id") or "")[:26]
            meta = link.get("metadata", {}) or {}
            title = str(meta.get("task_title", ""))[:64]

            color = "#8899aa"
            if status in ("done", "completed", "archived"):
                color = "#22dd88"
            elif status in ("ready", "in_progress"):
                color = "#eedd44"
            elif status in ("blocked", "failed"):
                color = "#ee4444"

            table.add_row(
                RichText(name, style=color),
                RichText(status, style=color),
                RichText(task_id, style="dim"),
                RichText(title),
            )


class SystemPanel(Vertical):
    """Panel showing system information."""

    def compose(self) -> ComposeResult:
        yield Label(RichText("◆ SYSTEM", style="bold #44aaff"))
        yield Static(id="system-info")

    def on_mount(self) -> None:
        lines = [
            f"  Python         {sys.version.split()[0]}",
            f"  Platform       {sys.platform}",
            f"  DATABASE_URL   {DATABASE_URL}",
            f"  HERMES_HOME    {HERMES_HOME}",
            f"  WORKSPACE_ROOT {AGENT_TEAM_WORKSPACE_ROOT}",
            f"  KANBAN_BOARD   {KANBAN_BOARD}",
            f"  MCP_BUS_URL    {MCP_BUS_URL}",
            f"  SECRET_KEY     {'set' if SECRET_KEY else 'not set'}",
            f"  API_TOKEN      {'set' if os.environ.get('API_TOKEN') else 'not set'}",
            f"",
            f"  [bold #44aaff]Shortcuts:[/bold #44aaff]",
            f"  [dim]1[/dim] Agents  [dim]2[/dim] Events  [dim]3[/dim] Kanban  [dim]4[/dim] System",
            f"  [dim]r[/dim] Refresh  [dim]q[/dim] Quit",
        ]
        self.query_one("#system-info", Static).update(RichText("\n".join(lines)))


class ArgosTUI(App):
    """Terminal dashboard for Argos multi-agent team."""

    TITLE = "Argos"
    SUB_TITLE = "Agent Team Dashboard"

    CSS = """
    * { scrollbar-size: 0 0; }

    Screen {
        background: #0d1117;
    }

    Header {
        background: #161b22;
        color: #4499ee;
        border-bottom: solid #30363d;
    }

    #sidebar {
        width: 30;
        background: #161b22;
        border-right: solid #30363d;
        padding: 1 1;
    }

    #agent-list {
        height: 1fr;
        background: #0d1117;
        border: solid #21262d;
        padding: 0 1;
    }

    #agent-count {
        padding: 0 1;
        margin-bottom: 1;
    }

    #events-log {
        height: 1fr;
        background: #0d1117;
        border: solid #21262d;
    }

    #kanban-table {
        height: 1fr;
        background: #0d1117;
    }

    #kanban-board-label {
        padding: 0 1;
    }

    #system-info {
        padding: 1 2;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    TabPane:focus {
        border: tall #4488ff;
    }

    Label {
        padding: 0 1;
    }

    ListView:focus > ListItem.--highlight {
        background: #1a3050;
    }

    DataTable:focus > .datatable--cursor {
        background: #1a3050;
    }

    Footer {
        background: #161b22;
        color: #8899aa;
        border-top: solid #30363d;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("1", "focus_agents", "Agents", show=True),
        Binding("2", "focus_events", "Events", show=True),
        Binding("3", "focus_kanban", "Kanban", show=True),
        Binding("4", "focus_system", "System", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            yield AgentSidebar(id="sidebar")
            with Vertical():
                with TabbedContent():
                    with TabPane("◆ Events", id="tab-events"):
                        yield EventsPanel()
                    with TabPane("◆ Kanban", id="tab-kanban"):
                        yield KanbanPanel()
                    with TabPane("◆ System", id="tab-system"):
                        yield SystemPanel()
        yield Footer()

    def on_mount(self) -> None:
        try:
            from ..db import init_database
            init_database()
        except Exception:
            pass
        try:
            from ..models.store import store
            store.load_persisted_state()
        except Exception:
            pass

    def action_focus_agents(self) -> None:
        try:
            self.query_one("#agent-list", ListView).focus()
        except Exception:
            pass

    def action_focus_events(self) -> None:
        try:
            self.query_one("#tab-events", TabPane).focus()
        except Exception:
            pass

    def action_focus_kanban(self) -> None:
        try:
            self.query_one("#tab-kanban", TabPane).focus()
        except Exception:
            pass

    def action_focus_system(self) -> None:
        try:
            self.query_one("#tab-system", TabPane).focus()
        except Exception:
            pass

    def action_refresh(self) -> None:
        try:
            self.query_one(AgentSidebar).refresh_agents()
        except Exception:
            pass


def main() -> None:
    ArgosTUI().run()


if __name__ == "__main__":
    main()
