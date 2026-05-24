"""Experience memory store — LanceDB ANN retrieval, eviction, dedup, decay."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from ..config import now_iso
from . import config as cfg
from .embeddings import (
    CircuitBreaker,
    DummyEmbedding,
    EmbeddingProvider,
    OllamaEmbedding,
    VectorStore,
    cosine,
    safe_call,
    safe_call_or,
)
from .traces import _new_id

from .metrics import metrics_collector  # noqa: E402


# ── seed memories ────────────────────────────────────────────

SEED_STRATEGIC_MEMORIES: list[dict[str, Any]] = [
    {
        "layer": "strategic", "type": "pattern",
        "content": "For tasks involving more than 3 source files, use exploration-first strategy: "
                   "assign an explorer agent to map dependencies and identify affected modules "
                   "before assigning implementation work.",
        "weight": 0.70, "scope": "global",
    },
    {
        "layer": "strategic", "type": "pattern",
        "content": "When a user describes a 'refactoring' or 'restructuring' task, always begin "
                   "with a codebase exploration step. Map before you move.",
        "weight": 0.75, "scope": "global",
    },
    {
        "layer": "strategic", "type": "pattern",
        "content": "For feature-addition tasks, prefer sequential assignment: first produce a "
                   "design/spec, then implement, then test. Parallel only when subtasks have "
                   "zero shared dependencies.",
        "weight": 0.65, "scope": "global",
    },
    {
        "layer": "operational", "type": "constraint",
        "content": "When modifying ORM model files (models.py), always check whether a database "
                   "migration is needed.",
        "weight": 0.80, "scope": "global",
    },
    {
        "layer": "operational", "type": "pitfall",
        "content": "Avoid mixing sync and async patterns in the same code path.",
        "weight": 0.70, "scope": "global",
    },
    # ── Chinese-market seed memories ──────────────────────────
    {
        "layer": "strategic", "type": "pattern",
        "content": "涉及3个以上源文件的任务，采用先探索后实施的策略：先指派探索 agent 梳理"
                   "模块依赖关系，明确影响范围，再进行具体实现。",
        "weight": 0.70, "scope": "global",
    },
    {
        "layer": "strategic", "type": "pattern",
        "content": "当用户描述重构或结构调整类任务时，务必先进行代码库探索。先摸底，再动手。",
        "weight": 0.75, "scope": "global",
    },
    {
        "layer": "strategic", "type": "pattern",
        "content": "新增功能类任务优先采用串行策略：先产出设计方案，再编码实现，最后测试验证。"
                   "仅当子任务零共享依赖时才考虑并行。",
        "weight": 0.65, "scope": "global",
    },
    {
        "layer": "operational", "type": "constraint",
        "content": "修改 ORM 模型文件（models.py）时，务必检查是否需要同步创建数据库迁移脚本。",
        "weight": 0.80, "scope": "global",
    },
    {
        "layer": "operational", "type": "pitfall",
        "content": "避免在同一代码路径中混用同步和异步模式，容易导致事件循环混乱。",
        "weight": 0.70, "scope": "global",
    },
    {
        "layer": "operational", "type": "constraint",
        "content": "金融、政务等合规场景下，所有外部 API 调用必须记录完整审计日志，"
                   "包含请求参数、响应摘要和调用耗时。",
        "weight": 0.85, "scope": "global",
    },
    {
        "layer": "strategic", "type": "pattern",
        "content": "对于涉及敏感数据的任务，优先在本地处理，避免将数据传输到外部服务。"
                   "本地部署场景下，所有模型推理和数据处理均应在内网完成。",
        "weight": 0.80, "scope": "global",
    },
]


class MemoryStore:
    """LanceDB-accelerated memory store with full lifecycle management."""

    def __init__(self, provider: EmbeddingProvider | None = None) -> None:
        self._provider: EmbeddingProvider | None = provider
        self._store: Any = None
        self._vstore: VectorStore | None = None
        self._cb = CircuitBreaker("memory", cfg.CB_FAILURE_THRESHOLD, cfg.CB_WINDOW_SEC, cfg.CB_COOLDOWN_SEC)
        self._eviction_thread: threading.Thread | None = None
        self._stop_eviction = threading.Event()
        self._initialized = False

    def init_app(self, store: Any) -> None:
        if self._initialized:
            return
        self._store = store
        if self._provider is None:
            self._provider = _build_provider()
        # Init LanceDB
        dim = safe_call_or(self._provider.dim(), None, self._provider.dim) if self._provider else 384
        self._vstore = VectorStore(cfg.LANCE_URI, dim or 384)
        self._ensure_seeds()
        self._start_eviction()
        self._initialized = True

    def shutdown(self) -> None:
        self._stop_eviction.set()
        if self._eviction_thread and self._eviction_thread.is_alive():
            self._eviction_thread.join(timeout=5)

    # ── seeds ────────────────────────────────────────────────

    def _ensure_seeds(self) -> None:
        for item in SEED_STRATEGIC_MEMORIES:
            mid = _seed_memory_id(item)
            existing = safe_call(None, lambda: self._store.find_memory(mid) if self._store else None)
            if existing:
                continue
            vec = safe_call_or([0.0] * (self._provider.dim() if self._provider else 384), None,
                              lambda: self._provider.encode([item["content"]])[0])
            safe_call(None, self._insert_one, mid, item, vec)
            safe_call(None, lambda: self._vstore.add(mid, vec, item["content"]) if self._vstore else None)

    def _insert_one(self, mid: str, item: dict[str, Any], vec: list[float]) -> None:
        if self._store is None:
            return
        self._store.insert_memory({
            "memory_id": mid, "layer": item["layer"], "type": item["type"],
            "content": item["content"], "embedding_json": json.dumps(vec),
            "source_trace_ids_json": item.get("source_trace_ids_json", "[]"),
            "consolidation_count": item.get("consolidation_count", 1),
            "weight": item["weight"], "use_count": 0, "success_count": 0,
            "scope": item.get("scope", "project"),
            "project_path": item.get("project_path"),
            "metadata_json": item.get("metadata_json", "{}"),
            "created_at": now_iso(), "last_used_at": None, "expires_at": None, "deleted_at": None,
        })

    # ── retrieval ────────────────────────────────────────────

    def retrieve(
        self,
        task_description: str,
        *,
        layer: str | None = None,
        top_k: int | None = None,
        min_weight: float | None = None,
    ) -> list[dict[str, Any]]:
        if self._store is None:
            return []
        top_k = top_k if top_k is not None else cfg.TOP_K
        min_weight = min_weight if min_weight is not None else cfg.MIN_WEIGHT

        q_vec = safe_call_or([0.0] * (self._provider.dim() if self._provider else 384), self._cb,
                             lambda: self._provider.encode([task_description])[0])

        is_dummy = all(v == 0.0 for v in q_vec)

        # LanceDB ANN search (skip for dummy vectors)
        vector_results: list[dict[str, Any]] = []
        if not is_dummy and self._vstore is not None:
            vector_results = safe_call_or([], self._cb,
                lambda: self._vstore.search(q_vec, top_k=max(top_k * 3, 20)))

        scored: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()

        if vector_results:
            for r in vector_results:
                mid = r.get("memory_id", "")
                if mid in seen:
                    continue
                seen.add(mid)
                mem = safe_call(None, lambda: self._store.find_memory(mid))
                if mem is None or mem.get("deleted_at"):
                    continue
                if mem.get("weight", 0.5) < min_weight:
                    continue
                if layer is not None and mem.get("layer") != layer:
                    continue
                sim = 1.0 - r.get("_distance", 1.0)
                score = sim * mem.get("weight", 0.5)
                scored.append((score, mem))
        else:
            # Fallback: keyword-based scoring over all candidates
            candidates = self._store.list_memories(layer=layer, min_weight=min_weight)
            for mem in candidates:
                if mem.get("deleted_at"):
                    continue
                ks = _keyword_score(task_description, mem.get("content", ""))
                score = ks * mem.get("weight", 0.5)
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [mem for _, mem in scored[:top_k]]
        metrics_collector.record_retrieval(len(result) > 0)
        return result

    def inject_into_context(self, task_description: str, target: str) -> str:
        layer_map = {"leader_decompose": "strategic", "worker_execute": "tactical", "leader_review": "strategic"}
        primary = layer_map.get(target, "strategic")

        memories: list[dict[str, Any]] = []
        for lyr in [primary, "operational"]:
            memories += self.retrieve(task_description, layer=lyr, top_k=cfg.TOP_K)

        if not memories:
            return ""

        seen: set[str] = set()
        lines = ["\n## Relevant past experience (auto-retrieved)\n"]
        chars = 0
        tag_map = {"strategic": "[策略]", "tactical": "[战术]", "operational": "[注意]"}
        for mem in memories:
            if mem["memory_id"] in seen:
                continue
            seen.add(mem["memory_id"])
            tag = tag_map.get(mem["layer"], "")
            line = f"- {tag} {mem['content']} (置信度: {mem.get('weight', 0.5):.0%})"
            if chars + len(line) > cfg.MAX_CONTEXT_CHARS:
                break
            lines.append(line)
            chars += len(line)

        return "\n".join(lines)

    # ── consolidation ────────────────────────────────────────

    def consolidate_from_traces(self, min_new_traces: int | None = None) -> int:
        if self._store is None or self._vstore is None:
            return 0
        min_new_traces = min_new_traces if min_new_traces is not None else cfg.CONSOLIDATION_MIN_TRACES

        def _do() -> int:
            traces = self._store.list_unconsolidated_traces(limit=50)
            if len(traces) < min_new_traces:
                return 0
            new_count = 0
            groups = _group_by_task_type(traces)
            for task_type, group in groups.items():
                if len(group) < cfg.CONSOLIDATION_MIN_GROUP_SIZE:
                    continue
                success_rate = sum(1 for t in group if _outcome_ok(t)) / len(group)
                if success_rate < cfg.CONSOLIDATION_MIN_SUCCESS_RATE:
                    continue
                content = _synthesize_strategic_memory(task_type, group)
                # dedup check
                existing = self.retrieve(content, top_k=1, min_weight=0.0)
                if existing and existing[0].get("weight", 0) > 0.5:
                    # update existing instead of creating new
                    mid = existing[0]["memory_id"]
                    self._store.update_memory(mid, {"consolidation_count": existing[0].get("consolidation_count", 1) + len(group)})
                else:
                    mid = _new_id("mem")
                    vec = safe_call_or([0.0] * (self._provider.dim() if self._provider else 384), self._cb,
                                       lambda: self._provider.encode([content])[0])
                    trace_ids = [t.get("trace_id", "") for t in group]
                    self._insert_one(mid, {
                        "layer": "strategic", "type": "pattern",
                        "content": content,
                        "source_trace_ids_json": json.dumps(trace_ids),
                        "consolidation_count": len(group),
                        "weight": min(success_rate, 0.9),
                        "scope": "project", "project_path": None,
                        "metadata_json": "{}",
                    }, vec)
                    safe_call(None, lambda: self._vstore.add(mid, vec, content))
                    new_count += 1
            self._store.mark_traces_consolidated(traces)
            if new_count > 0:
                metrics_collector.record_consolidation(new_count)
            return new_count

        return safe_call_or(0, self._cb, _do)

    # ── weight management ────────────────────────────────────

    def adjust_weight(self, memory_id: str, signal_strength: float) -> None:
        def _do() -> None:
            if self._store is None:
                return
            mem = self._store.find_memory(memory_id)
            if mem is None:
                return
            old = mem.get("weight", 0.5)
            delta = signal_strength * 0.1
            new = max(0.02, min(0.95, old + delta))
            updates: dict[str, Any] = {"weight": new, "last_used_at": now_iso()}
            updates["use_count"] = mem.get("use_count", 0) + 1
            if signal_strength > 0:
                updates["success_count"] = mem.get("success_count", 0) + 1
            self._store.update_memory(memory_id, updates)
        safe_call(self._cb, _do)

    # ── eviction & lifecycle ──────────────────────────────────

    def _start_eviction(self) -> None:
        if self._eviction_thread and self._eviction_thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop_eviction.wait(cfg.EVICTION_INTERVAL_SEC):
                safe_call(None, self._evict_once)

        self._eviction_thread = threading.Thread(target=_loop, daemon=True)
        self._eviction_thread.start()

    def _evict_once(self) -> int:
        if self._store is None:
            return 0
        removed = 0

        # 1. evict by weight
        all_mems = self._store.list_memories(min_weight=0.0)
        low_weight = [m for m in all_mems if m.get("weight", 0.5) < cfg.EVICTION_MIN_WEIGHT]
        if low_weight:
            ids = [m["memory_id"] for m in low_weight]
            for mid in ids:
                self._store.update_memory(mid, {"deleted_at": now_iso()})
            safe_call(None, lambda: self._vstore.delete(ids))
            removed += len(ids)

        # 2. evict by TTL
        now = now_iso()
        for m in all_mems:
            if m.get("deleted_at"):
                continue
            layer = m.get("layer", "strategic")
            ttl_days = cfg.TTL_MAP.get(layer, 0)
            if ttl_days <= 0:
                continue
            created = m.get("created_at", "")
            if not created:
                continue
            try:
                age_days = (_parse_iso(now) - _parse_iso(created)).total_seconds() / 86400
            except Exception:
                continue
            if age_days > ttl_days:
                self._store.update_memory(m["memory_id"], {"deleted_at": now})
                safe_call(None, lambda: self._vstore.delete([m["memory_id"]]))
                removed += 1

        # 3. decay unused memories
        for m in all_mems:
            if m.get("deleted_at"):
                continue
            last_used = m.get("last_used_at")
            if not last_used:
                continue
            try:
                unused_days = (_parse_iso(now) - _parse_iso(last_used)).total_seconds() / 86400
            except Exception:
                continue
            if unused_days > 7:
                decay = cfg.DECAY_RATE_PER_DAY * unused_days
                old_w = m.get("weight", 0.5)
                new_w = max(0.02, old_w - decay)
                if new_w != old_w:
                    self._store.update_memory(m["memory_id"], {"weight": new_w})

        # 4. dedup (check top memories for near-duplicates)
        all_mems = self._store.list_memories(min_weight=0.3)
        if len(all_mems) > 10:
            self._dedup(all_mems)

        # 5. hard cap
        all_mems = self._store.list_memories(min_weight=0.0)
        alive = [m for m in all_mems if not m.get("deleted_at")]
        if len(alive) > cfg.MAX_MEMORIES:
            alive.sort(key=lambda m: m.get("weight", 0.5))
            to_remove = alive[:len(alive) - cfg.MAX_MEMORIES]
            ids = [m["memory_id"] for m in to_remove]
            for mid in ids:
                self._store.update_memory(mid, {"deleted_at": now_iso()})
            safe_call(None, lambda: self._vstore.delete(ids))
            removed += len(ids)

        metrics_collector.record_eviction(removed)
        return removed

    def _dedup(self, memories: list[dict[str, Any]]) -> int:
        removed = 0
        # Pre-parse all embeddings to avoid O(n²) JSON parsing
        parsed = {m["memory_id"]: _parse_embedding(m.get("embedding_json")) for m in memories}
        for i in range(len(memories)):
            mi = memories[i]
            if mi.get("deleted_at"):
                continue
            emb_i = parsed.get(mi["memory_id"], [])
            for j in range(i + 1, len(memories)):
                mj = memories[j]
                if mj.get("deleted_at") or mi["layer"] != mj["layer"]:
                    continue
                emb_j = parsed.get(mj["memory_id"], [])
                sim = cosine(emb_i, emb_j)
                if sim > cfg.DEDUP_THRESHOLD:
                    # keep the higher-weight one, boost its weight
                    if mi["weight"] >= mj["weight"]:
                        self._store.update_memory(mi["memory_id"],
                            {"weight": min(0.95, mi["weight"] + 0.05), "consolidation_count": mi.get("consolidation_count", 1) + 1})
                        self._store.update_memory(mj["memory_id"], {"deleted_at": now_iso()})
                        safe_call(None, lambda: self._vstore.delete([mj["memory_id"]]))
                    removed += 1
        return removed

    # ── stats ────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        if self._store is None:
            return {"ok": False, "error": "not initialized"}
        all_mems = self._store.list_memories(min_weight=0.0)
        alive = [m for m in all_mems if not m.get("deleted_at")]
        per_layer = {"strategic": 0, "tactical": 0, "operational": 0}
        for m in alive:
            lyr = m.get("layer", "strategic")
            per_layer[lyr] = per_layer.get(lyr, 0) + 1
        weights = [m.get("weight", 0.5) for m in alive]
        vstore_count = safe_call_or(0, None, lambda: self._vstore.count()) if self._vstore else 0
        return {
            "total_memories": len(alive),
            "vector_count": vstore_count,
            "per_layer": per_layer,
            "avg_weight": sum(weights) / len(weights) if weights else 0,
            "cb_open": self._cb.is_open,
            "provider_dim": self._provider.dim() if self._provider else 0,
        }


# ── helpers ──────────────────────────────────────────────────

def _seed_memory_id(item: dict[str, Any]) -> str:
    digest = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()[:12]
    return f"seed_{item['layer']}_{item['type']}_{digest}"


def _build_provider() -> EmbeddingProvider:
    if cfg.EMBED_PROVIDER == "ollama":
        prov = OllamaEmbedding(base_url=cfg.OLLAMA_BASE_URL, model=cfg.OLLAMA_EMBED_MODEL, timeout=cfg.OLLAMA_TIMEOUT)
        if prov.ready():
            return prov
    return DummyEmbedding()


def _parse_embedding(raw: Any) -> list[float]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _outcome_ok(trace: dict[str, Any]) -> bool:
    outcome = trace.get("outcome_json", "{}")
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except (json.JSONDecodeError, TypeError):
            return False
    return outcome.get("status") == "completed"


def _group_by_task_type(traces: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in traces:
        decomp = t.get("decomposition_json", "{}")
        if isinstance(decomp, str):
            try:
                decomp = json.loads(decomp)
            except (json.JSONDecodeError, TypeError):
                decomp = {}
        strategy = decomp.get("strategy", "unknown")
        groups.setdefault(strategy, []).append(t)
    return groups


def _synthesize_strategic_memory(task_type: str, group: list[dict[str, Any]]) -> str:
    total = len(group)
    success = sum(1 for t in group if _outcome_ok(t))
    avg_rounds = sum(
        (t.get("outcome_json", {}) if isinstance(t.get("outcome_json"), dict) else {}).get("rounds_used", 1)
        for t in group
    ) / total if total else 0
    return (
        f"For tasks using '{task_type}' strategy (observed in {total} executions): "
        f"success rate {success}/{total} ({success/total:.0%}), "
        f"average {avg_rounds:.1f} rounds. "
        f"Favor this strategy for similar task types."
    )


def _keyword_score(query: str, content: str) -> float:
    q_words = set(query.lower().split())
    c_words = set(content.lower().split())
    if not q_words:
        return 0.3
    overlap = q_words & c_words
    return 0.3 + 0.4 * (len(overlap) / len(q_words))


def _parse_iso(ts: str) -> Any:
    from datetime import datetime, timezone
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


memory_store = MemoryStore()
