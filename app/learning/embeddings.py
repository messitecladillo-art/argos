"""Embedding provider + LanceDB vector store + circuit breaker."""

from __future__ import annotations

import json
import math
import time
import threading
from pathlib import Path
from typing import Any, Protocol


# ── embedding providers ──────────────────────────────────────

class EmbeddingProvider(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...
    def dim(self) -> int: ...


class OllamaEmbedding:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "nomic-embed-text", timeout: int = 30) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._dim: int | None = None

    def dim(self) -> int:
        if self._dim is not None:
            return self._dim
        vec = self.encode(["probe"])
        self._dim = len(vec[0])
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        import urllib.request
        payload = json.dumps({"model": self._model, "input": texts}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())
        return data["embeddings"]

    def ready(self) -> bool:
        try:
            self.encode(["health"])
            return True
        except Exception:
            return False


class DummyEmbedding:
    DIM = 384

    def dim(self) -> int:
        return self.DIM

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.DIM for _ in texts]


# ── LanceDB vector store ─────────────────────────────────────

class VectorStore:
    """LanceDB-backed ANN vector index. Metadata stays in SQLite."""

    def __init__(self, uri: str, dim: int) -> None:
        self._uri = uri
        self._dim = dim
        self._db: Any = None
        self._table: Any = None
        self._lock = threading.Lock()

    def _ensure_open(self) -> None:
        if self._table is not None:
            return
        import lancedb
        Path(self._uri).parent.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self._uri)
        try:
            self._table = self._db.open_table("memories")
        except Exception:
            import pyarrow as pa
            self._table = self._db.create_table(
                "memories",
                schema=pa.schema([
                    pa.field("memory_id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), self._dim)),
                    pa.field("content", pa.string()),
                ]),
            )

    def add(self, memory_id: str, vector: list[float], content: str) -> None:
        with self._lock:
            self._ensure_open()
            self._table.add([{
                "memory_id": memory_id,
                "vector": _plain_vector(vector),
                "content": content,
            }])

    def delete(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        with self._lock:
            self._ensure_open()
            self._table.delete("memory_id IN (" + ",".join(f"'{m}'" for m in memory_ids) + ")")

    def search(self, query_vector: list[float], top_k: int = 10, filter_expr: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_open()
            builder = self._table.search(_plain_vector(query_vector)).metric("cosine").limit(top_k)
            if filter_expr:
                builder = builder.where(filter_expr)
            results = builder.to_list()
            return [{"memory_id": r["memory_id"], "content": r.get("content", ""), "_distance": r.get("_distance", 1.0)} for r in results]

    def count(self) -> int:
        with self._lock:
            self._ensure_open()
            return self._table.count_rows()

    def drop(self) -> None:
        with self._lock:
            if self._db is None:
                return
            try:
                self._db.drop_table("memories")
            except Exception:
                pass
            self._table = None


# ── circuit breaker ──────────────────────────────────────────

def _plain_vector(vector: list[float]) -> list[float]:
    return [float(value) for value in vector]


class CircuitBreaker:
    """Prevents cascading failures from learning module into main flow."""

    def __init__(self, name: str, failure_threshold: int = 5, window_sec: float = 300, cooldown_sec: float = 600) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._window = window_sec
        self._cooldown = cooldown_sec
        self._failures: list[float] = []
        self._open_since: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._open_since is None:
                return False
            if time.monotonic() - self._open_since > self._cooldown:
                # half-open: allow one probe
                self._open_since = None
                self._failures.clear()
                return False
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = [t for t in self._failures if time.monotonic() - t < self._window]

    def failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures = [t for t in self._failures if now - t < self._window]
            self._failures.append(now)
            if len(self._failures) >= self._threshold:
                self._open_since = now

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._open_since = None


# ── safe call wrapper ────────────────────────────────────────

_safe_lock = threading.Lock()
_safe_log: list[dict[str, Any]] = []


def safe_call(cb: CircuitBreaker | None, fn, *args, **kwargs) -> Any:
    """Execute fn with full error isolation. Never raises to caller."""
    if cb is not None and cb.is_open:
        return None
    try:
        result = fn(*args, **kwargs)
        if cb is not None:
            cb.success()
        return result
    except Exception as exc:
        if cb is not None:
            cb.failure()
        with _safe_lock:
            _safe_log.append({"ts": time.time(), "error": str(exc), "cb": cb.name if cb else "none"})
            if len(_safe_log) > 100:
                _safe_log[:] = _safe_log[-50:]
        return None


def safe_call_or(fallback: Any, cb: CircuitBreaker | None, fn, *args, **kwargs) -> Any:
    result = safe_call(cb, fn, *args, **kwargs)
    return fallback if result is None else result


# ── utility ──────────────────────────────────────────────────

def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
