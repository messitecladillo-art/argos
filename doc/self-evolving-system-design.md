# Self-Evolving Multi-Agent System — Design Document

## Overview

This document describes the self-evolving memory and learning system layered on top of Hermes Agent Team. It is Phase 1 (of 4) of the roadmap: the **Experience Memory System** — the data foundation that all higher-order evolution (dynamic agent factory, prompt evolution, meta-cognitive layer) depends on.

### Why Memory First

```
Memory System ──► Meta-Cognitive Layer ──► Dynamic Agent Factory
(data fuel)       (pattern analysis)       (autonomous evolution)
```

Without execution traces, nothing can be analyzed. Without analysis, nothing can evolve.

---

## Architecture

```
                         ┌──────────────────────┐
                         │   Web UI / SSE / WS  │
                         └──────────┬───────────┘
                                    │
┌───────────────────────────────────┼───────────────────────────────┐
│                        Flask + Uvicorn (ASGI)                     │
│                                                                   │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │Controllers│  │ Services  │  │ Kanban       │  │ MCP Server  │ │
│  └─────┬─────┘  └─────┬─────┘  │ Dispatch     │  └─────────────┘ │
│        │              │        └──────────────┘                  │
│        │     ┌────────┴────────┐                                  │
│        │     │  NEW: Learning  │  ◄── 本设计新增                   │
│        │     │  ┌───────────┐  │                                  │
│        │     │  │  traces   │  │  ExecutionTrace 收集             │
│        │     │  │  memory   │  │  经验记忆 存储 & 检索             │
│        │     │  │  feedback │  │  隐式反馈 提取                    │
│        │     │  │  embeddings│ │  向量嵌入 生成                    │
│        │     │  └───────────┘  │                                  │
│        │     └────────────────┘                                   │
│        │              │                                           │
│  ┌─────┴──────────────┴────────────┐                              │
│  │     RuntimeStore (in-memory)    │                              │
│  │     + SQLitePersistence         │                              │
│  │     + NEW: LanceDB (vectors)    │                              │
│  └─────────────────────────────────┘                              │
└───────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Non-invasive**: Existing task flows work unchanged if learning module is disabled
2. **Observe, don't intercept**: Traces are collected by observing events, not by modifying dispatch logic
3. **Offline analysis**: Feedback extraction and memory consolidation happen asynchronously
4. **Gradual adoption**: System works with zero memories (cold start), improves with each task

---

## Module Structure

```
app/
├── learning/                    # NEW: self-evolving system
│   ├── __init__.py              # Public API surface
│   ├── traces.py                # ExecutionTrace collector
│   ├── memory.py                # Memory store & retrieval
│   ├── feedback.py              # Signal extraction engine
│   └── embeddings.py            # Embedding provider abstraction
├── db/
│   ├── models.py                # EXISTING + new ORM models
│   ├── migrations.py            # EXISTING + new migration
│   └── ...
└── ...
```

---

## Layer 1: ExecutionTrace — The Data Fuel

### Concept

Every time the Leader Agent processes a user task, we capture the **full decision chain**: how it decomposed, what context it used, who it assigned, what happened, and how the user reacted.

### Data Model

```
ExecutionTrace
├── trace_id: str (PK)
├── user_task_id: str (FK → user_tasks)
├── leader_agent_id: str (FK → agents)
├── phase: "decompose" | "execute" | "review" | "complete"
│
├── decomposition: JSON
│   ├── strategy: "sequential" | "parallel" | "pipeline"
│   ├── num_subtasks: int
│   ├── roles_used: [str]
│   └── reasoning: str (leader's own explanation)
│
├── context_plan: JSON
│   ├── total_tokens_estimate: int
│   ├── files_provided: [str]
│   └── selection_method: "keyword" | "dependency_graph" | "agent_requested"
│
├── allocations: JSON (array)
│   └── [{agent_id, role, assignment_id, context_summary, token_count}]
│
├── decisions: JSON (array)
│   └── [{timestamp, decision_point, options, chosen, reasoning}]
│
├── outcome: JSON
│   ├── status: "completed" | "blocked" | "failed"
│   ├── rounds_used: int
│   ├── total_duration_seconds: float
│   ├── worker_results_count: int
│   └── leader_summary: str
│
├── quality_signals: JSON (populated by feedback engine)
│   ├── success_score: 0.0 - 1.0
│   ├── efficiency_score: 0.0 - 1.0
│   └── user_satisfaction: 0.0 - 1.0
│
└── timestamps: {created_at, completed_at}
```

### Collection Strategy

Traces are collected **passively** by hooking into existing event and state-change flows:

```
Existing Event           →  Trace Action
─────────────────────────────────────────────
user_task created        →  Create trace row (phase=decompose)
leader creates kanban    →  Record decomposition + context_plan
  worker tasks
assignment dispatched    →  Record allocation entry
worker completes         →  Record allocation result
leader reviews           →  Record review decision
user_task completed      →  Finalize trace, compute outcome
```

No existing service code is modified. A new `TraceCollector` service subscribes to RuntimeStore events.

### DB Schema Addition

```sql
CREATE TABLE execution_traces (
    id INTEGER PRIMARY KEY,
    trace_id VARCHAR(80) UNIQUE NOT NULL,
    user_task_id VARCHAR(80) NOT NULL,
    leader_agent_id VARCHAR(120) NOT NULL,
    phase VARCHAR(40) DEFAULT 'decompose',
    decomposition_json TEXT DEFAULT '{}',
    context_plan_json TEXT DEFAULT '{}',
    allocations_json TEXT DEFAULT '[]',
    decisions_json TEXT DEFAULT '[]',
    outcome_json TEXT DEFAULT '{}',
    quality_json TEXT DEFAULT '{}',
    created_at VARCHAR(40),
    completed_at VARCHAR(40),
    db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_traces_task ON execution_traces(user_task_id);
CREATE INDEX idx_traces_leader ON execution_traces(leader_agent_id);
```

---

## Layer 2: Experience Memory — The Knowledge Base

### Three-Layer Memory Architecture

```
Layer 1: Strategic Memory (策略记忆)
  "这类任务的最优分解策略是什么"
  生命周期: 长期，跨项目持久化
  用途: 注入到 Leader 的任务分解 prompt 中

Layer 2: Tactical Memory (战术记忆)
  "这个项目的认证逻辑在哪些文件里"
  生命周期: 项目级别，跟随 workspace
  用途: 注入到 Agent 的上下文选择中

Layer 3: Operational Memory (操作记忆)
  "上次改 models.py 忘了跑 migration 导致问题"
  生命周期: 短期，带 TTL 过期
  用途: 作为警告/约束注入到 worker 的执行 prompt
```

### MemoryItem Data Model

```
MemoryItem
├── memory_id: str (PK)
├── layer: "strategic" | "tactical" | "operational"
├── type: "pattern" | "fact" | "constraint" | "preference" | "pitfall"
│
├── content: str               # NL description, queryable
├── embedding: BLOB/JSON       # vector for similarity search
│
├── source_trace_ids: [str]    # provenance — which traces produced this
├── consolidation_count: int   # how many traces reinforced this
│
├── weight: float (0.0-1.0)    # dynamically adjusted
├── use_count: int
├── success_count: int         # times retrieval led to good outcome
│
├── scope: "global" | "project" | "agent"
├── project_path: str|null     # for project-scoped memories
│
├── metadata_json: TEXT
├── created_at: str
├── last_used_at: str
├── expires_at: str|null       # TTL for operational memories
└── deleted_at: str|null       # soft delete
```

### Memory Consolidation

Memories are NOT created 1:1 from traces. They are **consolidated**:

```
Trace 1: "refactored auth, explored auth/ first, success, user accepted"
Trace 2: "refactored auth, skipped exploration, failed, user redid"
Trace 3: "refactored payment, explored first, success"
         ↓
Consolidated Strategic Memory:
  "For refactoring tasks involving >1 module, pre-exploration
   increases success rate. Recommended: explore first."
  weight: 0.82, consolidation_count: 3
```

Consolidation runs asynchronously, triggered after every N new traces (default N=5).

### Retrieval API

```python
class MemoryRetrieval:
    def retrieve(
        self,
        task_description: str,      # current task
        layer: str | None = None,   # optional filter
        top_k: int = 5,
        min_weight: float = 0.3,
    ) -> list[MemoryItem]:
        """
        Returns top-K relevant memories for the given task.
        Memories are ranked by: similarity(task, memory) × weight
        """
        ...

    def inject_into_context(
        self,
        task_description: str,
        target: "leader_decompose" | "worker_execute" | "leader_review",
    ) -> str:
        """
        Returns a formatted string of relevant memories
        ready to inject into the agent's system prompt.
        """
        ...
```

### DB Schema Addition

```sql
CREATE TABLE memory_items (
    id INTEGER PRIMARY KEY,
    memory_id VARCHAR(80) UNIQUE NOT NULL,
    layer VARCHAR(40) NOT NULL,
    type VARCHAR(40) NOT NULL,
    content TEXT NOT NULL,
    embedding_json TEXT,            -- JSON array of floats
    source_trace_ids_json TEXT DEFAULT '[]',
    consolidation_count INTEGER DEFAULT 1,
    weight REAL DEFAULT 0.5,
    use_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    scope VARCHAR(40) DEFAULT 'project',
    project_path VARCHAR(500),
    metadata_json TEXT DEFAULT '{}',
    created_at VARCHAR(40),
    last_used_at VARCHAR(40),
    expires_at VARCHAR(40),
    deleted_at VARCHAR(40),
    db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_memory_layer ON memory_items(layer);
CREATE INDEX idx_memory_type ON memory_items(type);
CREATE INDEX idx_memory_scope ON memory_items(scope);
CREATE INDEX idx_memory_weight ON memory_items(weight);
CREATE INDEX idx_memory_project ON memory_items(project_path);
```

### Vector Storage Decision

For Phase 1, embeddings are stored as JSON arrays in SQLite (the `embedding_json` column). This avoids adding a new dependency (ChromaDB/LanceDB) while the system is being validated. A simple cosine-similarity search scans all candidates with a weight filter.

**Migration path**: When memory count exceeds ~10,000, the `embeddings.py` abstraction allows swapping SQLite for LanceDB without changing MemoryRetrieval's interface.

---

## Layer 3: Feedback Signals — The Learning Fuel

### Signal Types

| Signal | Source | Strength | Extraction Method |
|--------|--------|----------|-------------------|
| **accept** | User accepts code as-is | +0.8 to +1.0 | Check if next message is a new task (no modification) |
| **modify_light** | User modifies <20% | +0.3 to +0.7 | Git diff analysis between agent output and final commit |
| **modify_heavy** | User modifies >50% | -0.3 to -0.7 | Same, higher threshold |
| **redo** | User asks "redo" / "again" | -0.8 | Pattern match in subsequent user message |
| **undo** | User reverts agent changes | -1.0 | Git revert detection |
| **hesitate** | Long pause before next action | -0.2 | Time gap between agent output and user response |
| **explicit** | User provides rating/feedback | direct | Parse explicit feedback messages |

### Feedback Flow

```
Agent output ──► User action ──► FeedbackExtractor ──► Signal stored
                                           │
                                           ▼
                              Memory weight adjustment:
                              - Positive signal → weight += Δ
                              - Negative signal → weight -= Δ
                              - weight decays by 5% if unused for 30d
```

### DB Schema Addition

```sql
CREATE TABLE feedback_signals (
    id INTEGER PRIMARY KEY,
    signal_id VARCHAR(80) UNIQUE NOT NULL,
    trace_id VARCHAR(80) NOT NULL,
    assignment_id VARCHAR(80),       -- nullable, task-level signals exist
    signal_type VARCHAR(40) NOT NULL,
    strength REAL NOT NULL,           -- -1.0 to 1.0
    detail_json TEXT DEFAULT '{}',    -- {modification_ratio, redo_count, etc}
    extracted_at VARCHAR(40),
    db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_feedback_trace ON feedback_signals(trace_id);
CREATE INDEX idx_feedback_type ON feedback_signals(signal_type);
```

---

## Integration Points

### 1. Trace Collection — hooks into existing services

```python
# app/services/chat.py — after dispatch completes
from app.learning.traces import trace_collector
trace_collector.record_allocation_result(assignment_id, result, status)

# app/services/kanban_sync.py — when task status changes  
from app.learning.traces import trace_collector
trace_collector.record_task_phase_change(user_task_id, new_phase)
```

The `trace_collector` singleton observes state transitions. If `learning.enabled = False`, all calls are no-ops.

### 2. Memory Injection — into agent prompts

```python
# In the Leader's MCP tool: mcp_agent_bus_create_kanban_worker_tasks
# Before decomposition, retrieve relevant strategic memories
from app.learning.memory import memory_store
relevant = memory_store.retrieve(task_content, layer="strategic", top_k=3)
context_hint = memory_store.inject_into_context(task_content, "leader_decompose")
```

### 3. Feedback Extraction — scheduled background job

```python
# Runs every 5 minutes, processes completed-but-unanalyzed traces
from app.learning.feedback import feedback_engine
feedback_engine.extract_signals_for_completed_traces()
```

---

## Cold Start Strategy

The system ships with **seed memories** — high-quality patterns extracted from real usage of the core team:

```python
SEED_STRATEGIC_MEMORIES = [
    {
        "content": "For tasks involving >3 source files, use exploration-first strategy: "
                   "assign an explorer agent to map dependencies before assigning implementation work.",
        "layer": "strategic",
        "weight": 0.7,
        "scope": "global",
    },
    {
        "content": "When the user describes a 'refactoring' task, always start with a codebase "
                   "exploration step before proposing architectural changes.",
        "layer": "strategic",
        "weight": 0.75,
        "scope": "global",
    },
    # ... more seeds
]
```

Seed weights start at 0.7 (confident but adjustable). After 50+ real traces, real experiences dominate seeds.

---

## Success Metrics

| Metric | How to Measure | Target (3 months) |
|--------|---------------|-------------------|
| Task completion rate | completed / total user tasks | +15% vs baseline (no memory) |
| Rounds per task | average rounds needed | -25% (fewer review rounds) |
| User modification rate | average % of code user changes | -20% (closer to user intent) |
| Memory hit rate | % of retrievals that influenced decisions | >60% |
| Cold start latency | time to first measurable improvement | <10 tasks |

---

## Implementation Plan

### Week 1-2: Core Data Layer
- [ ] Add ORM models: ExecutionTrace, MemoryItem, FeedbackSignal
- [ ] DB migration
- [ ] `app/learning/` package scaffold
- [ ] TraceCollector with event hooks

### Week 3-5: Memory System
- [ ] MemoryItem CRUD in RuntimeStore
- [ ] Embedding provider (sentence-transformers via Ollama embedding API)
- [ ] Similarity retrieval
- [ ] Memory consolidation (basic: pattern clustering)
- [ ] Context injection formatter

### Week 6-7: Feedback Engine
- [ ] Signal extraction from existing message/event data
- [ ] Weight adjustment algorithm
- [ ] Seed memory population

### Week 8: Integration & Validation
- [ ] Wire into Leader decomposition flow
- [ ] End-to-end test with real tasks
- [ ] Dashboard showing memory stats

---

## Appendix: Key Design Decisions

### Why SQLite for embeddings (Phase 1)?

LanceDB/ChromaDB add operational complexity. For <10K memories, brute-force cosine similarity over JSON arrays in SQLite is ~50ms — acceptable for a system that retrieves memories once per task decomposition, not per chat turn.

### Why separate trace table instead of enriching existing EventRecord?

EventRecord captures "what happened." ExecutionTrace captures "was it a good decision." Mixing them would bloat the hot event path. Traces are written once per task (not per event), keeping overhead minimal.

### Why consolidation instead of 1:1 trace→memory?

Single traces are noisy. Pattern emerges from aggregation. Consolidation extracts the signal from the noise.
