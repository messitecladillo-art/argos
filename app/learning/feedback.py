"""Feedback engine — async background extraction + signal-to-memory propagation."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from ..config import now_iso
from . import config as cfg
from .embeddings import CircuitBreaker, safe_call, safe_call_or
from .metrics import metrics_collector
from .traces import _new_id


class FeedbackEngine:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and cfg.ENABLED
        self._store: Any = None
        self._memory_store: Any = None
        self._cb = CircuitBreaker("feedback", cfg.CB_FAILURE_THRESHOLD, cfg.CB_WINDOW_SEC, cfg.CB_COOLDOWN_SEC)
        self._worker_thread: threading.Thread | None = None
        self._stop_worker = threading.Event()

    def init_app(self, store: Any, memory_store: Any = None) -> None:
        self._store = store
        self._memory_store = memory_store
        self._start_worker()

    def shutdown(self) -> None:
        self._stop_worker.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

    # ── background worker ────────────────────────────────────

    def _start_worker(self) -> None:
        if not self.enabled:
            return
        if self._worker_thread and self._worker_thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop_worker.wait(cfg.FEEDBACK_INTERVAL_SEC):
                safe_call(self._cb, self._extract_once)
                # also trigger consolidation on a longer cycle
                if self._memory_store and _should_consolidate():
                    safe_call(None, lambda: self._memory_store.consolidate_from_traces())
                # trigger active learning scan on an even longer cycle
                if _should_active_scan():
                    from .active import active_engine
                    safe_call(None, lambda: active_engine.scan_and_suggest())
                # record time-series metrics snapshot
                _record_metrics_snapshot()

        self._worker_thread = threading.Thread(target=_loop, daemon=True)
        self._worker_thread.start()

    def _extract_once(self) -> int:
        if self._store is None:
            return 0
        traces = self._store.list_traces_needing_feedback(limit=20)
        if len(traces) < cfg.FEEDBACK_MIN_TRACES:
            return 0
        count = 0
        for trace in traces:
            signals = self._analyze_trace(trace)
            for sig in signals:
                metrics_collector.record_feedback_signal(sig["signal_type"])
                safe_call(None, lambda s=sig: self._store.insert_feedback_signal(s))
                if self._memory_store is not None:
                    linked = safe_call_or([], None,
                        lambda t=trace: self._store.list_memories_by_source_trace(t.get("trace_id", "")))
                    for mem in linked:
                        self._memory_store.adjust_weight(mem["memory_id"], sig["strength"])
                count += 1
            safe_call(None, lambda t=trace: self._compute_quality(t))
        if count > 0:
            metrics_collector.record_feedback_signal("batch")
        return count

    # ── signal extraction ────────────────────────────────────

    def _analyze_trace(self, trace: dict[str, Any]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        trace_id = trace.get("trace_id", "")
        outcome = _parse_json(trace.get("outcome_json"), {})

        status = outcome.get("status", "unknown")
        if status == "completed":
            signals.append(self._make_signal(trace_id, None, "accept", 0.6))
        elif status == "failed":
            signals.append(self._make_signal(trace_id, None, "redo", -0.8))
        elif status == "blocked":
            signals.append(self._make_signal(trace_id, None, "hesitate", -0.4))

        rounds = outcome.get("rounds_used", 1)
        max_rounds = 10
        if rounds == 1:
            signals.append(self._make_signal(trace_id, None, "accept", 0.3))
        elif rounds > max_rounds * 0.7:
            signals.append(self._make_signal(trace_id, None, "hesitate", -0.3))

        # check for re-assignments (worker failed, re-assigned)
        allocations = _parse_json(trace.get("allocations_json"), [])
        for alloc in allocations:
            if alloc.get("subsequent_redo") or alloc.get("status") == "failed":
                signals.append(self._make_signal(
                    trace_id, alloc.get("assignment_id"), "redo", -0.5,
                    detail={"reason": "worker_failed_or_reassigned"},
                ))

        # duration-based: very fast completion = too easy, very slow = inefficient
        duration = outcome.get("total_duration_seconds", 0)
        if duration > 600:  # >10 min
            signals.append(self._make_signal(trace_id, None, "hesitate", -0.2, detail={"duration_s": duration}))

        return signals

    def record_explicit(self, trace_id: str, assignment_id: str | None, rating: int) -> dict[str, Any]:
        strength_map = {1: -1.0, 2: -0.5, 3: 0.0, 4: 0.5, 5: 1.0}
        strength = strength_map.get(rating, 0.0)
        signal = self._make_signal(trace_id, assignment_id, "explicit", strength, detail={"rating": rating})
        safe_call(None, lambda: self._store.insert_feedback_signal(signal) if self._store else None)
        return signal

    # ── helpers ──────────────────────────────────────────────

    def _make_signal(self, trace_id: str, assignment_id: str | None, signal_type: str,
                     strength: float, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "signal_id": _new_id("sig"),
            "trace_id": trace_id,
            "assignment_id": assignment_id,
            "signal_type": signal_type,
            "strength": max(-1.0, min(1.0, strength)),
            "detail_json": json.dumps(detail or {}, ensure_ascii=False),
            "extracted_at": now_iso(),
        }

    def _compute_quality(self, trace: dict[str, Any]) -> None:
        trace_id = trace.get("trace_id", "")
        signals = safe_call_or([], None,
                               lambda: self._store.list_signals_by_trace(trace_id) if self._store else [])
        if not signals:
            return
        strengths = [s.get("strength", 0) for s in signals]
        pos = [s for s in strengths if s > 0]
        neg = [abs(s) for s in strengths if s < 0]
        success = sum(pos) / (len(pos) + 1) if pos else 0.5
        efficiency = 1.0 - (sum(neg) / (len(neg) + 1)) if neg else 0.7
        satisfaction = (sum(strengths) / len(strengths) + 1) / 2

        from .traces import trace_collector
        safe_call(None, lambda: trace_collector.set_quality(
            trace_id, round(success, 3), round(efficiency, 3), round(satisfaction, 3)))


def _parse_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


_last_consolidation = 0.0
_consolidation_lock = threading.Lock()


def _should_consolidate() -> bool:
    global _last_consolidation
    with _consolidation_lock:
        now = time.monotonic()
        if now - _last_consolidation > cfg.CONSOLIDATION_INTERVAL_SEC:
            _last_consolidation = now
            return True
        return False


_last_active_scan = 0.0
_active_scan_lock = threading.Lock()


def _should_active_scan() -> bool:
    global _last_active_scan
    with _active_scan_lock:
        now = time.monotonic()
        # scan roughly every 2 hours (or 2x consolidation interval)
        interval = cfg.CONSOLIDATION_INTERVAL_SEC * 2
        if now - _last_active_scan > interval:
            _last_active_scan = now
            return True
        return False


_last_metrics_snapshot = 0.0
_metrics_snapshot_lock = threading.Lock()


def _record_metrics_snapshot() -> None:
    global _last_metrics_snapshot
    with _metrics_snapshot_lock:
        now = time.monotonic()
        # snapshot every 10 minutes
        if now - _last_metrics_snapshot < 600:
            return
        _last_metrics_snapshot = now

    from ..models.store import store as _store
    from .memory import memory_store as _ms
    mem_stats = safe_call_or({}, None, lambda: _ms.stats())
    trace_count = len(getattr(_store, "traces", []))
    signal_count = len(getattr(_store, "feedback_signals", []))
    metrics_collector.record_snapshot(
        memory_stats=mem_stats,
        trace_count=trace_count,
        signal_count=signal_count,
    )


feedback_engine = FeedbackEngine(enabled=cfg.ENABLED)
