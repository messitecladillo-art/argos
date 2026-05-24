from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from argos.db.models import AgentMcpServerRecord, AgentRecord, AgentSkillInstallRecord, MessageRecord
from argos.db.session import Base
from argos.models.store import RuntimeStore
from argos.services import transfer


@pytest.fixture()
def transfer_env(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    workspace_root = tmp_path / "agent_team"
    db_path = tmp_path / "transfer.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)

    modules = [
        transfer,
        transfer.registry,
        transfer.profiles,
        transfer.skill_installer,
        transfer.skill_installer.registry,
        transfer.mcp_installer,
        transfer.mcp_installer.profiles,
        transfer.mcp_installer.profiles,
        transfer.agents_service,
        transfer.agents_service.registry,
    ]
    for module in modules:
        if hasattr(module, "HERMES_HOME"):
            monkeypatch.setattr(module, "HERMES_HOME", hermes_home)
        if hasattr(module, "AGENT_TEAM_WORKSPACE_ROOT"):
            monkeypatch.setattr(module, "AGENT_TEAM_WORKSPACE_ROOT", workspace_root)
        if hasattr(module, "SessionLocal"):
            monkeypatch.setattr(module, "SessionLocal", session_local)

    monkeypatch.setattr(transfer.profiles, "check_hermes_ready", lambda: {"ok": True})
    monkeypatch.setattr(transfer.profiles, "create_hermes_profile", lambda profile_name: _make_profile(hermes_home, profile_name))
    monkeypatch.setattr(transfer.profiles, "delete_hermes_profile", lambda profile_name: _delete_profile(hermes_home, profile_name))
    monkeypatch.setattr(transfer.session_pool, "stop", lambda agent_id: None)
    monkeypatch.setattr(transfer.skill_installer, "install_from_git", lambda *args, **kwargs: {"ok": True})

    return hermes_home, workspace_root, session_local


def _make_profile(hermes_home: Path, profile_name: str) -> None:
    profile = hermes_home / "profiles" / profile_name
    profile.mkdir(parents=True, exist_ok=True)
    config = profile / "config.yaml"
    if not config.exists():
        config.write_text("model: gpt-test\napi_key: ${OPENAI_API_KEY}\n", encoding="utf-8")


def _delete_profile(hermes_home: Path, profile_name: str) -> None:
    import shutil

    shutil.rmtree(hermes_home / "profiles" / profile_name, ignore_errors=True)


def _seed_agent(session_local, hermes_home: Path, workspace_root: Path, profile_name: str = "leader"):
    profile = hermes_home / "profiles" / profile_name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "SOUL.md").write_text("# Soul\n", encoding="utf-8")
    (profile / "team-meta.json").write_text('{"name":"Leader"}', encoding="utf-8")
    (profile / "config.yaml").write_text(
        "model: old\napi_key: sk-testsecret123456\nmcp_servers:\n  docs:\n    url: http://127.0.0.1/mcp\n    headers:\n      Authorization: Bearer ****\n",
        encoding="utf-8",
    )
    skill_dir = profile / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n# Demo\n", encoding="utf-8")
    workspace = workspace_root / profile_name
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.txt").write_text("local", encoding="utf-8")
    with session_local.begin() as session:
        session.add(
            AgentRecord(
                agent_id=f"agent_{profile_name}",
                profile_name=profile_name,
                name="Leader",
                role="leader",
                description="boss",
                is_leader=True,
                workspace_path=str(workspace),
                status="busy",
                runtime_status="running",
                current_task="doing",
                load=77,
            )
        )
        session.add(
            AgentSkillInstallRecord(
                profile_name=profile_name,
                slug="demo",
                source_type="git",
                source_url="https://example.com/demo.git",
                source_ref="main",
                installed_at="old",
            )
        )
        session.add(
            AgentMcpServerRecord(
                profile_name=profile_name,
                name="docs",
                transport="http",
                source_type="manual",
                description="Docs",
                last_test_status="fail",
                last_error="boom",
            )
        )


def test_export_redacts_runtime_fields_and_secrets(transfer_env):
    hermes_home, workspace_root, session_local = transfer_env
    _seed_agent(session_local, hermes_home, workspace_root)

    archive = transfer.export_agents(["leader"], inline_skill_files=True, include_workspace=False)

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        meta = json.loads(zf.read("agents/leader/meta.json"))
        config = zf.read("agents/leader/profile/config.yaml").decode()
        secrets = zf.read("SECRETS.md").decode()
        manifest = json.loads(zf.read("manifest.json"))

    assert "agents/leader/profile/SOUL.md" in names
    assert "agents/leader/profile/skills/demo/SKILL.md" in names
    assert meta["profile_name"] == "leader"
    assert "runtime_status" not in meta
    assert "status" not in meta
    assert "sk-testsecret" not in config
    assert "${OPENAI_API_KEY}" in config
    assert "api_key" in secrets
    assert "MCP `docs`" in secrets
    assert "headers.Authorization" in secrets
    assert manifest["schema_version"] == 1
    assert manifest["agents"][0]["files"]["agents/leader/meta.json"].startswith("sha256:")


def test_inspect_rejects_tampered_checksum(transfer_env):
    hermes_home, workspace_root, session_local = transfer_env
    _seed_agent(session_local, hermes_home, workspace_root)
    archive = transfer.export_agents(["leader"], inline_skill_files=True, include_workspace=False)
    tampered = archive.with_name("tampered.zip")
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "agents/leader/meta.json":
                data = data.replace(b"Leader", b"Hacker")
            dst.writestr(item, data)

    with pytest.raises(transfer.TransferError, match="checksum mismatch"):
        transfer.inspect_archive(tampered)


def test_inspect_rejects_missing_required_agent_files(transfer_env, tmp_path):
    hermes_home, _workspace_root, _session_local = transfer_env
    archive = hermes_home / "tmp" / "broken.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    secrets_content = b"empty"
    manifest = {
        "schema_version": 1,
        "files": {"SECRETS.md": f"sha256:{hashlib.sha256(secrets_content).hexdigest()}"},
        "agents": [{"profile_name": "leader", "role": "leader", "is_leader": True}],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("SECRETS.md", secrets_content)

    with pytest.raises(transfer.TransferError, match="required file missing"):
        transfer.inspect_archive(archive)


def _write_archive_with_manifest(archive: Path, files: dict[str, bytes], agents: list[dict] | None = None) -> None:
    manifest = {
        "schema_version": 1,
        "files": {name: f"sha256:{hashlib.sha256(content).hexdigest()}" for name, content in files.items()},
        "agents": agents or [{"profile_name": "leader", "role": "leader", "is_leader": True}],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, content in files.items():
            zf.writestr(name, content)


def test_inspect_rejects_invalid_required_json(transfer_env):
    hermes_home, _workspace_root, _session_local = transfer_env
    archive = hermes_home / "tmp" / "invalid-json.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    _write_archive_with_manifest(
        archive,
        {
            "agents/leader/meta.json": b"not-json",
            "agents/leader/db/skill_installs.json": b"[]",
            "agents/leader/db/mcp_servers.json": b"[]",
        },
    )

    with pytest.raises(transfer.TransferError, match="invalid json file"):
        transfer.inspect_archive(archive)


def test_inspect_rejects_unmanifested_files(transfer_env):
    hermes_home, _workspace_root, _session_local = transfer_env
    archive = hermes_home / "tmp" / "extra-file.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "agents/leader/meta.json": b"{}",
        "agents/leader/db/skill_installs.json": b"[]",
        "agents/leader/db/mcp_servers.json": b"[]",
    }
    manifest = {
        "schema_version": 1,
        "files": {name: f"sha256:{hashlib.sha256(content).hexdigest()}" for name, content in files.items()},
        "agents": [{"profile_name": "leader", "role": "leader", "is_leader": True}],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, content in files.items():
            zf.writestr(name, content)
        zf.writestr("agents/leader/profile/SOUL.md", "unchecked")

    with pytest.raises(transfer.TransferError, match="unmanifested file"):
        transfer.inspect_archive(archive)


def test_inspect_rejects_invalid_skill_slug(transfer_env):
    hermes_home, _workspace_root, _session_local = transfer_env
    archive = hermes_home / "tmp" / "bad-skill-slug.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    _write_archive_with_manifest(
        archive,
        {
            "agents/leader/meta.json": b"{}",
            "agents/leader/db/skill_installs.json": b'[{"slug":"../../outside"}]',
            "agents/leader/db/mcp_servers.json": b"[]",
        },
    )

    with pytest.raises(transfer.TransferError, match="invalid skill slug"):
        transfer.inspect_archive(archive)


def test_import_clears_existing_and_restores_agent(transfer_env):
    hermes_home, workspace_root, session_local = transfer_env
    _seed_agent(session_local, hermes_home, workspace_root, "leader")
    archive = transfer.export_agents(["leader"], inline_skill_files=True, include_workspace=False)

    with session_local.begin() as session:
        session.add(
            AgentRecord(
                agent_id="agent_old",
                profile_name="old",
                name="Old",
                role="worker",
                workspace_path=str(workspace_root / "old"),
            )
        )
        session.add(MessageRecord(message_id="msg_1", to_agent_id="agent_old", content="old", created_at="now"))
    _make_profile(hermes_home, "old")
    (workspace_root / "old").mkdir(parents=True)
    store = RuntimeStore()
    store.register_agent({
        "agent_id": "agent_old",
        "profile_name": "old",
        "name": "Old",
        "role": "worker",
        "description": "",
        "is_leader": False,
        "workspace_path": str(workspace_root / "old"),
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
        "readiness_message": "",
        "created_at": "now",
        "last_active_at": "now",
    })

    result = transfer.import_archive(archive, store=store)

    assert result["ok"] is True
    assert result["results"][0]["agent_id"] == "agent_leader"
    assert not (hermes_home / "profiles" / "old").exists()
    assert not (workspace_root / "old").exists()
    assert (hermes_home / "profiles" / "leader" / "SOUL.md").exists()
    assert (hermes_home / "profiles" / "leader" / "skills" / "demo" / "SKILL.md").exists()
    with session_local() as session:
        agents = session.scalars(select(AgentRecord)).all()
        messages = session.scalars(select(MessageRecord)).all()
        skills = session.scalars(select(AgentSkillInstallRecord)).all()
        mcps = session.scalars(select(AgentMcpServerRecord)).all()
    assert [agent.profile_name for agent in agents] == ["leader"]
    assert agents[0].runtime_status == "stopped"
    assert agents[0].current_task == "空闲"
    assert messages == []
    assert skills[0].slug == "demo"
    assert mcps[0].name == "docs"
