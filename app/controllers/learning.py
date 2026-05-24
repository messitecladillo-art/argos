"""REST API for the self-evolving learning system."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..learning import active_engine, ab_evaluator, feedback_engine, memory_store, metrics_collector, trace_collector
from ..models.store import store

bp = Blueprint("learning", __name__, url_prefix="/api/learning")


@bp.get("/stats")
def get_stats():
    """Get learning system statistics."""
    snap = store.snapshot()
    mem_stats = memory_store.stats() if memory_store._initialized else {}
    return jsonify({
        "ok": True,
        "enabled": trace_collector.enabled,
        "traces": snap.get("learning", {}),
        "memory": mem_stats,
    })


@bp.get("/memories")
def list_memories():
    """List all memories with optional filters."""
    layer = request.args.get("layer")
    min_weight = float(request.args.get("min_weight", "0.0"))
    limit = int(request.args.get("limit", "20"))

    memories = store.list_memories(layer=layer, min_weight=min_weight)
    memories.sort(key=lambda m: m.get("weight", 0.5), reverse=True)
    memories = memories[:limit]

    return jsonify({
        "ok": True,
        "count": len(memories),
        "memories": [
            {
                "memory_id": m["memory_id"],
                "layer": m["layer"],
                "type": m["type"],
                "content": m["content"][:200],
                "weight": m["weight"],
                "use_count": m.get("use_count", 0),
                "success_count": m.get("success_count", 0),
                "scope": m.get("scope", ""),
                "created_at": m.get("created_at", ""),
                "last_used_at": m.get("last_used_at"),
                "consolidation_count": m.get("consolidation_count", 1),
            }
            for m in memories
        ],
    })


@bp.post("/memories/<memory_id>/forget")
def forget_memory(memory_id: str):
    """Manually delete a memory."""
    from ..config import now_iso
    mem = store.find_memory(memory_id)
    if mem is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    store.update_memory(memory_id, {"deleted_at": now_iso()})
    return jsonify({"ok": True, "message": "memory marked deleted"})


@bp.post("/traces/<trace_id>/feedback")
def record_explicit_feedback(trace_id: str):
    """Record explicit user feedback for a trace."""
    payload = request.get_json(silent=True) or {}
    rating = int(payload.get("rating", 0))
    if rating < 1 or rating > 5:
        return jsonify({"ok": False, "error": "rating must be 1-5"}), 400
    signal = feedback_engine.record_explicit(trace_id, payload.get("assignment_id"), rating)
    return jsonify({"ok": True, "signal": signal})


@bp.get("/traces")
def list_traces():
    """List recent execution traces."""
    limit = int(request.args.get("limit", "10"))
    traces = getattr(store, "traces", [])[-limit:]
    return jsonify({
        "ok": True,
        "count": len(traces),
        "traces": [
            {
                "trace_id": t.get("trace_id"),
                "user_task_id": t.get("user_task_id"),
                "phase": t.get("phase"),
                "quality_json": t.get("quality_json", "{}"),
                "completed_at": t.get("completed_at"),
            }
            for t in reversed(traces)
        ],
    })


@bp.post("/admin/consolidate")
def trigger_consolidation():
    """Manually trigger memory consolidation."""
    count = memory_store.consolidate_from_traces()
    return jsonify({"ok": True, "new_memories": count})


@bp.post("/admin/evict")
def trigger_eviction():
    """Manually trigger memory eviction."""
    count = memory_store._evict_once()
    return jsonify({"ok": True, "removed": count})


# ── Active Learning endpoints ────────────────────────────────

@bp.post("/active/scan")
def trigger_active_scan():
    """Manually trigger active learning scan for improvement suggestions."""
    min_traces = int(request.args.get("min_traces", "20"))
    suggestions = active_engine.scan_and_suggest(min_traces=min_traces)
    return jsonify({
        "ok": True,
        "count": len(suggestions),
        "suggestions": [
            {
                "type": s["type"],
                "content": s["content"],
                "confidence": s.get("confidence", 0),
                "impact_score": s.get("impact_score", 0),
            }
            for s in suggestions
        ],
    })


@bp.get("/active/suggestions")
def list_suggestions():
    """List current improvement suggestions."""
    min_confidence = float(request.args.get("min_confidence", "0.6"))
    suggestions = active_engine.get_suggestions(min_confidence=min_confidence)
    return jsonify({
        "ok": True,
        "count": len(suggestions),
        "suggestions": [
            {
                "type": s["type"],
                "content": s["content"],
                "confidence": s.get("confidence", 0),
                "impact_score": s.get("impact_score", 0),
                "applied": s.get("applied", False),
                "applied_at": s.get("applied_at"),
                "seen_count": s.get("seen_count", 1),
            }
            for s in suggestions
        ],
    })


@bp.post("/active/suggestions/<suggestion_id>/apply")
def apply_suggestion(suggestion_id: str):
    """Apply an improvement suggestion by suggestion_id, type, content, or index."""
    suggestions = active_engine.get_suggestions(min_confidence=0.0)
    # Priority: exact suggestion_id match, then index lookup, then pass-through
    matched = any(s.get("suggestion_id") == suggestion_id for s in suggestions)
    if not matched:
        try:
            idx = int(suggestion_id)
            if 0 <= idx < len(suggestions):
                suggestion_id = suggestions[idx]["type"]
        except ValueError:
            pass  # not an index, pass through as type/content
    result = active_engine.apply_suggestion(suggestion_id)
    if result["ok"]:
        return jsonify(result)
    return jsonify(result), 404


@bp.get("/active/stats")
def active_stats():
    """Get active learning statistics."""
    return jsonify({"ok": True, **active_engine.stats()})


# ── A/B Evaluation endpoints ─────────────────────────────────

@bp.post("/ab/experiments")
def create_experiment():
    """Create a new A/B experiment."""
    payload = request.get_json(silent=True) or {}
    name = payload.get("name", "")
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    exp_id = ab_evaluator.create_experiment(
        name=name,
        control_label=payload.get("control_label", "control"),
        treatment_label=payload.get("treatment_label", "treatment"),
        filter_expr=payload.get("filter_expr"),
    )
    return jsonify({"ok": True, "experiment_id": exp_id})


@bp.get("/ab/experiments")
def list_experiments():
    """List all A/B experiments."""
    experiments = ab_evaluator.list_experiments()
    return jsonify({"ok": True, "count": len(experiments), "experiments": experiments})


@bp.get("/ab/experiments/<experiment_id>")
def evaluate_experiment(experiment_id: str):
    """Evaluate an A/B experiment."""
    min_samples = int(request.args.get("min_samples", "10"))
    result = ab_evaluator.evaluate(experiment_id, min_samples=min_samples)
    if not result["ok"]:
        return jsonify(result), 404
    return jsonify(result)


@bp.post("/ab/experiments/<experiment_id>/record")
def record_experiment_outcome(experiment_id: str):
    """Record an outcome for an A/B experiment group."""
    payload = request.get_json(silent=True) or {}
    group = payload.get("group", "")
    trace_id = payload.get("trace_id", "")
    if not group or not trace_id:
        return jsonify({"ok": False, "error": "group and trace_id required"}), 400
    trace = store.get_trace(trace_id)
    if trace is None:
        return jsonify({"ok": False, "error": "trace not found"}), 404
    ab_evaluator.record_outcome(experiment_id, group, trace)
    return jsonify({"ok": True})


# ── Metrics / Observability endpoints ───────────────────────

@bp.get("/metrics")
def get_metrics_snapshot():
    """Get current metrics snapshot (retrieval rate, feedback distribution, etc.)."""
    return jsonify({"ok": True, **metrics_collector.snapshot()})


@bp.get("/metrics/history")
def get_metrics_history():
    """Get time-series metrics history."""
    limit = int(request.args.get("limit", "24"))
    history = metrics_collector.history(limit=limit)
    return jsonify({"ok": True, "count": len(history), "snapshots": history})


@bp.get("/system")
def get_system_dashboard():
    """Aggregated dashboard of the entire learning system."""
    mem_stats = memory_store.stats() if memory_store._initialized else {}
    active_stats = active_engine.stats()
    ab_experiments = ab_evaluator.list_experiments()
    met_snapshot = metrics_collector.snapshot()
    snap = store.snapshot()

    return jsonify({
        "ok": True,
        "enabled": trace_collector.enabled,
        "memory": {
            "total": mem_stats.get("total_memories", 0),
            "vector_count": mem_stats.get("vector_count", 0),
            "per_layer": mem_stats.get("per_layer", {}),
            "avg_weight": mem_stats.get("avg_weight", 0),
            "cb_open": mem_stats.get("cb_open", False),
            "provider_dim": mem_stats.get("provider_dim", 0),
        },
        "traces": snap.get("learning", {}),
        "feedback": {
            "total_signals": met_snapshot.get("feedback_total", 0),
            "by_type": met_snapshot.get("feedback_by_type", {}),
        },
        "active_learning": active_stats,
        "ab_experiments": {
            "total": len(ab_experiments),
            "active": sum(1 for e in ab_experiments if not e["concluded"]),
            "concluded": sum(1 for e in ab_experiments if e["concluded"]),
        },
        "retrieval": {
            "hit_rate": met_snapshot.get("retrieval_hit_rate", 0),
            "total": met_snapshot.get("retrieval_total", 0),
        },
        "eviction_total": met_snapshot.get("eviction_total", 0),
        "consolidation_total": met_snapshot.get("consolidation_total", 0),
    })
