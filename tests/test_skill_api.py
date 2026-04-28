from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Flask
from sqlalchemy import create_engine

from app.controllers import agents as agents_controller
from app.db.session import Base
from app.models.store import RuntimeStore
from sqlalchemy.orm import sessionmaker


def _client(monkeypatch, tmp_path):
    test_store = RuntimeStore()
    db_path = tmp_path / "skills-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(agents_controller, "store", test_store)
    monkeypatch.setattr(agents_controller.registry, "HERMES_HOME", tmp_path / ".hermes")
    monkeypatch.setattr(agents_controller.skill_installer, "HERMES_HOME", tmp_path / ".hermes")
    monkeypatch.setattr(agents_controller.skill_installer.registry, "HERMES_HOME", tmp_path / ".hermes")
    monkeypatch.setattr(agents_controller.skill_installer, "SessionLocal", session_local)
    monkeypatch.setattr(
        agents_controller.skill_installer,
        "_find_agent",
        lambda agent_id: test_store.find_agent(agent_id),
    )
    app = Flask(__name__)
    app.register_blueprint(agents_controller.bp)
    return app.test_client(), test_store


def _register_agent(store: RuntimeStore, profile_name: str = "dev") -> dict:
    agent = {
        "agent_id": f"agent_{profile_name}",
        "profile_name": profile_name,
        "name": "Dev",
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": "/tmp/dev",
        "status": "idle",
        "current_task": "空闲",
        "runtime_status": "stopped",
        "interaction_state": "idle",
        "orchestration_state": "none",
        "queue_depth": 0,
        "pending_interaction": None,
        "load": 0,
        "last_input": "",
        "last_output": "",
        "last_output_at": "",
        "readiness_status": "ready",
        "readiness_message": "SOUL.md 已就绪",
        "created_at": "2026-04-26T00:00:00Z",
        "last_active_at": "2026-04-26T00:00:00Z",
    }
    store.register_agent(agent)
    return agent


def test_list_agent_skills_reads_local_skill(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    skill_dir = agents_controller.registry.skills_dir_for("dev") / "local-demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: local-demo\ndescription: Local demo\n---\n\n# Local\n",
        encoding="utf-8",
    )

    response = client.get("/api/agents/agent_dev/skills")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skills"][0]["slug"] == "local-demo"
    assert data["skills"][0]["source_type"] == "local"


def test_list_agent_skills_reads_nested_local_skills(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    skill_dir = agents_controller.registry.skills_dir_for("dev") / "software-development" / "plan"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: plan\ndescription: Planning skill\n---\n\n# Plan\n",
        encoding="utf-8",
    )

    response = client.get("/api/agents/agent_dev/skills")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skills"][0]["slug"] == "software-development/plan"


def test_list_agent_skills_tolerates_invalid_frontmatter(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    bad_dir = agents_controller.registry.skills_dir_for("dev") / "broken-skill"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_text(
        "---\nname: broken-skill\ndescription: [broken\n---\n\n# Broken\n",
        encoding="utf-8",
    )

    response = client.get("/api/agents/agent_dev/skills")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skills"][0]["slug"] == "broken-skill"
    assert data["skills"][0]["error"].startswith("invalid frontmatter:")


def test_get_agent_skill_reads_body(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    skill_dir = agents_controller.registry.skills_dir_for("dev") / "local-demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: local-demo\ndescription: Local demo\n---\n\n# Local\n",
        encoding="utf-8",
    )

    response = client.get("/api/agents/agent_dev/skills/local-demo")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skill"]["frontmatter"]["name"] == "local-demo"
    assert "# Local" in data["skill"]["body"]


def test_get_agent_skill_reads_nested_body(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    skill_dir = agents_controller.registry.skills_dir_for("dev") / "apple" / "findmy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: findmy\ndescription: FindMy skill\n---\n\n# FindMy\n",
        encoding="utf-8",
    )

    response = client.get("/api/agents/agent_dev/skills/apple/findmy")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skill"]["slug"] == "apple/findmy"
    assert "# FindMy" in data["skill"]["body"]


def test_get_agent_skill_tolerates_invalid_frontmatter(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    skill_dir = agents_controller.registry.skills_dir_for("dev") / "broken-skill"
    skill_dir.mkdir(parents=True)
    content = "---\nname: broken-skill\ndescription: [broken\n---\n\n# Broken\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    response = client.get("/api/agents/agent_dev/skills/broken-skill")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["skill"]["slug"] == "broken-skill"
    assert data["skill"]["frontmatter"] == {}
    assert data["skill"]["body"] == content
    assert data["skill"]["error"].startswith("invalid frontmatter:")


def test_install_agent_skill_rejects_invalid_remote_frontmatter(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "clone", "--depth=1"]:
            repo_dir = Path(args[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "SKILL.md").write_text(
                "---\nname: broken-skill\ndescription: [broken\n---\n\n# Broken\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:4] == ["git", "-C", args[2], "rev-parse"]:
            return subprocess.CompletedProcess(args, 0, "deadbeef\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(agents_controller.skill_installer, "validate_source_url", lambda _url: None)
    monkeypatch.setattr(agents_controller.skill_installer.subprocess, "run", fake_run)

    response = client.post(
        "/api/agents/agent_dev/skills/install",
        json={"repo_url": "https://example.com/skill.git"},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"].startswith("invalid frontmatter:")


def test_install_agent_skill_requires_repo_url(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    response = client.post("/api/agents/agent_dev/skills/install", json={})

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "repo_url is required"


def test_install_agent_skill_accepts_source_url_alias(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    captured = {}

    def fake_install_from_git(agent_id, **kwargs):
        captured["agent_id"] = agent_id
        captured.update(kwargs)
        return {"slug": "demo-skill"}

    monkeypatch.setattr(agents_controller.skill_installer, "install_from_git", fake_install_from_git)

    response = client.post(
        "/api/agents/agent_dev/skills/install",
        json={"source_url": "https://example.com/skill.git"},
    )

    assert response.status_code == 201
    assert captured["repo_url"] == "https://example.com/skill.git"


def test_install_agent_skill_blank_ref_uses_remote_default_branch(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    clone_args = []

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "clone", "--depth=1"]:
            clone_args.extend(args)
            repo_dir = Path(args[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: Demo\n---\n\n# Demo\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "deadbeef\n", "")
        if args[-3:] == ["symbolic-ref", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "master\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(agents_controller.skill_installer, "validate_source_url", lambda _url: None)
    monkeypatch.setattr(agents_controller.skill_installer.subprocess, "run", fake_run)

    response = client.post(
        "/api/agents/agent_dev/skills/install",
        json={"repo_url": "https://example.com/skill.git", "ref": ""},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert "--branch" not in clone_args
    assert data["skill"]["source_ref"] == "master"


def test_install_agent_skill_auto_uses_only_nested_skill(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "clone", "--depth=1"]:
            repo_dir = Path(args[-1])
            skill_dir = repo_dir / "greet-with-model-version"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: greet-with-model-version\ndescription: Greet\n---\n\n# Greet\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "deadbeef\n", "")
        if args[-3:] == ["symbolic-ref", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "master\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(agents_controller.skill_installer, "validate_source_url", lambda _url: None)
    monkeypatch.setattr(agents_controller.skill_installer.subprocess, "run", fake_run)

    response = client.post(
        "/api/agents/agent_dev/skills/install",
        json={"repo_url": "https://example.com/skills.git"},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["skill"]["slug"] == "greet-with-model-version"
    assert data["skill"]["subdir"] == "greet-with-model-version"

    skills = client.get("/api/agents/agent_dev/skills").get_json()["skills"]
    assert skills[0]["subdir"] == "greet-with-model-version"

    reinstall_response = client.post(
        "/api/agents/agent_dev/skills/install",
        json={"repo_url": "https://example.com/skills.git"},
    )
    assert reinstall_response.status_code == 201


def test_uninstall_agent_skill_is_idempotent(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)

    response = client.delete("/api/agents/agent_dev/skills/missing-skill")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_uninstall_agent_skill_does_not_delete_namespace_dir(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    _register_agent(store)
    namespace_dir = agents_controller.registry.skills_dir_for("dev") / "software-development"
    plan_dir = namespace_dir / "plan"
    review_dir = namespace_dir / "review"
    plan_dir.mkdir(parents=True)
    review_dir.mkdir(parents=True)
    (plan_dir / "SKILL.md").write_text(
        "---\nname: plan\ndescription: Planning skill\n---\n\n# Plan\n",
        encoding="utf-8",
    )
    (review_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review skill\n---\n\n# Review\n",
        encoding="utf-8",
    )

    response = client.delete("/api/agents/agent_dev/skills/software-development")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert namespace_dir.exists()
    assert (plan_dir / "SKILL.md").exists()
    assert (review_dir / "SKILL.md").exists()
