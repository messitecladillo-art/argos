"""Time-series metrics collector for the self-evolving learning system."""

from __future__ import annotations

import threading
from typing import Any

from ..config import now_iso
from . import config as cfg
from .embeddings import safe_call


class MetricsCollector:
    """Ring-buffer time-series metrics with configurable retention."""

    def __init__(self, max_snapshots: int = 168) -> None:
        self._max = max_snapshots
        self._snapshots: list[dict[str, Any]] = []
        self._lock = threading.Lock()

        # Counters
        self._retrieval_total = 0
        self._retrieval_hits = 0
        self._feedback_signals_total = 0
        self._feedback_by_type: dict[str, int] = {}
        self._eviction_total = 0
        self._consolidation_total = 0

    def record_snapshot(self, memory_stats: dict[str, Any] | None = None,
                        trace_count: int = 0, signal_count: int = 0) -> None:
        with self._lock:
            snap = {
                "ts": now_iso(),
                "memory_count": memory_stats.get("total_memories", 0) if memory_stats else 0,
                "vector_count": memory_stats.get("vector_count", 0) if memory_stats else 0,
                "trace_count": trace_count,
                "signal_count": signal_count,
                "retrieval_hit_rate": self._retrieval_hits / max(self._retrieval_total, 1),
                "retrieval_total": self._retrieval_total,
                "feedback_total": self._feedback_signals_total,
                "feedback_by_type": dict(self._feedback_by_type),
                "eviction_total": self._eviction_total,
                "consolidation_total": self._consolidation_total,
                "avg_weight": memory_stats.get("avg_weight", 0) if memory_stats else 0,
                "per_layer": memory_stats.get("per_layer", {}) if memory_stats else {},
            }
            self._snapshots.append(snap)
            if len(self._snapshots) > self._max:
                self._snapshots = self._snapshots[-self._max:]

    def record_retrieval(self, hit: bool) -> None:
        with self._lock:
            self._retrieval_total += 1
            if hit:
                self._retrieval_hits += 1

    def record_feedback_signal(self, signal_type: str) -> None:
        with self._lock:
            self._feedback_signals_total += 1
            self._feedback_by_type[signal_type] = self._feedback_by_type.get(signal_type, 0) + 1

    def record_eviction(self, count: int) -> None:
        with self._lock:
            self._eviction_total += count

    def record_consolidation(self, count: int) -> None:
        with self._lock:
            self._consolidation_total += count

    def history(self, limit: int = 24) -> list[dict[str, Any]]:
        with self._lock:
            return self._snapshots[-limit:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            last = self._snapshots[-1] if self._snapshots else {}
            hit_rate = self._retrieval_hits / max(self._retrieval_total, 1)
            return {
                "retrieval_hit_rate": round(hit_rate, 3),
                "retrieval_total": self._retrieval_total,
                "feedback_total": self._feedback_signals_total,
                "feedback_by_type": dict(self._feedback_by_type),
                "eviction_total": self._eviction_total,
                "consolidation_total": self._consolidation_total,
                "last_snapshot_ts": last.get("ts"),
                "snapshot_count": len(self._snapshots),
            }


metrics_collector = MetricsCollector()
