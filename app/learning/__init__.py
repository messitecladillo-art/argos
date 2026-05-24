"""Self-evolving learning system — production-grade.

Components:
- config: all parameters via LEARN_* env vars
- embeddings: Ollama + LanceDB + CircuitBreaker + safe_call
- traces: ExecutionTrace collector (passive observer)
- memory: LanceDB-accelerated store with eviction/dedup/decay
- feedback: async background worker for signal extraction

Usage:
    from app.learning import trace_collector, memory_store, feedback_engine

    # lifecycle
    trace_collector.init_app(store)
    memory_store.init_app(store)
    feedback_engine.init_app(store, memory_store)

    # later
    memory_store.shutdown()
    feedback_engine.shutdown()
"""

from . import config
from .active import ABEvaluator, ActiveLearningEngine, ab_evaluator, active_engine
from .embeddings import (
    CircuitBreaker,
    DummyEmbedding,
    EmbeddingProvider,
    OllamaEmbedding,
    VectorStore,
    safe_call,
    safe_call_or,
)
from .feedback import FeedbackEngine, feedback_engine
from .memory import MemoryStore, memory_store
from .metrics import MetricsCollector, metrics_collector
from .traces import TraceCollector, trace_collector

__all__ = [
    "ABEvaluator",
    "ActiveLearningEngine",
    "CircuitBreaker",
    "DummyEmbedding",
    "EmbeddingProvider",
    "FeedbackEngine",
    "MemoryStore",
    "MetricsCollector",
    "OllamaEmbedding",
    "TraceCollector",
    "VectorStore",
    "ab_evaluator",
    "active_engine",
    "config",
    "feedback_engine",
    "memory_store",
    "metrics_collector",
    "safe_call",
    "safe_call_or",
    "trace_collector",
]
