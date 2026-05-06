from __future__ import annotations

import json
import subprocess

import pytest

from app.services.kanban import KanbanError, KanbanService, extract_task_id


def test_create_task_uses_board_json_and_idempotency(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"task_id": "kb_1"}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    service = KanbanService(board="team-board")

    payload = service.create_task(
        "Build",
        body="Do it",
        assignee="dev",
        parent=["kb_parent"],
        priority=5,
        idempotency_key="assignment:asg_1",
    )

    assert extract_task_id(payload) == "kb_1"
    assert calls[0][:4] == ["hermes", "kanban", "--board", "team-board"]
    assert "--json" in calls[0]
    assert ["--idempotency-key", "assignment:asg_1"][0] in calls[0]
    assert "kb_parent" in calls[0]


def test_cli_error_becomes_kanban_error(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="bad board")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KanbanError, match="bad board"):
        KanbanService().list_tasks()
