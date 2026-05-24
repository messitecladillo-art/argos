"""Central configuration for the self-evolving learning system.

All parameters are overridable via environment variables with LEARN_ prefix.
"""

from __future__ import annotations

import os
from pathlib import Path


def _bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _float_env(key: str, default: float) -> float:
    val = os.environ.get(key, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _int_env(key: str, default: int) -> int:
    val = os.environ.get(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ── master switch ────────────────────────────────────────────

ENABLED = _bool_env("LEARN_ENABLED", True)

# ── vector store ─────────────────────────────────────────────

LANCE_URI = os.environ.get("LEARN_LANCE_URI", str(Path.home() / ".hermes" / "learning.lance"))

# ── embedding ────────────────────────────────────────────────

EMBED_PROVIDER = os.environ.get("LEARN_EMBED_PROVIDER", "ollama")  # "ollama" | "dummy"
OLLAMA_BASE_URL = os.environ.get("LEARN_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_EMBED_MODEL = os.environ.get("LEARN_OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT = _int_env("LEARN_OLLAMA_TIMEOUT", 30)

# ── retrieval ────────────────────────────────────────────────

TOP_K = _int_env("LEARN_TOP_K", 5)
MIN_WEIGHT = _float_env("LEARN_MIN_WEIGHT", 0.3)
MAX_CONTEXT_CHARS = _int_env("LEARN_MAX_CONTEXT_CHARS", 3000)

# ── feedback ─────────────────────────────────────────────────

FEEDBACK_INTERVAL_SEC = _int_env("LEARN_FEEDBACK_INTERVAL", 300)  # 5 min
FEEDBACK_MIN_TRACES = _int_env("LEARN_FEEDBACK_MIN_TRACES", 3)

# ── consolidation ────────────────────────────────────────────

CONSOLIDATION_INTERVAL_SEC = _int_env("LEARN_CONSOLIDATION_INTERVAL", 1800)  # 30 min
CONSOLIDATION_MIN_TRACES = _int_env("LEARN_CONSOLIDATION_MIN_TRACES", 5)
CONSOLIDATION_MIN_GROUP_SIZE = _int_env("LEARN_CONSOLIDATION_MIN_GROUP", 2)
CONSOLIDATION_MIN_SUCCESS_RATE = _float_env("LEARN_CONSOLIDATION_MIN_SUCCESS", 0.7)

# ── eviction ─────────────────────────────────────────────────

EVICTION_INTERVAL_SEC = _int_env("LEARN_EVICTION_INTERVAL", 3600)  # 1 hour
EVICTION_MIN_WEIGHT = _float_env("LEARN_EVICTION_MIN_WEIGHT", 0.05)

# TTL in days per layer (0 = never expire)
TTL_STRATEGIC_DAYS = _int_env("LEARN_TTL_STRATEGIC_DAYS", 90)
TTL_TACTICAL_DAYS = _int_env("LEARN_TTL_TACTICAL_DAYS", 30)
TTL_OPERATIONAL_DAYS = _int_env("LEARN_TTL_OPERATIONAL_DAYS", 7)

# Dedup similarity threshold (0.95 = very close)
DEDUP_THRESHOLD = _float_env("LEARN_DEDUP_THRESHOLD", 0.95)

# Max memories to prevent unbounded growth
MAX_MEMORIES = _int_env("LEARN_MAX_MEMORIES", 20000)

# ── weight decay ─────────────────────────────────────────────

DECAY_RATE_PER_DAY = _float_env("LEARN_DECAY_RATE", 0.01)  # 1% per day unused

# ── circuit breaker ──────────────────────────────────────────

CB_FAILURE_THRESHOLD = _int_env("LEARN_CB_THRESHOLD", 5)
CB_WINDOW_SEC = _int_env("LEARN_CB_WINDOW", 300)  # 5 min
CB_COOLDOWN_SEC = _int_env("LEARN_CB_COOLDOWN", 600)  # 10 min

TTL_MAP = {
    "strategic": TTL_STRATEGIC_DAYS,
    "tactical": TTL_TACTICAL_DAYS,
    "operational": TTL_OPERATIONAL_DAYS,
}
