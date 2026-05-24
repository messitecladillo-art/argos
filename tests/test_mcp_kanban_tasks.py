from __future__ import annotations

import hashlib
import json

from argos import mcp_server
from argos.models.store import RuntimeStore
from argos.services import mcp_installer


def _agent(
    agent_id: str,
    profile_name: str,
    role: str,
    workspace_path: str | None = None,
    description: str = "",
) -> dict:
    return {
        "agent_id": agent_id,
        "profile_name": profile_name,
        "name": profile_name.title(),
        "role": role,
        "description": description,
        "is_leader": role == "leader",
        "workspace_path": workspace_path or f"/tmp/{profile_name}",
        "status": "idle",
        "current_task": "空闲",
        "runtime_status": "running",
        "interaction_state": "idle",
        "orchestration_state": "none",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "readiness_status": "ready",
        "readiness_message": "",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }


def test_leader_creates_worker_kanban_tasks(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    workspace_path = tmp_path / "dev_profile"
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker", str(workspace_path)))
    task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=task["user_task_id"],
        kanban_task_id="kb_parent",
        kanban_role="parent",
    )
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []
    completed = []

    def fake_create_task(title, **kwargs):
        calls.append({"title": title, **kwargs})
        return {"task_id": f"kb_worker_{len(calls)}", "status": "ready"}

    def fake_complete_task(task_id, **kwargs):
        completed.append({"task_id": task_id, **kwargs})
        return "completed"

    monkeypatch.setattr(mcp_server.kanban_service, "create_task", fake_create_task, raising=False)
    monkeypatch.setattr(mcp_server.kanban_service, "complete_task", fake_complete_task, raising=False)

    result = mcp_server.create_kanban_worker_tasks(
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement", "title": "Implement API"}],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
        summary_instruction="Summarize",
    )

    assert result["ok"] is True
    assert result["parent_completed"] is True
    assert result["assignments"][0]["kanban_task_id"] == "kb_worker_1"
    assert calls[0]["assignee"] == "dev_profile"
    assert calls[0]["parent"] == "kb_parent"
    assert calls[0]["workspace"] == f"dir:{workspace_path}"
    assert calls[0]["idempotency_key"].startswith(f"user-task-worker:{task['user_task_id']}:round:1:agent_dev:")
    assert completed[0]["task_id"] == "kb_parent"
    assert completed[0]["metadata"]["dispatch_phase_completed"] is True
    assert completed[0]["metadata"]["round"] == 1
    assert runtime_store.find_kanban_task_link(kanban_task_id="kb_parent")["kanban_status"] == "done"
    assert workspace_path.is_dir()
    trace = runtime_store.get_trace_by_user_task(task["user_task_id"])
    assert trace is not None
    decomposition = json.loads(trace["decomposition_json"])
    assert decomposition["roles_used"] == ["worker"]
    allocations = json.loads(trace["allocations_json"])
    assert len(allocations) == 1
    assert allocations[0]["role"] == "worker"


def test_kanban_worker_task_creation_is_idempotent_for_user_task(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    workspace_path = tmp_path / "dev_profile"
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker", str(workspace_path)))
    task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=task["user_task_id"],
        kanban_task_id="kb_parent",
        kanban_role="parent",
    )
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []
    monkeypatch.setattr(
        mcp_server.kanban_service,
        "create_task",
        lambda title, **kwargs: calls.append({"title": title, **kwargs})
        or {"task_id": f"kb_worker_{len(calls)}", "status": "ready"},
        raising=False,
    )
    monkeypatch.setattr(mcp_server.kanban_service, "complete_task", lambda *args, **kwargs: "completed", raising=False)

    first = mcp_server.create_kanban_worker_tasks(
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement"}],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
    )
    second = mcp_server.create_kanban_worker_tasks(
        assignments=[{"to_agent_id": "agent_dev", "content": "Implement again"}],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["assignments"][0]["kanban_task_id"] == first["assignments"][0]["kanban_task_id"]
    assert len(calls) == 1


def test_worker_kanban_body_includes_role_output_requirements(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    leader_workspace = tmp_path / "lead"
    product_workspace = tmp_path / "product_profile"
    runtime_store.register_agent(
        _agent(
            "agent_product",
            "product_profile",
            "worker",
            str(product_workspace),
            description="负责整理需求。输出：PRD、功能清单、验收标准。",
        )
    )
    task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Plan product")
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []
    monkeypatch.setattr(
        mcp_server.kanban_service,
        "create_task",
        lambda title, **kwargs: calls.append({"title": title, **kwargs})
        or {"task_id": "kb_worker_1", "status": "ready"},
        raising=False,
    )
    monkeypatch.setattr(mcp_server.kanban_service, "complete_task", lambda *args, **kwargs: "completed", raising=False)

    mcp_server.create_kanban_worker_tasks(
        assignments=[
            {
                "to_agent_id": "agent_product",
                "content": f"整理登录功能需求，所有文档保存到 {leader_workspace}",
            }
        ],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
    )

    body = calls[0]["body"]
    assert f"当前 worker 工作区是：{product_workspace}" in body
    assert "所有产物必须写入当前 worker 工作区" in body
    assert "其他 agent 目录只能作为读取参考" in body
    assert str(leader_workspace) in body
    assert "你的 Agent 角色描述" in body
    assert "输出：PRD、功能清单、验收标准" in body
    assert "必须按其中列出的产物类型生成对应内容" in body
    assert "kanban_complete(summary=...) 中列出文件路径" in body


def test_review_can_dispatch_next_round_for_same_user_task(monkeypatch, tmp_path):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    workspace_path = tmp_path / "dev_profile"
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker", str(workspace_path)))
    task = runtime_store.create_user_task(leader_agent_id="agent_lead", content="Build")
    first = runtime_store.create_delegation(
        leader_agent_id="agent_lead",
        assignments=[{"to_agent_id": "agent_dev", "content": "Round 1"}],
        summary_instruction="Review",
        user_task_id=task["user_task_id"],
    )
    runtime_store.close_user_task_dispatch(task["user_task_id"])
    assignment = first["assignments"][0]
    runtime_store.complete_assignment(first["delegation_id"], assignment["assignment_id"], result="needs more")
    runtime_store.mark_user_task_reviewing(task["user_task_id"], review_task_id="kb_review_1")
    runtime_store.upsert_kanban_task_link(
        local_type="user_task",
        local_id=f"{task['user_task_id']}:round:1",
        kanban_task_id="kb_review_1",
        kanban_role="review",
        kanban_status="running",
        assignee_profile="lead",
        parent_local_id=task["user_task_id"],
        metadata={"user_task_id": task["user_task_id"], "round": 1},
    )
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []
    monkeypatch.setattr(
        mcp_server.kanban_service,
        "create_task",
        lambda title, **kwargs: calls.append({"title": title, **kwargs})
        or {"task_id": f"kb_worker_{len(calls)}", "status": "ready"},
        raising=False,
    )
    monkeypatch.setattr(mcp_server.kanban_service, "complete_task", lambda *args, **kwargs: "completed", raising=False)

    result = mcp_server.create_kanban_worker_tasks(
        assignments=[{"to_agent_id": "agent_dev", "content": "Round 2"}],
        from_agent_id="agent_lead",
        user_task_id=task["user_task_id"],
        parent_task_id="kb_review_1",
    )

    assert result["idempotent"] is False
    assert result["continuation"] is True
    assert result["round"] == 2
    assert runtime_store.find_user_task(task["user_task_id"])["current_round"] == 2
    assert calls[0]["parent"] == "kb_review_1"
    assert calls[0]["idempotency_key"].startswith(f"user-task-worker:{task['user_task_id']}:round:2:agent_dev:")


def test_list_workers_does_not_expose_workspace(monkeypatch):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker"))
    monkeypatch.setattr(mcp_server, "store", runtime_store)
    monkeypatch.setattr(mcp_installer, "mcp_summary", lambda profile_name: [])

    workers = mcp_server.list_workers()

    assert workers[0]["agent_id"] == "agent_dev"
    assert "workspace_path" not in workers[0]


def test_non_leader_cannot_create_kanban_tasks(monkeypatch):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_dev", "dev_profile", "worker"))
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    try:
        mcp_server.create_kanban_worker_tasks(
            assignments=[{"to_agent_id": "agent_dev", "content": "Implement"}],
            from_agent_id="agent_dev",
        )
    except ValueError as exc:
        assert "leader" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_agent_can_request_human_input_as_kanban_task(monkeypatch):
    runtime_store = RuntimeStore()
    runtime_store.register_agent(_agent("agent_lead", "lead", "leader"))
    monkeypatch.setattr(mcp_server, "store", runtime_store)

    calls = []

    def fake_create_task(title, **kwargs):
        calls.append({"title": title, **kwargs})
        return {"task_id": "kb_human_1", "status": "ready"}

    monkeypatch.setattr(mcp_server.kanban_service, "create_task", fake_create_task, raising=False)

    result = mcp_server.request_human_input(
        question="部署到生产前是否继续？",
        context="测试已通过，但需要用户确认上线窗口。",
        options=["继续", "暂停"],
        from_agent_id="agent_lead",
        parent_task_id="kb_parent",
        user_task_id="ut_1234",
    )

    assert result["ok"] is True
    assert result["status"] == "waiting_human"
    assert result["human_task_id"] == "kb_human_1"
    assert calls[0]["title"] == "人工处理：部署到生产前是否继续？"
    assert calls[0]["assignee"] is None
    assert calls[0]["parent"] == "kb_parent"
    expected_digest = hashlib.sha1("agent_lead\nkb_parent\nut_1234\n部署到生产前是否继续？".encode("utf-8")).hexdigest()[:12]
    assert calls[0]["idempotency_key"] == f"human-input:kb_parent:{expected_digest}"
    assert "部署到生产前是否继续？" in calls[0]["body"]
    link = runtime_store.find_kanban_task_link(kanban_task_id="kb_human_1")
    assert link["kanban_role"] == "human_input"
    assert link["kanban_status"] == "waiting_human"
    assert link["metadata"]["question"] == "部署到生产前是否继续？"
    assert link["metadata"]["requester_agent_id"] == "agent_lead"
    assert link["metadata"]["options"] == ["继续", "暂停"]
