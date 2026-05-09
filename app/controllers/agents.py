from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..models.store import store
from ..services import registry
from ..services import agents as agents_service
from ..services import soul as soul_service
from ..services import skill_installer
from ..services.acp import pool as session_pool
from ..services.profiles import ProfileError, check_hermes_ready, list_hermes_profiles


bp = Blueprint("agents", __name__, url_prefix="/api")
MAX_SOUL_BYTES = 200_000


@bp.get("/dashboard")
def dashboard():
    return jsonify(store.snapshot())


@bp.get("/profiles")
def list_profiles():
    return jsonify({"profiles": list_hermes_profiles()})


@bp.get("/hermes/status")
def hermes_status():
    return jsonify(check_hermes_ready())


@bp.post("/agents")
def create_agent():
    payload = request.get_json(silent=True) or {}
    try:
        agent = agents_service.create_agent(
            store,
            name=payload.get("name") or "",
            profile_name=payload.get("profile_name") or "",
            role=payload.get("role") or "worker",
            description=payload.get("description") or "",
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent}), 201


@bp.delete("/agents/<agent_id>")
def delete_agent(agent_id: str):
    try:
        agent = agents_service.delete_agent(store, agent_id)
    except ValueError as exc:
        status_code = 404 if str(exc) == "agent not found" else 400
        return jsonify({"ok": False, "error": str(exc)}), status_code
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent})


@bp.post("/agents/<agent_id>/open-workspace")
def open_agent_workspace(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        path = _ensure_agent_workspace(agent)
        _open_directory(path)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": str(path)})


@bp.post("/agents/<agent_id>/start")
def start_agent(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    if (agent.get("readiness_status") or "ready") != "ready":
        return jsonify({"ok": False, "error": "agent is not ready"}), 400
    ok = session_pool.start(agent)
    return jsonify({"ok": ok, "agent": store.find_agent(agent_id)})


@bp.post("/agents/runtime")
def bulk_agent_runtime():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"start", "stop", "restart"}:
        return jsonify({"ok": False, "error": "action must be start, stop, or restart"}), 400

    agents = store.snapshot().get("agents", [])
    results = []
    for agent in agents:
        agent_id = agent.get("agent_id") or ""
        name = agent.get("name") or agent_id
        if action in {"start", "restart"} and (agent.get("readiness_status") or "ready") != "ready":
            results.append(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "ok": False,
                    "skipped": True,
                    "error": "agent is not ready",
                }
            )
            continue
        if action == "stop":
            session_pool.stop(agent_id)
            results.append({"agent_id": agent_id, "name": name, "ok": True})
            continue
        ok = session_pool.restart(agent) if action == "restart" else session_pool.start(agent)
        results.append(
            {
                "agent_id": agent_id,
                "name": name,
                "ok": bool(ok),
                "error": "agent runtime action failed" if not ok else "",
            }
        )

    failed = [item for item in results if not item.get("ok") and not item.get("skipped")]
    skipped = [item for item in results if item.get("skipped")]
    return jsonify(
        {
            "ok": not failed,
            "action": action,
            "results": results,
            "failed": len(failed),
            "skipped": len(skipped),
            "agents": store.snapshot().get("agents", []),
        }
    )


def _ensure_agent_workspace(agent: dict) -> Path:
    raw_path = agent.get("workspace_path") or registry.workspace_path_for(agent["profile_name"])
    path = Path(raw_path).expanduser().resolve(strict=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open_directory(path: Path) -> None:
    platform = sys.platform
    try:
        if platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        if platform.startswith("linux"):
            opener = shutil.which("xdg-open")
            if not opener:
                raise RuntimeError("xdg-open not found; cannot open workspace on Linux")
            subprocess.Popen([opener, str(path)])
            return
        if platform.startswith("win"):
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise RuntimeError("os.startfile is not available on this Windows runtime")
            startfile(str(path))
            return
    except OSError as exc:
        raise RuntimeError(f"open workspace failed: {exc}") from exc
    raise RuntimeError(f"unsupported platform: {platform}")


@bp.post("/agents/<agent_id>/stop")
def stop_agent(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    session_pool.stop(agent_id)
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.get("/agents/<agent_id>/soul")
def get_agent_soul(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404

    soul_path = registry.soul_path_for(agent["profile_name"])
    try:
        if soul_path.exists():
            content = soul_path.read_text(encoding="utf-8")
            updated_at = datetime.fromtimestamp(
                soul_path.stat().st_mtime,
                timezone.utc,
            ).isoformat().replace("+00:00", "Z")
        else:
            content = ""
            updated_at = None
    except OSError as exc:
        return jsonify({"ok": False, "error": f"SOUL.md read failed: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "content": content,
            "path": str(soul_path),
            "updated_at": updated_at,
            "agent": {
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "profile_name": agent["profile_name"],
                "role": agent["role"],
                "runtime_status": agent.get("runtime_status") or "stopped",
                "readiness_status": agent.get("readiness_status") or "ready",
            },
        }
    )


@bp.put("/agents/<agent_id>/soul")
def update_agent_soul(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    if (agent.get("readiness_status") or "ready") == "preparing":
        return jsonify({"ok": False, "error": "SOUL.md is still being generated"}), 409

    payload = request.get_json(silent=True) or {}
    content = payload.get("content")
    if not isinstance(content, str):
        return jsonify({"ok": False, "error": "content is required"}), 400
    if not content.strip():
        return jsonify({"ok": False, "error": "SOUL.md content cannot be empty"}), 400
    if len(content.encode("utf-8")) > MAX_SOUL_BYTES:
        return jsonify({"ok": False, "error": "SOUL.md content is too large"}), 400
    if not content.endswith("\n"):
        content += "\n"

    soul_path = registry.soul_path_for(agent["profile_name"])
    try:
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(content, encoding="utf-8")
        updated_at = datetime.fromtimestamp(
            soul_path.stat().st_mtime,
            timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    except OSError as exc:
        return jsonify({"ok": False, "error": f"SOUL.md write failed: {exc}"}), 500

    store.update_agent(
        agent_id,
        readiness_status="ready",
        readiness_message="SOUL.md 已保存",
        current_task="空闲" if agent.get("current_task") in {"SOUL.md 缺失或为空", "SOUL.md 写入失败"} else agent.get("current_task", "空闲"),
    )
    store.push_event(
        "agent.soul.updated",
        agent_id,
        None,
        {"text": f"SOUL.md 已保存 → {soul_path}"},
    )
    return jsonify(
        {
            "ok": True,
            "content": content,
            "path": str(soul_path),
            "updated_at": updated_at,
            "agent": store.find_agent(agent_id),
        }
    )


@bp.post("/agents/<agent_id>/soul/regenerate")
def regenerate_agent_soul(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    if (agent.get("readiness_status") or "ready") == "preparing":
        return jsonify({"ok": False, "error": "SOUL.md is still being generated"}), 409

    store.update_agent(
        agent_id,
        readiness_status="preparing",
        readiness_message="正在重新生成 SOUL.md",
        current_task="正在重新生成 SOUL.md",
    )
    store.push_event(
        "agent.soul.regenerate.started",
        agent_id,
        None,
        {"text": "SOUL.md 重新生成已开始"},
    )
    soul_service.spawn_generate(
        store,
        agent_id=agent["agent_id"],
        name=agent["name"],
        role=agent["role"],
        description=agent.get("description") or "",
        profile_name=agent["profile_name"],
    )
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)}), 202


@bp.post("/agents/<agent_id>/interactions/<request_id>/respond")
def respond_interaction(agent_id: str, request_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.respond_interaction(
            agent_id,
            request_id,
            payload.get("response") or "",
        )
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/terminal-input")
def send_terminal_input(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.send_terminal_input(agent_id, payload.get("text") or "")
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


@bp.post("/agents/<agent_id>/terminal-data")
def send_terminal_data(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        session_pool.send_terminal_data(agent_id, payload.get("data") or "")
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})


def _get_agent_or_404(agent_id: str) -> dict | None:
    agent = store.find_agent(agent_id)
    if agent is None:
        return None
    return agent


@bp.get("/agents/<agent_id>/skills")
def list_agent_skills(agent_id: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    return jsonify(
        {
            "ok": True,
            "skills": skill_installer.list_installed(agent["profile_name"]),
            "agent": {
                "agent_id": agent["agent_id"],
                "profile_name": agent["profile_name"],
                "name": agent["name"],
            },
        }
    )


@bp.post("/agents/<agent_id>/skills/install")
def install_agent_skill(agent_id: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    repo_url = payload.get("repo_url") or payload.get("source_url") or ""
    try:
        skill = skill_installer.install_from_git(
            agent_id,
            repo_url=repo_url,
            ref=payload.get("ref") or "",
            subdir=payload.get("subdir") or "",
            slug=payload.get("slug"),
        )
    except skill_installer.SkillError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True, "skill": skill}), 201


@bp.get("/agents/<agent_id>/skills/<path:slug>")
def get_agent_skill(agent_id: str, slug: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        skill = skill_installer.get_skill(agent["profile_name"], slug)
    except skill_installer.SkillError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    if skill is None:
        return jsonify({"ok": False, "error": "skill not found"}), 404
    return jsonify({"ok": True, "skill": skill})


@bp.delete("/agents/<agent_id>/skills/<path:slug>")
def uninstall_agent_skill(agent_id: str, slug: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        skill_installer.uninstall(agent_id, slug)
    except skill_installer.SkillError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True})


@bp.post("/agents/<agent_id>/skills/<path:slug>/reinstall")
def reinstall_agent_skill(agent_id: str, slug: str):
    agent = _get_agent_or_404(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    try:
        skill = skill_installer.reinstall(agent_id, slug)
    except skill_installer.SkillError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True, "skill": skill})


@bp.post("/agents/<agent_id>/terminal-resize")
def resize_terminal(agent_id: str):
    agent = store.find_agent(agent_id)
    if agent is None:
        return jsonify({"ok": False, "error": "agent not found"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        rows = int(payload.get("rows") or 0)
        cols = int(payload.get("cols") or 0)
        if rows <= 0 or cols <= 0:
            raise ValueError("rows and cols are required")
        session_pool.resize_terminal(agent_id, rows, cols)
    except (RuntimeError, ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "agent": store.find_agent(agent_id)})
