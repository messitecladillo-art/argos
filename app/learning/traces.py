"""ExecutionTrace collector — passively observes task flow and records traces."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..config import now_iso
from . import config as cfg


class TraceCollector:
    """Observes RuntimeStore events and builds ExecutionTrace records.

    All methods are no-ops if `enabled` is False.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._store: Any = None  # RuntimeStore, set during init_app

    def init_app(self, store: Any) -> None:
        self._store = store

    # ── trace lifecycle ──────────────────────────────────────

    def task_started(self, user_task_id: str, leader_agent_id: str, content: str) -> str | None:
        if not self.enabled or self._store is None:
            return None
        trace_id = _new_id("trace")
        self._store.insert_trace({
            "trace_id": trace_id,
            "user_task_id": user_task_id,
            "leader_agent_id": leader_agent_id,
            "phase": "decompose",
            "decomposition_json": "{}",
            "context_plan_json": "{}",
            "allocations_json": "[]",
            "decisions_json": "[]",
            "outcome_json": "{}",
            "quality_json": "{}",
            "created_at": now_iso(),
            "completed_at": None,
        })
        return trace_id

    def record_decomposition(
        self,
        trace_id: str,
        *,
        strategy: str,
        num_subtasks: int,
        roles_used: list[str],
        reasoning: str,
    ) -> None:
        if not self.enabled or self._store is None:
            return
        data = {
            "strategy": strategy,
            "num_subtasks": num_subtasks,
            "roles_used": roles_used,
            "reasoning": reasoning,
        }
        self._store.update_trace(trace_id, {"decomposition_json": json.dumps(data, ensure_ascii=False)})

    def record_context_plan(
        self,
        trace_id: str,
        *,
        total_tokens_estimate: int,
        files_provided: list[str],
        selection_method: str,
    ) -> None:
        if not self.enabled or self._store is None:
            return
        data = {
            "total_tokens_estimate": total_tokens_estimate,
            "files_provided": files_provided,
            "selection_method": selection_method,
        }
        self._store.update_trace(trace_id, {"context_plan_json": json.dumps(data, ensure_ascii=False)})

    def record_decision(
        self,
        trace_id: str,
        *,
        decision_point: str,
        options: list[str],
        chosen: str,
        reasoning: str,
    ) -> None:
        if not self.enabled or self._store is None:
            return
        entry = {
            "timestamp": now_iso(),
            "decision_point": decision_point,
            "options": options,
            "chosen": chosen,
            "reasoning": reasoning,
        }
        existing = self._store.get_trace(trace_id)
        if existing is None:
            return
        decisions = _json_loads(existing.get("decisions_json"), [])
        decisions.append(entry)
        self._store.update_trace(trace_id, {"decisions_json": json.dumps(decisions, ensure_ascii=False)})

    def record_allocation(
        self,
        trace_id: str,
        *,
        agent_id: str,
        role: str,
        assignment_id: str,
        context_summary: str,
        token_count: int = 0,
    ) -> None:
        if not self.enabled or self._store is None:
            return
        entry = {
            "agent_id": agent_id,
            "role": role,
            "assignment_id": assignment_id,
            "context_summary": context_summary,
            "token_count": token_count,
        }
        existing = self._store.get_trace(trace_id)
        if existing is None:
            return
        allocations = _json_loads(existing.get("allocations_json"), [])
        allocations.append(entry)
        self._store.update_trace(trace_id, {"allocations_json": json.dumps(allocations, ensure_ascii=False)})

    def record_allocation_result(self, assignment_id: str, result: str, status: str) -> None:
        if not self.enabled or self._store is None:
            return
        self._store.update_assignment_in_trace(assignment_id, result, status)

    def task_phase_change(self, user_task_id: str, phase: str) -> None:
        if not self.enabled or self._store is None:
            return
        self._store.update_trace_by_task(user_task_id, {"phase": phase})

    def task_completed(self, user_task_id: str, *, status: str, rounds: int, duration_s: float, summary: str) -> None:
        if not self.enabled or self._store is None:
            return
        outcome = {
            "status": status,
            "rounds_used": rounds,
            "total_duration_seconds": duration_s,
            "leader_summary": summary,
        }
        self._store.update_trace_by_task(user_task_id, {
            "phase": "complete",
            "outcome_json": json.dumps(outcome, ensure_ascii=False),
            "completed_at": now_iso(),
        })

    def set_quality(self, trace_id: str, success_score: float, efficiency_score: float, user_satisfaction: float) -> None:
        if not self.enabled or self._store is None:
            return
        data = {
            "success_score": success_score,
            "efficiency_score": efficiency_score,
            "user_satisfaction": user_satisfaction,
        }
        self._store.update_trace(trace_id, {"quality_json": json.dumps(data, ensure_ascii=False)})


# ── helpers ──────────────────────────────────────────────────

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _json_loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


trace_collector = TraceCollector(enabled=cfg.ENABLED)
