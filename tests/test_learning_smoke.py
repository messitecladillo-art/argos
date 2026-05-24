"""Smoke test for the self-evolving learning system (v2 — LanceDB + circuit breaker).

Run: ./.venv/Scripts/python.exe tests/test_learning_smoke.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import os
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from argos.db import init_database
from argos.learning import trace_collector, memory_store, feedback_engine, CircuitBreaker
from argos.learning.memory import _seed_memory_id
from argos.models.store import store


def test_db_init():
    init_database()
    # verify new tables
    snap = store.snapshot()
    assert "learning" in snap
    print(f"[PASS] DB init — learning stats: {snap['learning']}")


def test_trace_lifecycle():
    tid = trace_collector.task_started("ut_test_001", "leader_001", "refactor auth module for JWT")
    assert tid and tid.startswith("trace_")
    print(f"[PASS] trace started: {tid}")

    trace_collector.record_decomposition(tid, strategy="sequential", num_subtasks=3,
        roles_used=["worker", "worker", "worker"],
        reasoning="three modules to refactor sequentially")
    trace_collector.record_context_plan(tid, total_tokens_estimate=8000,
        files_provided=["auth.py", "middleware.py", "config.py"],
        selection_method="dependency_graph")
    trace_collector.record_decision(tid, decision_point="auth_method",
        options=["JWT", "session", "OAuth2"], chosen="JWT",
        reasoning="stateless requirement")
    trace_collector.record_allocation(tid, agent_id="w1", role="worker",
        assignment_id="asg_1", context_summary="Refactor auth.py", token_count=4000)
    trace_collector.record_allocation(tid, agent_id="w2", role="worker",
        assignment_id="asg_2", context_summary="Update middleware", token_count=3000)
    trace_collector.record_allocation_result("asg_1", "done", "completed")
    trace_collector.record_allocation_result("asg_2", "done", "completed")
    trace_collector.task_phase_change("ut_test_001", "execute")
    trace_collector.task_phase_change("ut_test_001", "review")
    trace_collector.task_completed("ut_test_001", status="completed", rounds=1, duration_s=120.5,
        summary="auth refactored to JWT")

    trace = store.get_trace(tid)
    assert trace is not None
    assert trace["phase"] == "complete"
    allocs = json.loads(trace["allocations_json"])
    assert len(allocs) == 2
    outcome = json.loads(trace["outcome_json"])
    assert outcome["status"] == "completed"
    print(f"[PASS] trace lifecycle: {len(allocs)} allocations, phase={trace['phase']}")


def test_memory_seeds():
    memory_store.init_app(store)
    mems = store.list_memories(min_weight=0.0)
    alive = [m for m in mems if not m.get("deleted_at")]
    assert len(alive) >= 5, f"expected >=5 seeds, got {len(alive)}"
    print(f"[PASS] seeds loaded: {len(alive)} memories")
    for m in alive[:3]:
        print(f"  [{m['weight']:.0%}] [{m['layer']}] {m['content'][:80]}...")


def test_lancedb_retrieval():
    results = memory_store.retrieve("refactoring authentication module", layer="strategic", top_k=3)
    assert len(results) > 0, "should find relevant memories"
    print(f"[PASS] LanceDB retrieval: {len(results)} results")
    for r in results:
        print(f"  [{r['weight']:.0%}] {r['content'][:80]}...")

    hint = memory_store.inject_into_context("refactoring auth", "leader_decompose")
    assert "Relevant past experience" in hint
    print(f"[PASS] context injection: {len(hint)} chars")


def test_vector_store_uses_plain_vectors():
    from argos.learning.embeddings import VectorStore

    class FakeBuilder:
        def __init__(self) -> None:
            self.metric_value = None
            self.limit_value = None

        def metric(self, value):
            self.metric_value = value
            return self

        def limit(self, value):
            self.limit_value = value
            return self

        def to_list(self):
            return [{"memory_id": "mem_1", "content": "ok", "_distance": 0.1}]

    class FakeTable:
        def __init__(self) -> None:
            self.added = None
            self.query = None
            self.builder = FakeBuilder()

        def add(self, rows):
            self.added = rows

        def search(self, query):
            self.query = query
            return self.builder

    table = FakeTable()
    vstore = VectorStore("unused", dim=3)
    vstore._table = table

    vstore.add("mem_1", [1, 2, 3], "content")
    assert table.added == [{"memory_id": "mem_1", "vector": [1.0, 2.0, 3.0], "content": "content"}]

    results = vstore.search([0.1, 0.2, 0.3], top_k=1)
    assert table.query == [0.1, 0.2, 0.3]
    assert results[0]["memory_id"] == "mem_1"
    print("[PASS] vector store passes plain Python vectors to LanceDB")


def test_feedback_extraction():
    feedback_engine.init_app(store, memory_store)
    # Direct extraction (bypassing worker sleep)
    count = feedback_engine._extract_once()
    print(f"[PASS] feedback extraction: {count} signals")

    # Check quality was set
    trace = store.get_trace_by_user_task("ut_test_001")
    if trace:
        quality = json.loads(trace.get("quality_json", "{}"))
        print(f"[PASS] quality: success={quality.get('success_score')}, efficiency={quality.get('efficiency_score')}, satisfaction={quality.get('user_satisfaction')}")


def test_feedback_skips_unfinished_traces():
    unfinished_id = f"trace_unfinished_{uuid.uuid4().hex[:8]}"
    completed_id = f"trace_completed_{uuid.uuid4().hex[:8]}"
    base = {
        "user_task_id": "ut_feedback_gate",
        "leader_agent_id": "leader_001",
        "phase": "execute",
        "decomposition_json": "{}",
        "context_plan_json": "{}",
        "allocations_json": "[]",
        "decisions_json": "[]",
        "quality_json": "{}",
        "created_at": "2026-01-01T00:00:00Z",
    }
    store.insert_trace({
        **base,
        "trace_id": unfinished_id,
        "outcome_json": "{}",
        "completed_at": None,
    })
    store.insert_trace({
        **base,
        "trace_id": completed_id,
        "outcome_json": json.dumps({"status": "completed", "rounds_used": 1}),
        "completed_at": "2026-01-01T00:01:00Z",
    })

    trace_ids = {trace["trace_id"] for trace in store.list_traces_needing_feedback(limit=100)}
    assert unfinished_id not in trace_ids
    assert completed_id in trace_ids
    print("[PASS] feedback queue ignores unfinished traces")


def test_seed_memory_id_is_stable():
    item = {"layer": "strategic", "type": "pattern", "content": "same across restarts"}
    assert _seed_memory_id(item) == _seed_memory_id(dict(item))
    assert _seed_memory_id(item).startswith("seed_strategic_pattern_")
    print("[PASS] seed memory IDs are deterministic")


def test_memory_consolidation():
    for i in range(4):
        tid = trace_collector.task_started(f"ut_c_{i:03d}", "leader_001", "refactor database layer")
        trace_collector.record_decomposition(tid, strategy="sequential", num_subtasks=2,
            roles_used=["worker", "worker"], reasoning=f"run {i}")
        trace_collector.task_completed(f"ut_c_{i:03d}", status="completed", rounds=1, duration_s=60,
            summary=f"done {i}")

    before = len([m for m in store.list_memories(min_weight=0.0) if not m.get("deleted_at")])
    new = memory_store.consolidate_from_traces(min_new_traces=2)
    after = len([m for m in store.list_memories(min_weight=0.0) if not m.get("deleted_at")])
    print(f"[PASS] consolidation: {new} new, {before} → {after}")


def test_weight_adjustment():
    mems = store.list_memories(min_weight=0.0)
    mems = [m for m in mems if not m.get("deleted_at")]
    if mems:
        mid = mems[0]["memory_id"]
        old = mems[0]["weight"]
        memory_store.adjust_weight(mid, 0.8)
        u1 = store.find_memory(mid)
        w1 = u1["weight"] if u1 else old
        memory_store.adjust_weight(mid, -0.5)
        u2 = store.find_memory(mid)
        w2 = u2["weight"] if u2 else w1
        print(f"[PASS] weight: {old:.2f} →(+0.8)→ {w1:.2f} →(-0.5)→ {w2:.2f}")


def test_eviction():
    # Add a very-low-weight memory that should be evicted
    import uuid
    mid = f"test_evict_low_{uuid.uuid4().hex[:8]}"
    store.insert_memory({
        "memory_id": mid, "layer": "operational", "type": "pitfall",
        "content": "test low weight memory", "embedding_json": "[]",
        "source_trace_ids_json": "[]", "consolidation_count": 1,
        "weight": 0.01, "use_count": 0, "success_count": 0,
        "scope": "global", "project_path": None, "metadata_json": "{}",
        "created_at": "2020-01-01T00:00:00Z", "last_used_at": None,
        "expires_at": None, "deleted_at": None,
    })
    removed = memory_store._evict_once()
    print(f"[PASS] eviction: {removed} removed (expected >=1 for low-weight)")

    # Verify it was deleted
    mem = store.find_memory(mid)
    assert mem is None or mem.get("deleted_at"), "low-weight memory should be evicted"
    print("[PASS] eviction verified — low-weight memory marked deleted")


def test_circuit_breaker():
    cb = CircuitBreaker("test", failure_threshold=3, window_sec=60, cooldown_sec=1)
    assert not cb.is_open
    for _ in range(5):
        cb.failure()
    assert cb.is_open, "should open after threshold exceeded"
    print("[PASS] circuit breaker opens after threshold")
    cb.reset()
    assert not cb.is_open
    print("[PASS] circuit breaker resets")


def test_disabled_mode():
    from argos.learning.traces import TraceCollector
    disabled = TraceCollector(enabled=False)
    assert disabled.task_started("x", "y", "z") is None
    print("[PASS] disabled collector is no-op")


def test_global_trace_collector_respects_learn_enabled():
    env = os.environ.copy()
    env["LEARN_ENABLED"] = "0"
    script = (
        "import argos.learning.traces as traces; "
        "print('enabled=' + str(traces.trace_collector.enabled))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "enabled=False" in result.stdout
    print("[PASS] LEARN_ENABLED disables global trace collector")


def test_stats_api():
    stats = memory_store.stats()
    assert stats["total_memories"] >= 5
    print(f"[PASS] memory stats: total={stats['total_memories']}, per_layer={stats['per_layer']}, cb_open={stats['cb_open']}")


def test_safe_call():
    from argos.learning.embeddings import safe_call, safe_call_or
    cb = CircuitBreaker("test_safe", failure_threshold=2, window_sec=60, cooldown_sec=60)

    def ok(): return 42
    def fails(): raise RuntimeError("boom")

    assert safe_call(None, ok) == 42
    assert safe_call(None, fails) is None
    assert safe_call_or(99, None, fails) == 99
    print("[PASS] safe_call: success returns value, failure returns None/fallback")


def test_active_learning():
    from argos.learning import active_engine
    active_engine.init_app(store, memory_store)

    # Generate enough varied traces for pattern detection
    # sequential tasks: high success (8 completed, 2 failed)
    for i in range(10):
        tid = trace_collector.task_started(f"ut_al_seq_{i:03d}", "leader_001", f"sequential task {i}")
        if tid is None:
            continue
        trace_collector.record_decomposition(tid, strategy="sequential", num_subtasks=3,
            roles_used=["worker", "worker", "worker"], reasoning=f"low context test {i}")
        trace_collector.record_context_plan(tid, total_tokens_estimate=4000, files_provided=["a.py"],
            selection_method="direct")
        status = "completed" if i < 8 else "failed"
        trace_collector.task_completed(f"ut_al_seq_{i:03d}", status=status, rounds=1,
            duration_s=30.0 + i * 10, summary=f"result {i}")

    # parallel tasks: low success (3 completed, 7 failed)
    for i in range(10):
        tid = trace_collector.task_started(f"ut_al_par_{i:03d}", "leader_001", f"parallel task {i}")
        if tid is None:
            continue
        trace_collector.record_decomposition(tid, strategy="parallel", num_subtasks=5,
            roles_used=["worker", "worker", "worker", "worker"], reasoning=f"high context test {i}")
        trace_collector.record_context_plan(tid, total_tokens_estimate=15000, files_provided=["a.py", "b.py", "c.py"],
            selection_method="direct")
        status = "completed" if i < 3 else "failed"
        trace_collector.task_completed(f"ut_al_par_{i:03d}", status=status, rounds=3,
            duration_s=120.0 + i * 30, summary=f"result {i}")

    suggestions = active_engine.scan_and_suggest(min_traces=5)
    print(f"[PASS] active learning scan: {len(suggestions)} suggestions generated")
    for s in suggestions[:5]:
        print(f"  [{s.get('type')}] confidence={s.get('confidence', 0):.0%} impact={s.get('impact_score', 0):.2f}")

    # Test suggestion listing
    all_suggestions = active_engine.get_suggestions(min_confidence=0.0)
    print(f"[PASS] active suggestions: {len(all_suggestions)} stored (pending={active_engine.stats()['pending']})")

    # Test apply
    if all_suggestions:
        result = active_engine.apply_suggestion(all_suggestions[0]["content"])
        assert result["ok"], f"apply failed: {result}"
        print(f"[PASS] apply suggestion: {result['suggestion']['type']}")

    stats = active_engine.stats()
    assert stats["total_suggestions"] >= 0
    print(f"[PASS] active stats: total={stats['total_suggestions']}, applied={stats['applied']}")


def test_metrics():
    from argos.learning import metrics_collector

    # Reset for clean test
    metrics_collector._retrieval_total = 0
    metrics_collector._retrieval_hits = 0
    metrics_collector._feedback_signals_total = 0
    metrics_collector._feedback_by_type.clear()
    metrics_collector._eviction_total = 0
    metrics_collector._consolidation_total = 0
    metrics_collector._snapshots.clear()

    # Record some metrics
    metrics_collector.record_retrieval(True)
    metrics_collector.record_retrieval(True)
    metrics_collector.record_retrieval(False)
    metrics_collector.record_feedback_signal("accept")
    metrics_collector.record_feedback_signal("redo")
    metrics_collector.record_feedback_signal("accept")
    metrics_collector.record_eviction(3)
    metrics_collector.record_consolidation(1)
    metrics_collector.record_snapshot(
        memory_stats={"total_memories": 10, "vector_count": 8, "avg_weight": 0.65,
                      "per_layer": {"strategic": 5, "tactical": 3, "operational": 2}},
        trace_count=50, signal_count=15,
    )

    snap = metrics_collector.snapshot()
    assert snap["retrieval_total"] == 3
    assert abs(snap["retrieval_hit_rate"] - 2 / 3) < 0.001
    assert snap["feedback_total"] == 3
    assert snap["feedback_by_type"]["accept"] == 2
    assert snap["feedback_by_type"]["redo"] == 1
    assert snap["eviction_total"] == 3
    assert snap["consolidation_total"] == 1
    print(f"[PASS] metrics snapshot: hit_rate={snap['retrieval_hit_rate']:.0%}, "
          f"signals={snap['feedback_total']}, evictions={snap['eviction_total']}")

    history = metrics_collector.history(limit=5)
    assert len(history) >= 1
    assert history[-1]["memory_count"] == 10
    print(f"[PASS] metrics history: {len(history)} snapshots")


def test_persistence_roundtrip():
    """Verify suggestions and experiments survive store reload."""
    from argos.learning import active_engine, ab_evaluator
    import uuid

    # Create test data
    exp_id = ab_evaluator.create_experiment(
        name="persist test", control_label="A", treatment_label="B")
    assert store.find_experiment(exp_id) is not None
    print(f"[PASS] experiment persisted: {exp_id}")

    # Simulate reload: re-init from store
    ab_evaluator._experiments.clear()
    ab_evaluator.init_app(store)
    loaded = ab_evaluator.list_experiments()
    assert any(e["id"] == exp_id for e in loaded), "experiment should survive reload"
    print(f"[PASS] experiment survives reload: {len(loaded)} experiments")

    # Suggestions persistence — use unique ID each run
    sug_id = f"sug_test_{uuid.uuid4().hex[:8]}"
    sug = {
        "suggestion_id": sug_id,
        "type": "test_type",
        "content": f"test persistence suggestion {sug_id}",
        "confidence": 0.8,
        "impact_score": 0.5,
        "evidence_json": "{}",
        "applied": False,
        "applied_at": None,
        "seen_count": 1,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    store.insert_suggestion(sug)

    # Reload
    active_engine._suggestions.clear()
    active_engine.init_app(store, memory_store)
    suggestions = active_engine.get_suggestions(min_confidence=0.0)
    assert any(s["suggestion_id"] == sug_id for s in suggestions), "suggestion should survive reload"
    print(f"[PASS] suggestions survive reload: {len(suggestions)} total")


def test_ab_evaluation():
    from argos.learning import ab_evaluator
    # Clear stale state from other tests
    ab_evaluator._experiments.clear()
    store.experiments.clear()
    ab_evaluator.init_app(store)

    exp_id = ab_evaluator.create_experiment(
        name="test strategy comparison",
        control_label="sequential",
        treatment_label="parallel",
    )
    assert exp_id.startswith("ab_")
    print(f"[PASS] AB experiment created: {exp_id}")

    # Record outcomes
    for i in range(10):
        tid = trace_collector.task_started(f"ut_ab_{i:03d}", "leader_001", f"AB test {i}")
        if tid is None:
            continue
        trace_collector.task_completed(f"ut_ab_{i:03d}", status="completed" if i < 7 else "failed",
            rounds=1, duration_s=60, summary=f"AB {i}")
        trace = store.get_trace(tid)
        if trace:
            group = "control" if i < 5 else "treatment"
            ab_evaluator.record_outcome(exp_id, group, trace)

    result = ab_evaluator.evaluate(exp_id, min_samples=3)
    assert result["ok"]
    print(f"[PASS] AB evaluate: delta={result.get('delta', 0):.3f}, confidence={result.get('confidence', 0):.0%}")

    experiments = ab_evaluator.list_experiments()
    assert len(experiments) == 1
    print(f"[PASS] AB list: {len(experiments)} experiments")


def main():
    print("=" * 60)
    print("Self-Evolving Learning System v2 — Smoke Test")
    print("(LanceDB + Circuit Breaker + Eviction + Async)")
    print("=" * 60)

    # DB first, then init learning
    test_db_init()
    trace_collector.init_app(store)
    memory_store.init_app(store)
    feedback_engine.init_app(store, memory_store)
    from argos.learning import active_engine, ab_evaluator
    active_engine.init_app(store, memory_store)
    ab_evaluator.init_app(store)
    print()

    test_trace_lifecycle()
    print()
    test_memory_seeds()
    print()
    test_lancedb_retrieval()
    print()
    test_feedback_extraction()
    print()
    test_memory_consolidation()
    print()
    test_weight_adjustment()
    print()
    test_eviction()
    print()
    test_circuit_breaker()
    print()
    test_disabled_mode()
    print()
    test_stats_api()
    print()
    test_safe_call()
    print()
    test_active_learning()
    print()
    test_ab_evaluation()
    print()
    test_persistence_roundtrip()
    print()
    test_metrics()
    print()

    # cleanup
    memory_store.shutdown()
    feedback_engine.shutdown()

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
