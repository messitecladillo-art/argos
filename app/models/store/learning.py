"""Learning mixin for RuntimeStore — traces, memories, feedback signals."""

from __future__ import annotations

import json
from typing import Any


class LearningMixin:
    """In-memory collections backed by SQLitePersistence.

    All mutation methods persist through self._persist().
    """

    # ── execution traces ─────────────────────────────────────

    def insert_trace(self, trace: dict[str, Any]) -> None:
        with self._lock:
            existing = getattr(self, "traces", None)
            if existing is None:
                self.traces: list[dict[str, Any]] = []
            self.traces.append(trace)
            self._persist("insert_trace", trace)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            for t in getattr(self, "traces", []):
                if t.get("trace_id") == trace_id:
                    return dict(t)
        return None

    def update_trace(self, trace_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for i, t in enumerate(getattr(self, "traces", [])):
                if t.get("trace_id") == trace_id:
                    next_t = dict(t)
                    next_t.update(updates)
                    next_t["db_updated_at"] = None  # trigger ORM onupdate
                    self.traces[i] = next_t
                    self._persist("update_trace", trace_id, updates)
                    return

    def update_trace_by_task(self, user_task_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for i, t in enumerate(getattr(self, "traces", [])):
                if t.get("user_task_id") == user_task_id:
                    next_t = dict(t)
                    next_t.update(updates)
                    next_t["db_updated_at"] = None
                    self.traces[i] = next_t
                    self._persist("update_trace", t["trace_id"], updates)
                    return

    def get_trace_by_user_task(self, user_task_id: str) -> dict[str, Any] | None:
        with self._lock:
            for t in getattr(self, "traces", []):
                if t.get("user_task_id") == user_task_id:
                    return dict(t)
        return None

    def update_assignment_in_trace(self, assignment_id: str, result: str, status: str) -> None:
        with self._lock:
            for t in getattr(self, "traces", []):
                allocs = t.get("allocations_json", "[]")
                if isinstance(allocs, str):
                    try:
                        allocs = json.loads(allocs)
                    except (json.JSONDecodeError, TypeError):
                        continue
                for alloc in allocs:
                    if alloc.get("assignment_id") == assignment_id:
                        alloc["result"] = result
                        alloc["status"] = status
                        t["allocations_json"] = json.dumps(allocs, ensure_ascii=False)
                        self._persist("update_trace", t["trace_id"], {"allocations_json": t["allocations_json"]})
                        return

    def list_traces_needing_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            result: list[dict[str, Any]] = []
            for t in getattr(self, "traces", []):
                outcome = _json_dict(t.get("outcome_json"))
                if outcome.get("status") not in {"completed", "failed", "blocked"}:
                    continue
                q = t.get("quality_json", "{}")
                if isinstance(q, str):
                    try:
                        q = json.loads(q)
                    except (json.JSONDecodeError, TypeError):
                        pass
                if not q:
                    result.append(dict(t))
                if len(result) >= limit:
                    break
            return result

    def list_unconsolidated_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            result: list[dict[str, Any]] = []
            for t in getattr(self, "traces", []):
                if t.get("consolidated"):
                    continue
                outcome = _json_dict(t.get("outcome_json"))
                if outcome.get("status") not in {"completed", "failed", "blocked"}:
                    continue
                result.append(dict(t))
                if len(result) >= limit:
                    break
            return result

    def mark_traces_consolidated(self, traces: list[dict[str, Any]]) -> None:
        with self._lock:
            ids = {t.get("trace_id") for t in traces}
            for i, t in enumerate(getattr(self, "traces", [])):
                if t.get("trace_id") in ids:
                    t["consolidated"] = True
                    self._persist("update_trace", t["trace_id"], {"consolidated": True})

    # ── memory items ─────────────────────────────────────────

    def find_memory(self, memory_id: str) -> dict[str, Any] | None:
        with self._lock:
            for m in getattr(self, "memories", []):
                if m.get("memory_id") == memory_id:
                    return dict(m)
        return None

    def insert_memory(self, memory: dict[str, Any]) -> None:
        with self._lock:
            existing = getattr(self, "memories", None)
            if existing is None:
                self.memories: list[dict[str, Any]] = []
            self.memories.append(memory)
            self._persist("insert_memory", memory)

    def update_memory(self, memory_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for i, m in enumerate(getattr(self, "memories", [])):
                if m.get("memory_id") == memory_id:
                    next_m = dict(m)
                    next_m.update(updates)
                    self.memories[i] = next_m
                    self._persist("update_memory", memory_id, updates)
                    return

    def list_memories(
        self,
        *,
        layer: str | None = None,
        min_weight: float = 0.3,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            result: list[dict[str, Any]] = []
            for m in getattr(self, "memories", []):
                if m.get("deleted_at"):
                    continue
                if layer is not None and m.get("layer") != layer:
                    continue
                if m.get("weight", 0.5) < min_weight:
                    continue
                if scope is not None and m.get("scope") != scope:
                    continue
                result.append(dict(m))
            return result

    def list_memories_by_source_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            result: list[dict[str, Any]] = []
            for m in getattr(self, "memories", []):
                ids_raw = m.get("source_trace_ids_json", "[]")
                if isinstance(ids_raw, str):
                    try:
                        ids = json.loads(ids_raw)
                    except (json.JSONDecodeError, TypeError):
                        ids = []
                else:
                    ids = ids_raw
                if trace_id in ids:
                    result.append(dict(m))
            return result

    # ── feedback signals ─────────────────────────────────────

    def insert_feedback_signal(self, signal: dict[str, Any]) -> None:
        with self._lock:
            existing = getattr(self, "feedback_signals", None)
            if existing is None:
                self.feedback_signals: list[dict[str, Any]] = []
            self.feedback_signals.append(signal)
            self._persist("insert_feedback_signal", signal)

    def list_signals_by_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(s)
                for s in getattr(self, "feedback_signals", [])
                if s.get("trace_id") == trace_id
            ]

    # ── learning suggestions ────────────────────────────────────

    def insert_suggestion(self, suggestion: dict[str, Any]) -> None:
        with self._lock:
            existing = getattr(self, "suggestions", None)
            if existing is None:
                self.suggestions: list[dict[str, Any]] = []
            sid = suggestion.get("suggestion_id", "")
            # Skip if already present (safe against re-insert)
            if sid and any(s.get("suggestion_id") == sid for s in self.suggestions):
                return
            self.suggestions.append(suggestion)
            self._persist("insert_suggestion", suggestion)

    def update_suggestion(self, suggestion_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for i, s in enumerate(getattr(self, "suggestions", [])):
                if s.get("suggestion_id") == suggestion_id:
                    next_s = dict(s)
                    next_s.update(updates)
                    self.suggestions[i] = next_s
                    self._persist("update_suggestion", suggestion_id, updates)
                    return

    def list_suggestions(self, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(s)
                for s in getattr(self, "suggestions", [])
                if s.get("confidence", 0) >= min_confidence
            ]

    def find_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        with self._lock:
            for s in getattr(self, "suggestions", []):
                if s.get("suggestion_id") == suggestion_id:
                    return dict(s)
        return None

    # ── AB experiments ──────────────────────────────────────────

    def insert_experiment(self, experiment: dict[str, Any]) -> None:
        with self._lock:
            existing = getattr(self, "experiments", None)
            if existing is None:
                self.experiments: list[dict[str, Any]] = []
            eid = experiment.get("experiment_id", "")
            if eid and any(e.get("experiment_id") == eid for e in self.experiments):
                return
            self.experiments.append(experiment)
            self._persist("insert_experiment", experiment)

    def update_experiment(self, experiment_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for i, e in enumerate(getattr(self, "experiments", [])):
                if e.get("experiment_id") == experiment_id:
                    next_e = dict(e)
                    next_e.update(updates)
                    self.experiments[i] = next_e
                    self._persist("update_experiment", experiment_id, updates)
                    return

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in getattr(self, "experiments", [])]

    def find_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._lock:
            for e in getattr(self, "experiments", []):
                if e.get("experiment_id") == experiment_id:
                    return dict(e)
        return None


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
