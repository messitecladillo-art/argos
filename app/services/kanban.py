from __future__ import annotations

import json
import subprocess
from typing import Any

from ..config import KANBAN_BOARD, KANBAN_DEFAULT_WORKSPACE


class KanbanError(RuntimeError):
    pass


class KanbanService:
    def __init__(self, *, board: str = KANBAN_BOARD, timeout: int = 60) -> None:
        self.board = board
        self.timeout = timeout

    def ensure_board(self) -> None:
        try:
            boards = self._run_json(["boards", "list", "--json"], scoped=False)
        except KanbanError:
            boards = []
        if not _contains_board(boards, self.board):
            self._run(
                [
                    "boards",
                    "create",
                    self.board,
                    "--name",
                    _title_from_slug(self.board),
                ],
                scoped=False,
            )

    def create_task(
        self,
        title: str,
        *,
        body: str,
        assignee: str | None,
        parent: str | list[str] | None = None,
        workspace: str = KANBAN_DEFAULT_WORKSPACE,
        priority: int | None = None,
        idempotency_key: str | None = None,
        skills: list[str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_board()
        args = [
            "create",
            title,
            "--body",
            body,
            "--workspace",
            workspace,
            "--json",
        ]
        if assignee:
            args.extend(["--assignee", assignee])
        parents = [parent] if isinstance(parent, str) else list(parent or [])
        for parent_id in parents:
            if parent_id:
                args.extend(["--parent", parent_id])
        if priority is not None:
            args.extend(["--priority", str(priority)])
        if idempotency_key:
            args.extend(["--idempotency-key", idempotency_key])
        for skill in skills or []:
            args.extend(["--skill", skill])
        return self._run_json(args)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        archived: bool = False,
    ) -> list[dict[str, Any]]:
        args = ["list", "--json"]
        if status:
            args.extend(["--status", status])
        if assignee:
            args.extend(["--assignee", assignee])
        if archived:
            args.append("--archived")
        data = self._run_json(args)
        return data if isinstance(data, list) else data.get("tasks", [])

    def show_task(self, task_id: str) -> dict[str, Any]:
        return self._run_json(["show", task_id, "--json"])

    def runs(self, task_id: str) -> Any:
        return self._run_json(["runs", task_id, "--json"])

    def log(self, task_id: str, *, tail: int | None = None) -> str:
        args = ["log", task_id]
        if tail is not None:
            args.extend(["--tail", str(tail)])
        return self._run(args)

    def context(self, task_id: str) -> str:
        return self._run(["context", task_id])

    def complete_task(
        self,
        task_id: str,
        *,
        result: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        args = ["complete", task_id, "--result", result]
        if summary:
            args.extend(["--summary", summary])
        if metadata is not None:
            args.extend(["--metadata", json.dumps(metadata, ensure_ascii=False)])
        return self._run(args)

    def dispatch_once(self, *, max_workers: int | None = None) -> Any:
        args = ["dispatch", "--json"]
        if max_workers is not None:
            args.extend(["--max", str(max_workers)])
        return self._run_json(args, timeout=600)

    def assign_task(self, task_id: str, profile: str) -> str:
        return self._run(["assign", task_id, profile])

    def unblock_task(self, task_id: str) -> str:
        return self._run(["unblock", task_id])

    def archive_task(self, task_id: str) -> str:
        return self._run(["archive", task_id])

    def archive_tasks(self, task_ids: list[str]) -> str:
        ids = [task_id for task_id in task_ids if task_id]
        if not ids:
            return ""
        return self._run(["archive", *ids])

    def _base_args(self, *, scoped: bool = True) -> list[str]:
        if scoped:
            return ["hermes", "kanban", "--board", self.board]
        return ["hermes", "kanban"]

    def _run(self, args: list[str], *, scoped: bool = True, timeout: int | None = None) -> str:
        try:
            result = subprocess.run(
                [*self._base_args(scoped=scoped), *args],
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.timeout,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise KanbanError("hermes CLI not found in PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise KanbanError("hermes kanban command timed out") from exc
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0 or output.startswith("kanban:") or error.startswith("kanban:"):
            detail = (error or output or "hermes kanban failed").strip()
            raise KanbanError(detail)
        return output

    def _run_json(self, args: list[str], *, scoped: bool = True, timeout: int | None = None) -> Any:
        output = self._run(args, scoped=scoped, timeout=timeout)
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise KanbanError(f"invalid hermes kanban JSON output: {output[:200]}") from exc


def extract_task_id(payload: dict[str, Any]) -> str:
    for key in ("task_id", "id", "key"):
        value = payload.get(key)
        if value:
            return str(value)
    for key in ("task", "card", "created", "data"):
        task = payload.get(key)
        if isinstance(task, dict):
            return extract_task_id(task)
    raise KanbanError("kanban task id missing from CLI response")


def task_status(payload: dict[str, Any]) -> str:
    value = payload.get("status") or payload.get("state")
    if value:
        return str(value)
    for key in ("task", "card", "created", "data"):
        task = payload.get(key)
        if isinstance(task, dict):
            return task_status(task)
    return ""


def task_result(payload: dict[str, Any]) -> str:
    for key in ("result", "summary"):
        value = payload.get(key)
        if value:
            return str(value)
    for key in ("task", "card", "created", "data"):
        task = payload.get(key)
        if isinstance(task, dict):
            return task_result(task)
    return ""


def _contains_board(payload: Any, board: str) -> bool:
    items = payload if isinstance(payload, list) else payload.get("boards", [])
    for item in items:
        if isinstance(item, dict) and item.get("slug") == board:
            return True
        if item == board:
            return True
    return False


def _title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


kanban_service = KanbanService()
