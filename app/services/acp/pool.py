"""ACPPool — lifecycle manager for HermesSession instances.

One ACPPool owns a map of agent_id → HermesSession, starts/stops them and
routes finalized worker replies through the summary prompts back to the
leader. Exposes the module-level `pool` singleton used across the app.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

from ...models.store import store
from .. import registry
from .helpers import CONCISE_SUMMARY_RULES, _log_state
from .session import HermesSession


class ACPPool:
    """Compatibility wrapper kept under the old module path/import name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.clients: dict[str, HermesSession] = {}

    def is_running(self, agent_id: str) -> bool:
        with self._lock:
            session = self.clients.get(agent_id)
        return bool(session and session.proc.isalive())

    def start(self, agent: dict) -> bool:
        agent_id = agent["agent_id"]
        if (agent.get("readiness_status") or "ready") != "ready":
            _log_state("start_skipped_not_ready", agent_id, readiness=agent.get("readiness_status"))
            return False
        profile_name = agent["profile_name"]
        workspace_path = agent.get("workspace_path") or str(
            registry.workspace_path_for(profile_name)
        )
        pending_items: list[dict[str, Any]] = []
        with self._lock:
            existing = self.clients.get(agent_id)
            if existing and existing.proc.isalive():
                return True
            if existing is not None:
                pending_items = existing.take_pending_messages()
        try:
            workspace_path = registry.ensure_workspace(profile_name, workspace_path)
            store.update_agent(agent_id, workspace_path=workspace_path)
            session = HermesSession(profile_name, agent_id, workspace_path, self._on_final)
        except FileNotFoundError:
            store.update_agent(
                agent_id,
                runtime_status="crashed",
                interaction_state="failed",
                status="offline",
            )
            store.push_event(
                "agent.runtime.failed",
                agent_id,
                None,
                {"text": "hermes CLI not found in PATH"},
            )
            return False
        except Exception as exc:  # noqa: BLE001
            store.update_agent(
                agent_id,
                runtime_status="crashed",
                interaction_state="failed",
                status="offline",
            )
            store.push_event(
                "agent.runtime.failed",
                agent_id,
                None,
                {"text": f"failed to start Hermes session: {exc}"},
            )
            return False
        with self._lock:
            self.clients[agent_id] = session
        session.restore_pending_messages(pending_items)
        store.update_agent(
            agent_id,
            runtime_status="running",
            interaction_state="idle",
            pending_interaction=None,
            status="idle",
            current_task="空闲",
        )
        store.push_event(
            "agent.runtime.started",
            agent_id,
            None,
            {"text": f"Hermes session 已启动（profile={profile_name}）"},
        )
        return True

    def stop(self, agent_id: str) -> None:
        with self._lock:
            session = self.clients.pop(agent_id, None)
        if session is not None:
            session.close()
        store.update_agent(
            agent_id,
            runtime_status="stopped",
            interaction_state="idle",
            pending_interaction=None,
            queue_depth=0,
            status="offline",
            current_task="已停止",
        )
        store.push_event(
            "agent.runtime.stopped",
            agent_id,
            None,
            {"text": "Hermes session 已停止"},
        )

    def restart(self, agent: dict) -> bool:
        agent_id = agent["agent_id"]
        self.stop(agent_id)
        return self.start(agent)

    def prompt(
        self,
        agent_id: str,
        content: str,
        *,
        reply_to_leader: str | None = None,
        delegation_id: str | None = None,
        assignment_id: str | None = None,
        user_task_id: str | None = None,
        summarize_delegation_id: str | None = None,
        summarize_user_task_id: str | None = None,
    ) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        _log_state(
            "pool_prompt",
            agent_id,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            user_task_id=user_task_id,
            summarize_user_task_id=summarize_user_task_id,
        )
        session.enqueue_message(
            content,
            reply_to_leader=reply_to_leader,
            delegation_id=delegation_id,
            assignment_id=assignment_id,
            user_task_id=user_task_id,
            summarize_delegation_id=summarize_delegation_id,
            summarize_user_task_id=summarize_user_task_id,
        )

    def current_user_task_id(self, agent_id: str) -> str | None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            return None
        return session.current_user_task_id()

    def respond_interaction(self, agent_id: str, request_id: str, response: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.respond_interaction(request_id, response)

    def send_terminal_input(self, agent_id: str, text: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.send_terminal_input(text)

    def send_terminal_data(self, agent_id: str, data: str) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.send_terminal_data(data)

    def resize_terminal(self, agent_id: str, rows: int, columns: int) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        session.resize_terminal(rows, columns)

    def attach_terminal(self, agent_id: str) -> tuple[queue.Queue[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None or not session.proc.isalive():
            raise RuntimeError("agent session is not running; start it first")
        return session.open_terminal_stream()

    def detach_terminal(self, agent_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            session = self.clients.get(agent_id)
        if session is None:
            return
        session.close_terminal_stream(subscriber)

    def _on_final(
        self,
        agent_id: str,
        reply: str,
        leader_id: str | None,
        delegation_id: str | None,
        assignment_id: str | None,
        user_task_id: str | None,
        summarize_delegation_id: str | None,
        summarize_user_task_id: str | None,
        failed: bool = False,
    ) -> None:
        if summarize_user_task_id:
            _log_state("summary_final", agent_id, user_task_id=summarize_user_task_id, reply_len=len(reply or ""))
            try:
                store.mark_user_task_completed(summarize_user_task_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "user_task.summary.failed",
                    agent_id,
                    summarize_user_task_id,
                    {"text": f"标记用户任务总结完成失败：{exc}"},
                )
            return
        if summarize_delegation_id:
            try:
                store.mark_delegation_summarized(summarize_delegation_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "delegation.summary.failed",
                    agent_id,
                    summarize_delegation_id,
                    {"text": f"标记批次总结完成失败：{exc}"},
                )
        if leader_id and delegation_id and assignment_id:
            _log_state(
                "assignment_final",
                agent_id,
                delegation_id=delegation_id,
                assignment_id=assignment_id,
                user_task_id=user_task_id,
                failed=failed,
                reply_len=len(reply or ""),
            )
            try:
                completed = store.complete_assignment(
                    delegation_id,
                    assignment_id,
                    result=reply or "(空响应)",
                    failed=failed,
                )
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "delegation.assignment.failed",
                    agent_id,
                    delegation_id,
                    {"text": f"记录 worker 结果失败：{exc}"},
                )
                completed = None
            if completed:
                if completed.get("user_task_id"):
                    self._prompt_user_task_to_summarize(completed)
                else:
                    self._prompt_leader_to_summarize(completed)
            return
        if user_task_id:
            _log_state("user_task_dispatch_final", agent_id, user_task_id=user_task_id, reply_len=len(reply or ""))
            try:
                completed = store.close_user_task_dispatch(user_task_id)
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "user_task.dispatch.failed",
                    agent_id,
                    user_task_id,
                    {"text": f"关闭用户任务派发阶段失败：{exc}"},
                )
                completed = None
            if completed:
                self._prompt_user_task_to_summarize(completed)
            return
        if leader_id:
            worker = store.find_agent(agent_id) or {}
            name = worker.get("name") or agent_id
            try:
                self.prompt(leader_id, f"[来自 {name} 的回复]: {reply}")
            except Exception as exc:  # noqa: BLE001
                store.push_event(
                    "agent.output.failed",
                    leader_id,
                    None,
                    {"text": f"回推 leader 失败：{exc}"},
                )

    def _prompt_leader_to_summarize(self, delegation: dict) -> None:
        leader_id = delegation["leader_agent_id"]
        delegation_id = delegation["delegation_id"]
        store.mark_delegation_summarizing(delegation_id)
        results = []
        for index, assignment in enumerate(delegation["assignments"], start=1):
            results.append(
                "\n".join(
                    [
                        f"## {index}. {assignment['worker_name']} ({assignment['worker_agent_id']})",
                        f"子任务：{assignment['content']}",
                        f"状态：{assignment['status']}",
                        "结果：",
                        assignment.get("result") or "(空响应)",
                    ]
                )
            )
        worker_results = "\n\n".join(results)
        prompt = (
            "[SYSTEM_DELEGATION_SUMMARY_REQUEST]\n"
            f"delegation_id: {delegation_id}\n"
            "同一批 worker 子任务已经全部结束。请只基于以下 worker 结果，面向用户输出最终总结。\n"
            "不要再次派发同一批任务；如有缺失或失败，请在总结中明确说明。\n\n"
            "总结要求：\n"
            f"{delegation['summary_instruction']}\n\n"
            f"{CONCISE_SUMMARY_RULES}\n"
            "Worker 结果：\n"
            f"{worker_results}"
        )
        try:
            self.prompt(
                leader_id,
                prompt,
                summarize_delegation_id=delegation_id,
            )
        except Exception as exc:  # noqa: BLE001
            store.push_event(
                "agent.output.failed",
                leader_id,
                delegation_id,
                {"text": f"回推 leader 汇总请求失败：{exc}"},
            )

    def _prompt_user_task_to_summarize(self, user_task: dict) -> None:
        user_task_id = user_task["user_task_id"]
        user_task = store.mark_user_task_summarizing(user_task_id)
        leader_id = user_task["leader_agent_id"]
        results = []
        for delegation in store.snapshot()["delegations"]:
            if delegation.get("user_task_id") != user_task_id:
                continue
            for index, assignment in enumerate(delegation["assignments"], start=1):
                results.append(
                    "\n".join(
                        [
                            f"## {len(results) + 1}. {assignment['worker_name']} ({assignment['worker_agent_id']})",
                            f"批次：{delegation['delegation_id']}",
                            f"子任务：{assignment['content']}",
                            f"状态：{assignment['status']}",
                            "结果：",
                            assignment.get("result") or "(空响应)",
                        ]
                    )
                )
        worker_results = "\n\n".join(results) or "(没有 worker 结果)"
        prompt = (
            "[SYSTEM_USER_TASK_SUMMARY_REQUEST]\n"
            f"user_task_id: {user_task_id}\n"
            "同一个用户任务拆分出的所有 worker 子任务已经全部结束。请只基于以下 worker 结果，面向用户输出最终总结。\n"
            "不要再次派发同一批任务；如有缺失或失败，请在总结中明确说明。\n\n"
            f"{CONCISE_SUMMARY_RULES}\n"
            "用户原始任务：\n"
            f"{user_task.get('content') or ''}\n\n"
            "Worker 结果：\n"
            f"{worker_results}"
        )
        try:
            self.prompt(
                leader_id,
                prompt,
                summarize_user_task_id=user_task_id,
            )
        except Exception as exc:  # noqa: BLE001
            store.push_event(
                "agent.output.failed",
                leader_id,
                user_task_id,
                {"text": f"回推 leader 用户任务汇总请求失败：{exc}"},
            )

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self.clients.keys())
        for agent_id in ids:
            self.stop(agent_id)


pool = ACPPool()
