from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

from ..config import HERMES_HOME, PROFILE_NAME_RE


class ProfileError(RuntimeError):
    """Raised when the hermes CLI fails for a non-business reason."""


def check_hermes_ready() -> dict:
    """Return whether the local Hermes CLI is usable for profile cloning."""
    try:
        result = subprocess.run(
            ["hermes", "profile", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "reason": "not_found",
            "message": "未检测到 hermes CLI，请先安装并配置 Hermes Agent。",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": "timeout",
            "message": "Hermes 响应超时，请确认 Hermes Agent 已正确配置。",
        }

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return {
            "ok": False,
            "reason": "command_failed",
            "message": "Hermes 当前不可用，请先完成 Hermes Agent 配置。",
            "detail": output,
        }

    profiles = _parse_profile_list(result.stdout or "")
    if not profiles:
        return {
            "ok": False,
            "reason": "no_profiles",
            "message": "未检测到可用 Hermes profile，请先配置 Hermes Agent。",
        }

    return {"ok": True, "profiles": profiles, "message": "Hermes 已就绪"}


def _profile_config_path(profile_name: str) -> Path:
    return HERMES_HOME / "profiles" / profile_name / "config.yaml"


def create_hermes_profile(profile_name: str) -> None:
    """Invoke `hermes profile create <name> --clone --no-alias`.

    `--clone` inherits the active profile's model/config so the new profile
    is immediately usable (otherwise Model is empty and chat won't run).
    Treats "already exists" as idempotent success.
    """
    cmd = ["hermes", "profile", "create", profile_name, "--clone", "--no-alias"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise ProfileError("hermes CLI not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProfileError("hermes profile create timed out") from exc
    if result.returncode == 0:
        return
    stderr = (result.stderr or result.stdout or "").strip()
    if "already exists" in stderr.lower():
        return
    raise ProfileError(stderr or "hermes profile create failed")


def list_hermes_profiles() -> list[str]:
    """Parse `hermes profile list` into a list of profile names."""
    try:
        result = subprocess.run(
            ["hermes", "profile", "list"], capture_output=True, text=True, timeout=15
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return _parse_profile_list(result.stdout or "")


def _parse_profile_list(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        stripped = line.strip().lstrip("◆").strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first.lower() == "profile" or set(first) <= {"─", "-"}:
            continue
        if PROFILE_NAME_RE.match(first):
            names.append(first)
    return names


def delete_hermes_profile(profile_name: str) -> None:
    """Invoke `hermes profile delete <name> -y`. No-op if profile does not exist."""
    try:
        result = subprocess.run(
            ["hermes", "profile", "delete", profile_name, "-y"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise ProfileError("hermes CLI not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProfileError("hermes profile delete timed out") from exc
    if result.returncode == 0:
        return
    stderr = (result.stderr or result.stdout or "").strip()
    if "not found" in stderr.lower() or "does not exist" in stderr.lower():
        return
    raise ProfileError(stderr or "hermes profile delete failed")


def attach_mcp_server(profile_name: str, *, name: str, url: str) -> None:
    """Inject an HTTP MCP server entry into a profile's config.yaml.

    Hermes reads `mcp_servers.<name> = {url, enabled}` from the profile config
    (see hermes_cli/mcp_config.py). We merge in place so the rest of the file
    (model, providers, …) is preserved.
    """
    upsert_mcp_server(profile_name, name, {"url": url, "enabled": True})


def read_profile_config(profile_name: str) -> dict:
    cfg_path = _profile_config_path(profile_name)
    if not cfg_path.exists():
        raise ProfileError(f"profile config not found: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def write_profile_config(profile_name: str, data: dict) -> None:
    cfg_path = _profile_config_path(profile_name)
    if not cfg_path.exists():
        raise ProfileError(f"profile config not found: {cfg_path}")
    tmp_path = cfg_path.with_name(f"{cfg_path.name}.tmp")
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, cfg_path)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProfileError(f"profile config write failed: {exc}") from exc


def upsert_mcp_server(profile_name: str, name: str, spec: dict) -> None:
    data = read_profile_config(profile_name)
    servers = data.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcp_servers"] = servers
    next_spec = dict(spec)
    next_spec["enabled"] = True
    servers[name] = next_spec
    write_profile_config(profile_name, data)


def remove_mcp_server(profile_name: str, name: str) -> None:
    data = read_profile_config(profile_name)
    servers = data.get("mcp_servers")
    if isinstance(servers, dict):
        servers.pop(name, None)
    write_profile_config(profile_name, data)


# Hermes built-in toolsets that conflict with our agent_bus-based team
# delegation. When enabled on a leader profile they cause the LLM to route
# "让 X 做 Y" 类指令到内部的子 agent（delegation）或者 iMessage/SMS 工具
# （messaging），从而绕过 agent_bus.delegate_task，使 worker 不会真正收到消息。
LEADER_CONFLICTING_TOOLSETS = ("delegation", "messaging")


def disable_conflicting_toolsets(profile_name: str) -> None:
    """Disable built-in toolsets on a profile that conflict with agent_bus."""
    for toolset in LEADER_CONFLICTING_TOOLSETS:
        try:
            subprocess.run(
                ["hermes", "-p", profile_name, "tools", "disable", toolset],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Best-effort: SOUL.md guidance still steers the LLM.
            pass
