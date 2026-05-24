"""Active learning engine — discovers patterns and suggests improvements."""

from __future__ import annotations

import json
import math
import threading
from typing import Any

from ..config import now_iso
from . import config as cfg
from .embeddings import CircuitBreaker, safe_call, safe_call_or
from .traces import _new_id


class ActiveLearningEngine:
    """Scans execution traces for statistically significant patterns
    and generates ranked, actionable improvement suggestions.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and cfg.ENABLED
        self._store: Any = None
        self._memory_store: Any = None
        self._cb = CircuitBreaker("active_learn", cfg.CB_FAILURE_THRESHOLD, cfg.CB_WINDOW_SEC, cfg.CB_COOLDOWN_SEC)
        self._suggestions: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def init_app(self, store: Any, memory_store: Any = None) -> None:
        self._store = store
        self._memory_store = memory_store
        # Load persisted suggestions
        try:
            loaded = store.list_suggestions(min_confidence=0.0)
            with self._lock:
                self._suggestions = loaded
        except Exception:
            pass

    # ── main entry ───────────────────────────────────────────

    def scan_and_suggest(self, min_traces: int = 20) -> list[dict[str, Any]]:
        """Scan all traces for actionable patterns. Returns ranked suggestions."""
        if not self.enabled or self._store is None:
            return []

        def _do() -> list[dict[str, Any]]:
            traces = getattr(self._store, "traces", [])
            if len(traces) < min_traces:
                return []

            suggestions: list[dict[str, Any]] = []
            suggestions.extend(self._analyze_strategy(traces))
            suggestions.extend(self._analyze_subtask_count(traces))
            suggestions.extend(self._analyze_context_efficiency(traces))
            suggestions.extend(self._analyze_role_patterns(traces))
            suggestions.extend(self._analyze_round_efficiency(traces))

            # rank by impact score
            suggestions.sort(key=lambda s: s.get("impact_score", 0), reverse=True)

            # dedup by similarity
            filtered = self._dedup_suggestions(suggestions)

            with self._lock:
                # merge with existing suggestions, keep top 20
                merged = {s["content"]: s for s in self._suggestions}
                for s in filtered:
                    key = s["content"]
                    if key in merged:
                        s["seen_count"] = merged[key].get("seen_count", 1) + 1
                        s["suggestion_id"] = merged[key].get("suggestion_id", _new_id("sug"))
                        # persist update
                        safe_call(None, lambda sid=s["suggestion_id"], sc=s["seen_count"]:
                            self._store.update_suggestion(sid, {"seen_count": sc}) if self._store else None)
                    else:
                        s["seen_count"] = 1
                        s["suggestion_id"] = _new_id("sug")
                        # persist new suggestion
                        safe_call(None, lambda sug=s: self._store.insert_suggestion(sug) if self._store else None)
                    merged[key] = s
                self._suggestions = sorted(merged.values(), key=lambda s: s.get("impact_score", 0), reverse=True)[:20]

            return filtered

        return safe_call_or([], self._cb, _do)

    # ── analyzers ────────────────────────────────────────────

    def _analyze_strategy(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compare success rates by decomposition strategy."""
        by_strategy: dict[str, list[dict[str, Any]]] = {}
        for t in traces:
            decomp = _parse_json(t.get("decomposition_json"), {})
            strategy = decomp.get("strategy", "unknown")
            by_strategy.setdefault(strategy, []).append(t)

        if len(by_strategy) < 2:
            return []

        suggestions: list[dict[str, Any]] = []
        for strategy, group in by_strategy.items():
            if len(group) < 5:
                continue
            success = sum(1 for t in group if _outcome_ok(t))
            rate = success / len(group)
            avg_rounds = _avg_rounds(group)
            avg_duration = _avg_duration(group)

            # compare against all other strategies
            others = [t for s, g in by_strategy.items() if s != strategy for t in g]
            if len(others) < 5:
                continue
            other_success = sum(1 for t in others if _outcome_ok(t))
            other_rate = other_success / len(others)

            delta = rate - other_rate
            confidence = _confidence(delta, len(group), len(others))
            if confidence < 0.7:
                continue

            impact = abs(delta) * confidence
            if delta > 0.1:
                suggestions.append({
                    "type": "strategy_advantage",
                    "content": f"'{strategy}' strategy outperforms others: {rate:.0%} vs {other_rate:.0%} "
                               f"(n={len(group)}, avg {avg_rounds:.1f} rounds, {avg_duration:.0f}s). "
                               f"Consider defaulting to '{strategy}' for similar tasks.",
                    "confidence": confidence,
                    "impact_score": impact,
                    "evidence": {
                        "strategy": strategy, "group_size": len(group), "success_rate": rate,
                        "other_rate": other_rate, "avg_rounds": avg_rounds, "avg_duration_s": avg_duration,
                    },
                    "generated_at": now_iso(),
                })
            elif delta < -0.1:
                suggestions.append({
                    "type": "strategy_avoid",
                    "content": f"'{strategy}' strategy underperforms: {rate:.0%} vs {other_rate:.0%} "
                               f"(n={len(group)}). Consider avoiding '{strategy}' unless explicitly needed.",
                    "confidence": confidence,
                    "impact_score": impact,
                    "evidence": {
                        "strategy": strategy, "group_size": len(group), "success_rate": rate,
                        "other_rate": other_rate,
                    },
                    "generated_at": now_iso(),
                })

        return suggestions

    def _analyze_subtask_count(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze relationship between subtask count and success."""
        bins: dict[str, list[dict[str, Any]]] = {"1-2": [], "3-5": [], "6+": []}
        for t in traces:
            decomp = _parse_json(t.get("decomposition_json"), {})
            n = decomp.get("num_subtasks", 1)
            if n <= 2:
                bins["1-2"].append(t)
            elif n <= 5:
                bins["3-5"].append(t)
            else:
                bins["6+"].append(t)

        results: list[dict[str, Any]] = []
        for label, group in bins.items():
            if len(group) < 5:
                continue
            success = sum(1 for t in group if _outcome_ok(t))
            rate = success / len(group)
            results.append({"label": label, "n": len(group), "rate": rate, "avg_rounds": _avg_rounds(group)})

        if len(results) < 2:
            return []

        best = max(results, key=lambda r: r["rate"])
        worst = min(results, key=lambda r: r["rate"])
        if best["rate"] - worst["rate"] > 0.15:
            confidence = _confidence(best["rate"] - worst["rate"], best["n"], worst["n"])
            return [{
                "type": "subtask_optimum",
                "content": f"Optimal subtask count: {best['label']} tasks ({best['rate']:.0%} success, n={best['n']}) "
                           f"vs {worst['label']} tasks ({worst['rate']:.0%} success, n={worst['n']}). "
                           f"Decompose into {best['label']} subtasks when possible.",
                "confidence": confidence,
                "impact_score": abs(best["rate"] - worst["rate"]) * confidence,
                "evidence": {"best": best, "worst": worst},
                "generated_at": now_iso(),
            }]
        return []

    def _analyze_context_efficiency(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze if context size correlates with success."""
        high_ctx: list[dict[str, Any]] = []
        low_ctx: list[dict[str, Any]] = []
        for t in traces:
            ctx_plan = _parse_json(t.get("context_plan_json"), {})
            tokens = ctx_plan.get("total_tokens_estimate", 0)
            if tokens > 10000:
                high_ctx.append(t)
            else:
                low_ctx.append(t)

        if len(high_ctx) < 5 or len(low_ctx) < 5:
            return []

        high_rate = sum(1 for t in high_ctx if _outcome_ok(t)) / len(high_ctx)
        low_rate = sum(1 for t in low_ctx if _outcome_ok(t)) / len(low_ctx)
        delta = low_rate - high_rate
        confidence = _confidence(delta, len(low_ctx), len(high_ctx))
        if confidence < 0.7 or abs(delta) < 0.1:
            return []

        direction = "more effective" if delta > 0 else "less effective"
        return [{
            "type": "context_efficiency",
            "content": f"Tasks with {'<10K' if delta > 0 else '>10K'} tokens context are {direction}: "
                       f"{low_rate:.0%} vs {high_rate:.0%}. "
                       f"Adjust context selection to {'minimize' if delta > 0 else 'maximize'} token count.",
            "confidence": confidence,
            "impact_score": abs(delta) * confidence,
            "evidence": {"low_ctx_rate": low_rate, "high_ctx_rate": high_rate,
                         "low_n": len(low_ctx), "high_n": len(high_ctx)},
            "generated_at": now_iso(),
        }]

    def _analyze_role_patterns(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze which agent role combinations work best."""
        by_roles: dict[str, list[dict[str, Any]]] = {}
        for t in traces:
            decomp = _parse_json(t.get("decomposition_json"), {})
            roles = tuple(sorted(decomp.get("roles_used", [])))
            key = "+".join(roles) if roles else "unknown"
            by_roles.setdefault(key, []).append(t)

        if len(by_roles) < 2:
            return []

        results = []
        for roles, group in by_roles.items():
            if len(group) < 5:
                continue
            rate = sum(1 for t in group if _outcome_ok(t)) / len(group)
            results.append({"roles": roles, "n": len(group), "rate": rate})

        if len(results) < 2:
            return []

        best = max(results, key=lambda r: r["rate"])
        if best["rate"] > 0.7:
            return [{
                "type": "role_optimum",
                "content": f"Role combination '{best['roles']}' achieves {best['rate']:.0%} success (n={best['n']}). "
                           f"Prefer this role mix for similar task types.",
                "confidence": 0.75,
                "impact_score": best["rate"] * 0.5,
                "evidence": {"best_roles": best, "all_roles": results},
                "generated_at": now_iso(),
            }]
        return []

    def _analyze_round_efficiency(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect if multi-round tasks have systemic issues."""
        multi_round = [t for t in traces if _parse_json(t.get("outcome_json"), {}).get("rounds_used", 1) > 2]
        single_round = [t for t in traces if _parse_json(t.get("outcome_json"), {}).get("rounds_used", 1) == 1]

        if len(multi_round) < 5:
            return []

        multi_rate = sum(1 for t in multi_round if _outcome_ok(t)) / len(multi_round)
        single_rate = sum(1 for t in single_round if _outcome_ok(t)) / len(single_round) if single_round else 1.0

        delta = single_rate - multi_rate
        if delta > 0.2:
            return [{
                "type": "round_inefficiency",
                "content": f"Multi-round tasks (>2 rounds) have {delta:.0%} lower success rate. "
                           f"Invest in better initial decomposition to reduce rounds.",
                "confidence": 0.8,
                "impact_score": delta * 0.8,
                "evidence": {"single_round_rate": single_rate, "multi_round_rate": multi_rate,
                             "multi_round_n": len(multi_round)},
                "generated_at": now_iso(),
            }]
        return []

    # ── suggestion management ────────────────────────────────

    def _dedup_suggestions(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result = []
        for s in suggestions:
            key = s["type"] + ":" + s.get("content", "")[:80]
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result

    def get_suggestions(self, min_confidence: float = 0.6) -> list[dict[str, Any]]:
        with self._lock:
            return [s for s in self._suggestions if s.get("confidence", 0) >= min_confidence]

    def apply_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        """Mark a suggestion as applied. Creates a memory so the system remembers the change."""
        with self._lock:
            for s in self._suggestions:
                # match by exact suggestion_id, type, content, or content prefix
                if (s.get("suggestion_id") == suggestion_id
                        or s.get("type") == suggestion_id
                        or s.get("content") == suggestion_id
                        or s.get("content", "").startswith(suggestion_id)):
                    s["applied"] = True
                    s["applied_at"] = now_iso()
                    # Persist the applied state
                    sid = s.get("suggestion_id", "")
                    safe_call(None, lambda: self._store.update_suggestion(sid,
                        {"applied": True, "applied_at": now_iso()}) if self._store and sid else None)
                    # Propagate as a memory via the proper MemoryStore path
                    if self._memory_store and self._memory_store._store:
                        mid = _new_id("active")
                        item = {
                            "layer": "strategic",
                            "type": "pattern",
                            "content": s["content"],
                            "source_trace_ids_json": "[]",
                            "consolidation_count": 1,
                            "weight": s.get("confidence", 0.7),
                            "scope": "project",
                            "project_path": None,
                            "metadata_json": json.dumps({"source": "active_learning"}, ensure_ascii=False),
                        }
                        # encode embedding and store in both DB and LanceDB
                        vec = safe_call_or(
                            [0.0] * (self._memory_store._provider.dim() if self._memory_store._provider else 384),
                            None,
                            lambda: self._memory_store._provider.encode([s["content"]])[0]
                            if self._memory_store._provider else [0.0] * 384,
                        )
                        safe_call(None, self._memory_store._insert_one, mid, item, vec)
                        safe_call(None, lambda: self._memory_store._vstore.add(mid, vec, s["content"])
                                  if self._memory_store._vstore else None)
                    return {"ok": True, "suggestion": s}
            return {"ok": False, "error": "suggestion not found"}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            applied = sum(1 for s in self._suggestions if s.get("applied"))
            return {
                "total_suggestions": len(self._suggestions),
                "applied": applied,
                "pending": len(self._suggestions) - applied,
                "top_suggestion": self._suggestions[0]["content"][:120] if self._suggestions else None,
            }


# ── A/B evaluation framework ─────────────────────────────────

class ABEvaluator:
    """Compares two strategies by running them on similar tasks and measuring outcomes."""

    def __init__(self) -> None:
        self._store: Any = None
        self._experiments: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def init_app(self, store: Any) -> None:
        self._store = store
        # Load persisted experiments, deserializing JSON columns
        try:
            loaded = store.list_experiments()
            with self._lock:
                for exp in loaded:
                    eid = exp["experiment_id"]
                    self._experiments[eid] = {
                        "id": eid,
                        "name": exp.get("name", ""),
                        "control_label": exp.get("control_label", "control"),
                        "treatment_label": exp.get("treatment_label", "treatment"),
                        "filter_expr": exp.get("filter_expr"),
                        "control": _parse_json(exp.get("control_json"), {"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0}),
                        "treatment": _parse_json(exp.get("treatment_json"), {"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0}),
                        "created_at": exp.get("created_at", ""),
                        "concluded": exp.get("concluded", False),
                        "winner": exp.get("winner"),
                    }
        except Exception:
            pass

    def create_experiment(
        self,
        name: str,
        control_label: str,
        treatment_label: str,
        filter_expr: str | None = None,
    ) -> str:
        """Create an A/B experiment. filter_expr matches task descriptions."""
        exp_id = _new_id("ab")
        exp = {
            "experiment_id": exp_id,
            "name": name,
            "control_label": control_label,
            "treatment_label": treatment_label,
            "filter_expr": filter_expr,
            "control_json": json.dumps({"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0}),
            "treatment_json": json.dumps({"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0}),
            "concluded": False,
            "winner": None,
        }
        with self._lock:
            self._experiments[exp_id] = {
                "id": exp_id,
                "name": name,
                "control_label": control_label,
                "treatment_label": treatment_label,
                "filter_expr": filter_expr,
                "control": {"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0},
                "treatment": {"count": 0, "success": 0, "total_rounds": 0, "total_duration": 0},
                "created_at": now_iso(),
                "concluded": False,
                "winner": None,
            }
            # Persist
            safe_call(None, lambda: self._store.insert_experiment(exp) if self._store else None)
        return exp_id

    def record_outcome(self, experiment_id: str, group: str, trace: dict[str, Any]) -> None:
        """Record a task outcome for an A/B experiment."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None or exp["concluded"]:
                return
            bucket = exp.get(group)
            if bucket is None:
                return
            bucket["count"] += 1
            outcome = _parse_json(trace.get("outcome_json"), {})
            if _outcome_ok(trace):
                bucket["success"] += 1
            bucket["total_rounds"] += outcome.get("rounds_used", 1)
            bucket["total_duration"] += outcome.get("total_duration_seconds", 0)
            # Persist updated bucket
            persist_key = f"{group}_json"
            safe_call(None, lambda eid=experiment_id, k=persist_key, b=dict(bucket):
                self._store.update_experiment(eid, {k: json.dumps(b)}) if self._store else None)

    def evaluate(self, experiment_id: str, min_samples: int = 10) -> dict[str, Any]:
        """Evaluate experiment results. Auto-concludes if winner is clear."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None:
                return {"ok": False, "error": "experiment not found"}

            c = exp["control"]
            t = exp["treatment"]
            if c["count"] < min_samples or t["count"] < min_samples:
                return {"ok": True, "concluded": False, "reason": "insufficient_samples",
                        "control_n": c["count"], "treatment_n": t["count"]}

            c_rate = c["success"] / c["count"] if c["count"] else 0
            t_rate = t["success"] / t["count"] if t["count"] else 0
            c_avg_r = c["total_rounds"] / c["count"] if c["count"] else 0
            t_avg_r = t["total_rounds"] / t["count"] if t["count"] else 0
            c_avg_d = c["total_duration"] / c["count"] if c["count"] else 0
            t_avg_d = t["total_duration"] / t["count"] if t["count"] else 0

            delta = t_rate - c_rate
            confidence = _confidence(delta, t["count"], c["count"])

            result = {
                "ok": True,
                "control": {"n": c["count"], "success_rate": c_rate, "avg_rounds": c_avg_r, "avg_duration_s": c_avg_d},
                "treatment": {"n": t["count"], "success_rate": t_rate, "avg_rounds": t_avg_r, "avg_duration_s": t_avg_d},
                "delta": delta,
                "confidence": confidence,
            }

            # auto-conclude if confidence is high enough
            if confidence > 0.9 and abs(delta) > 0.05:
                exp["concluded"] = True
                exp["winner"] = exp["treatment_label"] if delta > 0 else exp["control_label"]
                result["concluded"] = True
                result["winner"] = exp["winner"]
                result["recommendation"] = f"Switch to '{exp['winner']}' — {abs(delta):.0%} improvement"
                # Persist conclusion
                safe_call(None, lambda eid=experiment_id, w=exp["winner"]:
                    self._store.update_experiment(eid, {"concluded": True, "winner": w}) if self._store else None)
            else:
                result["concluded"] = False

            return result

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"id": eid, "name": e["name"], "concluded": e["concluded"],
                 "winner": e["winner"], "control_n": e["control"]["count"],
                 "treatment_n": e["treatment"]["count"]}
                for eid, e in self._experiments.items()
            ]


# ── helpers ──────────────────────────────────────────────────

def _parse_json(raw: Any, fallback: Any = None) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return fallback if fallback is not None else {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else {}


def _outcome_ok(trace: dict[str, Any]) -> bool:
    outcome = _parse_json(trace.get("outcome_json"), {})
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except (json.JSONDecodeError, TypeError):
            return False
    return outcome.get("status") == "completed"


def _avg_rounds(group: list[dict[str, Any]]) -> float:
    if not group:
        return 0.0
    total = sum(_parse_json(t.get("outcome_json"), {}).get("rounds_used", 1) for t in group)
    return total / len(group)


def _avg_duration(group: list[dict[str, Any]]) -> float:
    if not group:
        return 0.0
    total = sum(_parse_json(t.get("outcome_json"), {}).get("total_duration_seconds", 0) for t in group)
    return total / len(group)


def _confidence(delta: float, n1: int, n2: int) -> float:
    """Simple confidence score based on effect size and sample sizes.
    Uses Welch's t-test approximation.
    """
    if n1 < 2 or n2 < 2:
        return 0.0
    # pooled standard error approximation
    se = math.sqrt(0.25 / n1 + 0.25 / n2)  # max variance for proportions
    if se == 0:
        return 0.0
    t = abs(delta) / se
    # Convert t-statistic to approximate confidence
    # For df = n1 + n2 - 2, using normal approximation
    if t > 3.0:
        return 0.99
    elif t > 2.0:
        return 0.95
    elif t > 1.5:
        return 0.85
    elif t > 1.0:
        return 0.70
    elif t > 0.5:
        return 0.50
    return 0.30


active_engine = ActiveLearningEngine()
ab_evaluator = ABEvaluator()
