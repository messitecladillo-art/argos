from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import socket
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select

from ..config import AGENT_TEAM_WORKSPACE_ROOT, HERMES_HOME, PROFILE_NAME_RE, now_iso
from ..db.models import (
    AgentMcpServerRecord,
    AgentRecord,
    AgentSkillInstallRecord,
    AssignmentRecord,
    DelegationRecord,
    EventRecord,
    MessageRecord,
    UserTaskRecord,
)
from ..db.session import SessionLocal
from ..models.store import RuntimeStore
from . import agents as agents_service
from . import mcp_installer, profiles, registry, skill_installer
from .acp import pool as session_pool


SCHEMA_VERSION = 1
EXPORT_SUFFIX = ".zip"
PROFILE_FILES = ("SOUL.md", "team-meta.json", "config.yaml")
PROFILE_DIRS = ("memories",)
RUNTIME_AGENT_FIELDS = {
    "id",
    "status",
    "runtime_status",
    "interaction_state",
    "orchestration_state",
    "queue_depth",
    "pending_interaction_json",
    "load",
    "last_input",
    "last_output",
    "last_output_at",
    "readiness_status",
    "readiness_message",
    "last_active_at",
    "created_at",
    "updated_at",
    "deleted_at",
    "db_created_at",
    "db_updated_at",
}
RUNTIME_TABLES = (
    AssignmentRecord,
    DelegationRecord,
    UserTaskRecord,
    MessageRecord,
    EventRecord,
)
SECRET_LINE_RE = re.compile(r"^(?P<prefix>\s*api_key\s*:\s*)(?P<value>.+?)\s*$", re.IGNORECASE)
PLAIN_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


class TransferError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Archive:
    root: Path
    manifest: dict[str, Any]


def export_agents(
    profile_names: list[str],
    *,
    inline_skill_files: bool,
    include_workspace: bool = False,
) -> Path:
    names = _clean_profile_names(profile_names)
    export_root = _tmp_dir("export")
    secrets: list[str] = []
    try:
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": now_iso(),
            "source_host": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
            },
            "options": {
                "inline_skill_files": bool(inline_skill_files),
                "include_workspace": bool(include_workspace),
            },
            "agents": [],
        }
        for profile_name in names:
            agent = _load_agent_record(profile_name)
            if agent is None:
                raise TransferError(f"profile not found: {profile_name}")
            agent_root = export_root / "agents" / profile_name
            profile_root = agent_root / "profile"
            (agent_root / "db").mkdir(parents=True, exist_ok=True)
            profile_root.mkdir(parents=True, exist_ok=True)

            meta = _agent_record_to_export(agent)
            _write_json(agent_root / "meta.json", meta)
            skill_rows = [_record_to_dict(row) for row in _load_skill_records(profile_name)]
            mcp_rows = _mcp_rows_for_export(profile_name, secrets)
            _write_json(agent_root / "db" / "skill_installs.json", skill_rows)
            _write_json(agent_root / "db" / "mcp_servers.json", mcp_rows)
            _copy_profile_files(profile_name, profile_root, inline_skill_files, secrets)
            if include_workspace:
                _copy_workspace(profile_name, agent_root / "workspace")
            manifest["agents"].append(
                {
                    "profile_name": profile_name,
                    "agent_id": agent.agent_id,
                    "role": agent.role,
                    "is_leader": bool(agent.is_leader),
                    "files": {},
                    "skills": [
                        {
                            "slug": item.get("slug"),
                            "source_type": item.get("source_type"),
                            "inline": bool(inline_skill_files),
                        }
                        for item in skill_rows
                    ],
                    "mcp_servers": [
                        {"name": item.get("name"), "transport": item.get("transport")}
                        for item in mcp_rows
                    ],
                }
            )
        _write_readme(export_root)
        _write_secrets(export_root, secrets)
        checksums = _checksums(export_root)
        for agent in manifest["agents"]:
            prefix = f"agents/{agent['profile_name']}/"
            agent["files"] = {k: v for k, v in checksums.items() if k.startswith(prefix)}
        manifest["files"] = checksums
        _write_json(export_root / "manifest.json", manifest)
        timestamp = now_iso()[0:16].replace("-", "").replace("T", "-").replace(":", "")
        archive_path = HERMES_HOME / "tmp" / f"argos-{timestamp}{EXPORT_SUFFIX}"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        _zip_dir(export_root, archive_path)
        return archive_path
    finally:
        shutil.rmtree(export_root, ignore_errors=True)


def inspect_archive(zip_path: Path) -> dict:
    archive = _open_archive(zip_path)
    try:
        deleted_agents = _current_agent_count()
        manifest = archive.manifest
        return {
            "ok": True,
            "manifest": manifest,
            "agents": manifest.get("agents", []),
            "will_clear": {
                "agents": deleted_agents,
                "workspaces": deleted_agents,
                "history_tables": ["messages", "events", "user_tasks", "delegations", "assignments"],
            },
            "missing_secrets": _read_secrets(archive.root),
        }
    finally:
        shutil.rmtree(archive.root, ignore_errors=True)


def import_archive(zip_path: Path, *, store: RuntimeStore | None = None) -> dict:
    from ..models.store import store as default_store

    target_store = store or default_store
    ready = profiles.check_hermes_ready()
    if not ready.get("ok"):
        raise TransferError(ready.get("message") or "Hermes CLI 未就绪", status_code=412)
    archive = _open_archive(zip_path)
    results: list[dict] = []
    try:
        _clear_local_state(target_store)
        for item in archive.manifest.get("agents", []):
            profile_name = item.get("profile_name") or ""
            try:
                result = _import_one_agent(archive.root, profile_name, target_store)
            except Exception as exc:  # noqa: BLE001
                _rollback_profile(profile_name, target_store)
                results.append({"profile_name": profile_name, "success": False, "error": str(exc)})
            else:
                results.append(result)
        target_store.push_agents_changed()
        target_store.push_event(
            "agent.imported",
            "system",
            None,
            {"text": f"团队导入完成：{sum(1 for r in results if r.get('success'))}/{len(results)} 成功"},
        )
        return {"ok": True, "results": results, "missing_secrets": _read_secrets(archive.root)}
    finally:
        shutil.rmtree(archive.root, ignore_errors=True)


def _clean_profile_names(profile_names: list[str]) -> list[str]:
    names = [str(name or "").strip() for name in profile_names]
    names = [name for name in dict.fromkeys(names) if name]
    if not names:
        raise TransferError("profile_names is required")
    for name in names:
        if not PROFILE_NAME_RE.fullmatch(name):
            raise TransferError(f"invalid profile_name: {name}")
    return names


def _tmp_dir(prefix: str) -> Path:
    root = HERMES_HOME / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=root))


def _load_agent_record(profile_name: str) -> AgentRecord | None:
    with SessionLocal() as session:
        return session.scalar(
            select(AgentRecord).where(
                AgentRecord.profile_name == profile_name,
                AgentRecord.deleted_at.is_(None),
            )
        )


def _load_skill_records(profile_name: str) -> list[AgentSkillInstallRecord]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(AgentSkillInstallRecord).where(AgentSkillInstallRecord.profile_name == profile_name)
            )
        )


def _load_mcp_records(profile_name: str) -> list[AgentMcpServerRecord]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(AgentMcpServerRecord).where(AgentMcpServerRecord.profile_name == profile_name)
            )
        )


def _record_to_dict(record: Any) -> dict[str, Any]:
    payload = {}
    for column in record.__table__.columns:
        if column.name in {"id", "db_created_at", "db_updated_at"}:
            continue
        payload[column.name] = getattr(record, column.name)
    return payload


def _agent_record_to_export(record: AgentRecord) -> dict[str, Any]:
    payload = _record_to_dict(record)
    for field in RUNTIME_AGENT_FIELDS:
        payload.pop(field, None)
    payload["current_task"] = "空闲"
    return payload


def _mcp_rows_for_export(profile_name: str, secrets: list[str]) -> list[dict[str, Any]]:
    try:
        config = profiles.read_profile_config(profile_name)
    except Exception:  # noqa: BLE001
        config = {}
    servers = config.get("mcp_servers") if isinstance(config, dict) else {}
    rows = []
    for record in _load_mcp_records(profile_name):
        row = _record_to_dict(record)
        for key in ("last_test_status", "last_test_at", "last_error"):
            row[key] = ""
        if isinstance(servers, dict):
            spec = servers.get(record.name) or {}
            row["spec"] = spec
            row["missing_secret_keys"] = _mcp_missing_secret_keys(profile_name, record.name, spec)
            for item in row["missing_secret_keys"]:
                secrets.append(f"- `{profile_name}` MCP `{record.name}` 需要在目标机补齐：`{item}`")
        rows.append(row)
    return rows


def _mcp_missing_secret_keys(profile_name: str, name: str, spec: dict) -> list[str]:
    missing: list[str] = []
    headers = spec.get("headers") if isinstance(spec, dict) else None
    if isinstance(headers, dict):
        for key in headers:
            if mcp_installer.SECRET_KEY_RE.search(str(key)):
                missing.append(f"headers.{key}")
    env = spec.get("env") if isinstance(spec, dict) else None
    if isinstance(env, dict):
        for key in env:
            if mcp_installer.SECRET_KEY_RE.search(str(key)):
                missing.append(f"env.{key}")
    return missing


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_profile_files(profile_name: str, target: Path, inline_skill_files: bool, secrets: list[str]) -> None:
    source = HERMES_HOME / "profiles" / profile_name
    if not source.exists():
        raise TransferError(f"profile directory not found: {profile_name}")
    for filename in PROFILE_FILES:
        src = source / filename
        if not src.exists():
            continue
        dst = target / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        if filename == "config.yaml":
            dst.write_text(_redact_config(src.read_text(encoding="utf-8"), profile_name, secrets), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
    for dirname in PROFILE_DIRS:
        src = source / dirname
        if src.exists():
            shutil.copytree(src, target / dirname, dirs_exist_ok=True, symlinks=True)
    if inline_skill_files and (source / "skills").exists():
        shutil.copytree(source / "skills", target / "skills", dirs_exist_ok=True, symlinks=True)


def _copy_workspace(profile_name: str, target: Path) -> None:
    source = registry.workspace_path_for(profile_name)
    if source.exists():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("node_modules", ".venv", "__pycache__", ".git"),
        )


def _redact_config(content: str, profile_name: str, secrets: list[str]) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        match = SECRET_LINE_RE.match(line)
        if not match:
            lines.append(PLAIN_OPENAI_KEY_RE.sub("${OPENAI_API_KEY}", line))
            continue
        value = match.group("value").strip().strip('"\'')
        if value.startswith("${") or not value:
            lines.append(line)
            continue
        secrets.append(f"- `{profile_name}`: config.yaml 中的 api_key 已替换为 `${{OPENAI_API_KEY}}`")
        lines.append(f"{match.group('prefix')}${{OPENAI_API_KEY}}")
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def _write_readme(root: Path) -> None:
    (root / "README.txt").write_text(
        "Argos export. Use the web UI import dialog or /api/transfer/import to restore.\n",
        encoding="utf-8",
    )


def _write_secrets(root: Path, secrets: list[str]) -> None:
    content = "# 需要重新配置的凭据\n\n"
    content += "未检测到明文凭据。\n" if not secrets else "\n".join(dict.fromkeys(secrets)) + "\n"
    (root / "SECRETS.md").write_text(content, encoding="utf-8")


def _checksums(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(root).as_posix()
        files[rel] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    return files


def _zip_dir(root: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())


def _open_archive(zip_path: Path) -> _Archive:
    root = _tmp_dir("import")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                dest = (root / member.filename).resolve(strict=False)
                if root.resolve(strict=False) != dest and root.resolve(strict=False) not in dest.parents:
                    raise TransferError("zip contains unsafe path")
                zf.extract(member, root)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise TransferError("invalid zip archive") from exc
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise TransferError("manifest.json is missing or invalid") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        shutil.rmtree(root, ignore_errors=True)
        raise TransferError("unsupported schema_version")
    _validate_manifest(root, manifest)
    return _Archive(root=root, manifest=manifest)


def _validate_manifest(root: Path, manifest: dict[str, Any]) -> None:
    expected = manifest.get("files") or {}
    if not isinstance(expected, dict) or not expected:
        raise TransferError("manifest files is invalid")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    extra_files = sorted(set(actual_files) - set(expected))
    if extra_files:
        raise TransferError(f"archive contains unmanifested file: {extra_files[0]}")
    for rel, checksum in expected.items():
        path = root / rel
        if not path.is_file():
            raise TransferError(f"archive file missing: {rel}")
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if actual != checksum:
            raise TransferError(f"checksum mismatch: {rel}")
    agents = manifest.get("agents")
    if not isinstance(agents, list) or not agents:
        raise TransferError("archive contains no agents")
    for agent in agents:
        profile_name = str(agent.get("profile_name") or "")
        if not PROFILE_NAME_RE.fullmatch(profile_name):
            raise TransferError(f"invalid profile_name in archive: {profile_name}")
        required_files = (
            f"agents/{profile_name}/meta.json",
            f"agents/{profile_name}/db/skill_installs.json",
            f"agents/{profile_name}/db/mcp_servers.json",
        )
        for rel in required_files:
            if rel not in expected:
                raise TransferError(f"archive required file missing from manifest: {rel}")
            if not (root / rel).is_file():
                raise TransferError(f"archive required file missing: {rel}")
        _validate_agent_payload_files(root, profile_name)


def _validate_agent_payload_files(root: Path, profile_name: str) -> None:
    meta = _read_json_file(root / "agents" / profile_name / "meta.json", f"agents/{profile_name}/meta.json")
    if not isinstance(meta, dict):
        raise TransferError(f"agent meta must be an object: {profile_name}")
    skills = _read_json_file(
        root / "agents" / profile_name / "db" / "skill_installs.json",
        f"agents/{profile_name}/db/skill_installs.json",
    )
    if not isinstance(skills, list):
        raise TransferError(f"agent skill_installs must be a list: {profile_name}")
    for item in skills:
        if not isinstance(item, dict):
            raise TransferError(f"agent skill install must be an object: {profile_name}")
        _validate_import_skill_slug(str(item.get("slug") or ""), profile_name)
    mcps = _read_json_file(
        root / "agents" / profile_name / "db" / "mcp_servers.json",
        f"agents/{profile_name}/db/mcp_servers.json",
    )
    if not isinstance(mcps, list):
        raise TransferError(f"agent mcp_servers must be a list: {profile_name}")
    if any(not isinstance(item, dict) for item in mcps):
        raise TransferError(f"agent mcp server must be an object: {profile_name}")


def _read_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferError(f"invalid json file: {label}") from exc


def _validate_import_skill_slug(slug: str, profile_name: str) -> str:
    try:
        return skill_installer._validate_skill_locator(slug)
    except Exception as exc:  # noqa: BLE001
        raise TransferError(f"invalid skill slug for {profile_name}: {slug}") from exc


def _current_agent_count() -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(AgentRecord).where(AgentRecord.deleted_at.is_(None))) or 0


def _read_secrets(root: Path) -> list[str]:
    path = root / "SECRETS.md"
    if not path.exists():
        return []
    return [line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def _clear_local_state(store: RuntimeStore) -> None:
    agents_by_id = {agent["agent_id"]: dict(agent) for agent in store.snapshot().get("agents", [])}
    with SessionLocal() as session:
        for record in session.scalars(select(AgentRecord).where(AgentRecord.deleted_at.is_(None))):
            agents_by_id.setdefault(
                record.agent_id,
                {
                    "agent_id": record.agent_id,
                    "profile_name": record.profile_name,
                    "workspace_path": record.workspace_path or str(registry.workspace_path_for(record.profile_name)),
                },
            )
    for agent in list(agents_by_id.values()):
        try:
            session_pool.stop(agent["agent_id"])
        except Exception:  # noqa: BLE001
            pass
        profile_name = agent.get("profile_name") or ""
        if profile_name:
            try:
                profiles.delete_hermes_profile(profile_name)
            except Exception as exc:  # noqa: BLE001
                raise TransferError(f"delete profile failed: {profile_name}: {exc}") from exc
            mcp_installer.delete_records_for_profile(profile_name)
            agents_service._delete_workspace(agent.get("workspace_path") or registry.workspace_path_for(profile_name))
        store.remove_agent(agent["agent_id"])
    with SessionLocal.begin() as session:
        session.query(AgentSkillInstallRecord).delete()
        session.query(AgentMcpServerRecord).delete()
        session.query(AgentRecord).delete()
        for model in RUNTIME_TABLES:
            session.query(model).delete()
    with store._lock:
        store.agents = []
        store.user_tasks = []
        store.delegations = []
        store.messages.clear()
        store.events.clear()


def _import_one_agent(root: Path, profile_name: str, store: RuntimeStore) -> dict:
    agent_root = root / "agents" / profile_name
    meta = json.loads((agent_root / "meta.json").read_text(encoding="utf-8"))
    profiles.create_hermes_profile(profile_name)
    profile_target = HERMES_HOME / "profiles" / profile_name
    profile_source = agent_root / "profile"
    existing_config = _safe_read_yaml(profile_target / "config.yaml")
    _copy_imported_profile(profile_source, profile_target)
    imported_config = _safe_read_yaml(profile_source / "config.yaml")
    if imported_config:
        _write_merged_config(profile_target / "config.yaml", existing_config, imported_config)
    workspace_path = str(registry.workspace_path_for(profile_name))
    registry.ensure_workspace(profile_name, workspace_path)
    if (agent_root / "workspace").exists():
        shutil.copytree(agent_root / "workspace", Path(workspace_path), dirs_exist_ok=True)
    registry.write_team_meta(
        profile_name,
        {
            "name": meta.get("name") or profile_name,
            "role": meta.get("role") or "worker",
            "description": meta.get("description") or "",
            "is_leader": bool(meta.get("is_leader")),
            "created_at": now_iso(),
            "workspace_path": workspace_path,
        },
    )
    agent = {
        "agent_id": registry.agent_id_for(profile_name),
        "profile_name": profile_name,
        "name": meta.get("name") or profile_name,
        "role": meta.get("role") or "worker",
        "description": meta.get("description") or "",
        "is_leader": bool(meta.get("is_leader")),
        "workspace_path": workspace_path,
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
        "readiness_status": "ready" if (profile_target / "SOUL.md").exists() else "failed",
        "readiness_message": "SOUL.md 已就绪" if (profile_target / "SOUL.md").exists() else "SOUL.md 缺失或为空",
        "created_at": now_iso(),
        "last_active_at": now_iso(),
    }
    store.register_agent(agent)
    _upsert_imported_agent_record(agent)
    _restore_skills(agent["agent_id"], profile_name, agent_root)
    _restore_mcps(profile_name, agent_root)
    return {"profile_name": profile_name, "agent_id": agent["agent_id"], "success": True}


def _upsert_imported_agent_record(agent: dict) -> None:
    with SessionLocal.begin() as session:
        record = session.scalar(select(AgentRecord).where(AgentRecord.agent_id == agent["agent_id"]))
        if record is None:
            record = AgentRecord(agent_id=agent["agent_id"], profile_name=agent["profile_name"])
            session.add(record)
        record.profile_name = agent["profile_name"]
        record.name = agent.get("name") or ""
        record.role = agent.get("role") or "worker"
        record.description = agent.get("description") or ""
        record.is_leader = bool(agent.get("is_leader"))
        record.workspace_path = agent.get("workspace_path") or ""
        record.status = "idle"
        record.current_task = "空闲"
        record.runtime_status = "stopped"
        record.interaction_state = "idle"
        record.orchestration_state = "none"
        record.queue_depth = 0
        record.pending_interaction_json = "null"
        record.load = 0
        record.last_input = ""
        record.last_output = ""
        record.last_output_at = ""
        record.readiness_status = agent.get("readiness_status") or "ready"
        record.readiness_message = agent.get("readiness_message") or ""
        record.created_at = agent.get("created_at")
        record.updated_at = now_iso()
        record.deleted_at = None
        record.last_active_at = agent.get("last_active_at") or ""


def _safe_read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_merged_config(path: Path, existing: dict, imported: dict) -> None:
    merged = dict(imported)
    for key in ("model", "provider", "api_key", "providers"):
        if key in existing:
            merged[key] = existing[key]
    if isinstance(existing.get("mcp_servers"), dict) and isinstance(imported.get("mcp_servers"), dict):
        merged["mcp_servers"] = {**existing["mcp_servers"], **imported["mcp_servers"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _copy_imported_profile(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("SOUL.md", "team-meta.json"):
        if (source / filename).exists():
            shutil.copy2(source / filename, target / filename)
    for dirname in ("memories", "skills"):
        if (source / dirname).exists():
            shutil.copytree(source / dirname, target / dirname, dirs_exist_ok=True, symlinks=True)


def _restore_skills(agent_id: str, profile_name: str, agent_root: Path) -> None:
    rows = json.loads((agent_root / "db" / "skill_installs.json").read_text(encoding="utf-8"))
    for row in rows:
        slug = _validate_import_skill_slug(row.get("slug") or "", profile_name)
        inline_dir = agent_root / "profile" / "skills" / slug
        if inline_dir.exists():
            target = registry.skill_dir(profile_name, slug)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(inline_dir, target, dirs_exist_ok=True, symlinks=True)
            payload = dict(row)
            payload["installed_at"] = now_iso()
            skill_installer._upsert_install_record(profile_name, slug, payload)
            continue
        if row.get("source_url"):
            skill_installer.install_from_git(
                agent_id,
                repo_url=row.get("source_url") or "",
                ref=row.get("source_ref") or "",
                subdir=row.get("subdir") or "",
                slug=slug,
            )


def _restore_mcps(profile_name: str, agent_root: Path) -> None:
    rows = json.loads((agent_root / "db" / "mcp_servers.json").read_text(encoding="utf-8"))
    for row in rows:
        name = row.get("name") or ""
        spec = row.get("spec") or {}
        if spec:
            profiles.upsert_mcp_server(profile_name, name, spec)
        mcp_installer._upsert_record(
            profile_name,
            mcp_installer._RecordPayload(
                name=name,
                transport=row.get("transport") or "http",
                source_type=row.get("source_type") or "manual",
                description=row.get("description") or "",
                managed=bool(row.get("managed")),
            ),
        )


def _rollback_profile(profile_name: str, store: RuntimeStore) -> None:
    if not profile_name:
        return
    agent_id = registry.agent_id_for(profile_name)
    try:
        store.remove_agent(agent_id)
    except Exception:  # noqa: BLE001
        pass
    with SessionLocal.begin() as session:
        session.query(AgentSkillInstallRecord).filter_by(profile_name=profile_name).delete()
        session.query(AgentMcpServerRecord).filter_by(profile_name=profile_name).delete()
        session.query(AgentRecord).filter_by(profile_name=profile_name).delete()
    try:
        profiles.delete_hermes_profile(profile_name)
    except Exception:  # noqa: BLE001
        shutil.rmtree(HERMES_HOME / "profiles" / profile_name, ignore_errors=True)
    shutil.rmtree(AGENT_TEAM_WORKSPACE_ROOT / profile_name, ignore_errors=True)
