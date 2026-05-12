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
    create_call = calls[-1]
    assert create_call[:4] == ["hermes", "kanban", "--board", "team-board"]
    assert "--json" in create_call
    assert ["--idempotency-key", "assignment:asg_1"][0] in create_call
    assert "kb_parent" in create_call


def test_cli_error_becomes_kanban_error(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="bad board")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KanbanError, match="bad board"):
        KanbanService().list_tasks()


def test_reset_board_deletes_and_recreates_non_default_board(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = KanbanService(board="team-board").reset_board()

    assert result["board"] == "team-board"
    assert calls[0] == ["hermes", "kanban", "boards", "rm", "team-board", "--delete"]
    assert calls[1] == ["hermes", "kanban", "boards", "create", "team-board", "--name", "Team Board"]


def test_reset_board_rejects_default_board():
    with pytest.raises(KanbanError, match="default board cannot be reset"):
        KanbanService(board="default").reset_board()
