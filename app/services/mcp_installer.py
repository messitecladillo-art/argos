from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from ..config import now_iso
from ..db.models import AgentMcpServerRecord
from ..db.session import SessionLocal
from . import profiles


MCP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
RESERVED_NAMES = {"agent_bus"}
SECRET_KEY_RE = re.compile(r"(^authorization$|token|secret|key|password)", re.IGNORECASE)
VALID_TRANSPORTS = {"http", "stdio"}


class McpError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _RecordPayload:
    name: str
    transport: str
    source_type: str = "manual"
    description: str = ""
    managed: bool = False


def _find_agent(agent_id: str) -> dict:
    from ..models.store import store

    agent = store.find_agent(agent_id)
    if agent is None:
        raise McpError("agent not found", status_code=404)
    return agent


def _agent_profile_name(agent_id: str) -> str:
    return _find_agent(agent_id)["profile_name"]


def _validate_name(name: str, *, allow_reserved: bool = False) -> str:
    value = (name or "").strip()
    if not MCP_NAME_RE.fullmatch(value):
        raise McpError("invalid mcp name")
    if value in RESERVED_NAMES and not allow_reserved:
        raise McpError("agent_bus is platform-managed")
    return value


def _validate_transport(transport: str) -> str:
    value = (transport or "").strip().lower()
    if value not in VALID_TRANSPORTS:
        raise McpError("transport must be http or stdio")
    return value


def _validate_url(url: str) -> str:
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise McpError("invalid mcp url", status_code=422)
    return value


def _string_dict(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpError(f"{field} must be an object", status_code=422)
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        if not key_text:
            raise McpError(f"{field} contains empty key", status_code=422)
        if item is None:
            result[key_text] = ""
        elif isinstance(item, (str, int, float, bool)):
            result[key_text] = str(item)
        else:
            raise McpError(f"{field}.{key_text} must be a scalar", status_code=422)
    return result


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise McpError(f"{field} must be an array", status_code=422)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise McpError(f"{field} items must be strings", status_code=422)
        result.append(item)
    return result


def _transport_from_spec(spec: dict) -> str:
    if "command" in spec:
        return "stdio"
    return "http"


def _record_map(profile_name: str) -> dict[str, AgentMcpServerRecord]:
    with SessionLocal() as session:
        records = session.scalars(
            select(AgentMcpServerRecord).where(
                AgentMcpServerRecord.profile_name == profile_name
            )
        ).all()
    return {record.name: record for record in records}


def _load_record(profile_name: str, name: str) -> AgentMcpServerRecord | None:
    with SessionLocal() as session:
        return session.scalar(
            select(AgentMcpServerRecord).where(
                AgentMcpServerRecord.profile_name == profile_name,
                AgentMcpServerRecord.name == name,
            )
        )


def _upsert_record(profile_name: str, payload: _RecordPayload) -> None:
    now = now_iso()
    with SessionLocal.begin() as session:
        record = session.scalar(
            select(AgentMcpServerRecord).where(
                AgentMcpServerRecord.profile_name == profile_name,
                AgentMcpServerRecord.name == payload.name,
            )
        )
        if record is None:
            record = AgentMcpServerRecord(profile_name=profile_name, name=payload.name)
            record.created_at = now
            session.add(record)
        record.transport = payload.transport
        record.source_type = payload.source_type
        record.description = payload.description
        record.managed = payload.managed
        record.updated_at = now


def upsert_builtin_agent_bus(profile_name: str) -> None:
    _upsert_record(
        profile_name,
        _RecordPayload(
            name="agent_bus",
            transport="http",
            source_type="builtin",
            description="平台团队总线",
            managed=True,
        ),
    )


def delete_records_for_profile(profile_name: str) -> None:
    with SessionLocal.begin() as session:
        session.query(AgentMcpServerRecord).filter_by(profile_name=profile_name).delete()


def _delete_record(profile_name: str, name: str) -> None:
    with SessionLocal.begin() as session:
        record = session.scalar(
            select(AgentMcpServerRecord).where(
                AgentMcpServerRecord.profile_name == profile_name,
                AgentMcpServerRecord.name == name,
            )
        )
        if record is not None:
            session.delete(record)


def _update_test_record(profile_name: str, name: str, transport: str, status: str, detail: str) -> None:
    with SessionLocal.begin() as session:
        record = session.scalar(
            select(AgentMcpServerRecord).where(
                AgentMcpServerRecord.profile_name == profile_name,
                AgentMcpServerRecord.name == name,
            )
        )
        if record is None:
            record = AgentMcpServerRecord(
                profile_name=profile_name,
                name=name,
                transport=transport,
                source_type="external",
                description="",
                managed=False,
            )
            record.created_at = now_iso()
            session.add(record)
        record.last_test_status = status
        record.last_test_at = now_iso()
        record.last_error = "" if status == "ok" else detail
        record.updated_at = now_iso()


def _mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def _mask_secrets(mapping: dict[str, str], *, reveal: bool) -> dict[str, str]:
    if reveal:
        return dict(mapping)
    return {
        key: (_mask_value(value) if SECRET_KEY_RE.search(key) else value)
        for key, value in mapping.items()
    }


def _is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key))


def _mcp_entry(profile_name: str, name: str, spec: dict, record: AgentMcpServerRecord | None, *, reveal_secrets: bool = False) -> dict:
    transport = record.transport if record is not None else _transport_from_spec(spec)
    source_type = record.source_type if record is not None else "external"
    managed = bool(record.managed) if record is not None else name == "agent_bus"
    if name == "agent_bus":
        source_type = "builtin"
        managed = True
    headers = _string_dict(spec.get("headers"), "headers")
    env = _string_dict(spec.get("env"), "env")
    return {
        "name": name,
        "transport": transport,
        "source_type": source_type,
        "description": record.description if record is not None else "",
        "managed": managed,
        "has_db_record": record is not None,
        "url": spec.get("url") or "",
        "headers": _mask_secrets(headers, reveal=reveal_secrets),
        "header_secret_keys": [key for key in headers if _is_secret_key(key)],
        "command": spec.get("command") or "",
        "args": _string_list(spec.get("args"), "args"),
        "env": _mask_secrets(env, reveal=reveal_secrets),
        "env_secret_keys": [key for key in env if _is_secret_key(key)],
        "last_test_status": record.last_test_status if record is not None else "",
        "last_test_at": record.last_test_at if record is not None else "",
        "last_error": record.last_error if record is not None else "",
        "profile_name": profile_name,
    }


def _load_yaml_servers(profile_name: str) -> dict[str, dict]:
    data = profiles.read_profile_config(profile_name)
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return {}
    return {str(name): spec for name, spec in servers.items() if isinstance(spec, dict)}


def list_installed(profile_name: str, *, reveal_secrets: bool = False) -> list[dict]:
    servers = _load_yaml_servers(profile_name)
    records = _record_map(profile_name)
    names = sorted(set(servers) | set(records))
    items = []
    for name in names:
        spec = servers.get(name) or {}
        record = records.get(name)
        if not spec and record is not None:
            continue
        items.append(_mcp_entry(profile_name, name, spec, record, reveal_secrets=reveal_secrets))
    return items


def get_mcp(profile_name: str, name: str, *, reveal_secrets: bool = False) -> dict | None:
    servers = _load_yaml_servers(profile_name)
    spec = servers.get(name)
    if spec is None:
        return None
    return _mcp_entry(profile_name, name, spec, _load_record(profile_name, name), reveal_secrets=reveal_secrets)


def _build_spec(*, transport: str, payload: dict, existing: dict | None = None, partial: bool = False) -> dict:
    base = dict(existing or {}) if partial else {}
    if transport == "http":
        if "url" in payload or not partial:
            base["url"] = _validate_url(payload.get("url") or "")
        if "headers" in payload:
            headers = _merge_secret_mapping(
                _string_dict(existing.get("headers"), "headers") if existing else {},
                payload.get("headers"),
            )
            if headers:
                base["headers"] = headers
            else:
                base.pop("headers", None)
        base.pop("command", None)
        base.pop("args", None)
        base.pop("env", None)
    else:
        if "command" in payload or not partial:
            command = (payload.get("command") or "").strip()
            if not command:
                raise McpError("command is required", status_code=422)
            base["command"] = command
        if "args" in payload or not partial:
            base["args"] = _string_list(payload.get("args"), "args")
        if "env" in payload:
            env = _merge_secret_mapping(
                _string_dict(existing.get("env"), "env") if existing else {},
                payload.get("env"),
            )
            if env:
                base["env"] = env
            else:
                base.pop("env", None)
        base.pop("url", None)
        base.pop("headers", None)
    base["enabled"] = True
    return base


def _merge_secret_mapping(existing: dict[str, str], incoming: Any) -> dict[str, str]:
    patch = _string_dict(incoming, "secret mapping")
    result = dict(existing)
    for key, value in patch.items():
        if value == "":
            result.pop(key, None)
        elif key in result and value in {"****", _mask_value(result[key])}:
            continue
        else:
            result[key] = value
    return result


def add_mcp(agent_id: str, *, name: str, transport: str, url: str | None = None, headers: dict | None = None, command: str | None = None, args: list[str] | None = None, env: dict | None = None, description: str = "", takeover: bool = False) -> dict:
    profile_name = _agent_profile_name(agent_id)
    mcp_name = _validate_name(name)
    mcp_transport = _validate_transport(transport)
    servers = _load_yaml_servers(profile_name)
    records = _record_map(profile_name)
    if mcp_name in records and mcp_name in servers:
        raise McpError("mcp already exists", status_code=409)
    if mcp_name in servers and not takeover:
        raise McpError("external mcp exists; confirm takeover", status_code=409)
    payload = {"url": url, "headers": headers, "command": command, "args": args, "env": env}
    spec = _build_spec(transport=mcp_transport, payload=payload)
    profiles.upsert_mcp_server(profile_name, mcp_name, spec)
    _upsert_record(
        profile_name,
        _RecordPayload(
            name=mcp_name,
            transport=mcp_transport,
            source_type="manual",
            description=(description or "").strip(),
            managed=False,
        ),
    )
    result = get_mcp(profile_name, mcp_name) or {}
    result["requires_restart"] = True
    return result


def update_mcp(agent_id: str, name: str, *, patch: dict) -> dict:
    profile_name = _agent_profile_name(agent_id)
    mcp_name = _validate_name(name, allow_reserved=True)
    current = get_mcp(profile_name, mcp_name, reveal_secrets=True)
    if current is None:
        raise McpError("mcp not found", status_code=404)
    if current.get("managed"):
        raise McpError("agent_bus is platform-managed")
    transport = _validate_transport(patch.get("transport") or current["transport"])
    existing_spec = _load_yaml_servers(profile_name).get(mcp_name) or {}
    spec = _build_spec(transport=transport, payload=patch, existing=existing_spec, partial=True)
    profiles.upsert_mcp_server(profile_name, mcp_name, spec)
    _upsert_record(
        profile_name,
        _RecordPayload(
            name=mcp_name,
            transport=transport,
            source_type="manual",
            description=(patch.get("description") if "description" in patch else current.get("description")) or "",
            managed=False,
        ),
    )
    result = get_mcp(profile_name, mcp_name) or {}
    result["requires_restart"] = True
    return result


def remove_mcp(agent_id: str, name: str) -> None:
    profile_name = _agent_profile_name(agent_id)
    mcp_name = _validate_name(name, allow_reserved=True)
    current = get_mcp(profile_name, mcp_name)
    if current is None:
        raise McpError("mcp not found", status_code=404)
    if current.get("managed"):
        raise McpError("agent_bus is platform-managed")
    profiles.remove_mcp_server(profile_name, mcp_name)
    _delete_record(profile_name, mcp_name)


def test_mcp(agent_id: str, name: str, *, timeout: int = 15) -> dict:
    profile_name = _agent_profile_name(agent_id)
    mcp_name = _validate_name(name, allow_reserved=True)
    current = get_mcp(profile_name, mcp_name, reveal_secrets=True)
    if current is None:
        raise McpError("mcp not found", status_code=404)
    if current["transport"] == "http":
        result = _test_http(current, timeout=timeout)
    else:
        result = _test_stdio(current, timeout=timeout)
    _update_test_record(profile_name, mcp_name, current["transport"], result["status"], result["detail"])
    return result


def _test_http(mcp: dict, *, timeout: int) -> dict:
    url = mcp.get("url") or ""
    headers = _string_dict(mcp.get("headers"), "headers")
    headers.setdefault("Accept", "application/json, text/event-stream")
    try:
        response = httpx.head(url, headers=headers, timeout=min(timeout, 10), follow_redirects=False)
    except httpx.HTTPError:
        response = None
    if response is not None and response.status_code not in {403, 405}:
        return _http_result(url, response.status_code)
    try:
        with httpx.stream("GET", url, headers=headers, timeout=min(timeout, 10), follow_redirects=False) as response:
            return _http_result(url, response.status_code)
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "fail", "detail": f"HTTP request failed: {exc.__class__.__name__}"}


def _http_result(url: str, status_code: int) -> dict:
    if 200 <= status_code < 400:
        return {"ok": True, "status": "ok", "detail": f"{status_code} from {url}"}
    if status_code in {401, 404, 406}:
        return {"ok": False, "status": "fail", "detail": f"网络可达但协议/权限未通过，HTTP {status_code}"}
    return {"ok": False, "status": "fail", "detail": f"HTTP {status_code}"}


def _test_stdio(mcp: dict, *, timeout: int) -> dict:
    command = mcp.get("command") or ""
    args = _string_list(mcp.get("args"), "args")
    extra_env = _string_dict(mcp.get("env"), "env")
    env = {**os.environ, **extra_env} if extra_env else None
    init_message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hermes-agents-team", "version": "1.0"},
        },
    }
    proc = None
    try:
        proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        lines: queue.Queue[str] = queue.Queue()

        def read_stdout() -> None:
            if proc is None or proc.stdout is None:
                return
            line = proc.stdout.readline()
            if line:
                lines.put(line)

        thread = threading.Thread(target=read_stdout, daemon=True)
        thread.start()
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(init_message) + "\n")
        proc.stdin.flush()
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            return {"ok": False, "status": "fail", "detail": "stdio initialize timed out"}
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "status": "fail", "detail": "stdio returned invalid JSON"}
        if payload.get("id") == 1 and ("result" in payload or payload.get("method") == "initialize"):
            return {"ok": True, "status": "ok", "detail": "stdio initialize ok"}
        return {"ok": False, "status": "fail", "detail": "stdio initialize failed"}
    except FileNotFoundError:
        return {"ok": False, "status": "fail", "detail": "command not found"}
    except OSError as exc:
        return {"ok": False, "status": "fail", "detail": f"stdio failed: {exc}"}
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()


def mcp_summary(profile_name: str) -> list[dict]:
    return [
        {
            "name": item["name"],
            "transport": item["transport"],
            "description": item.get("description") or "",
            "source_type": item.get("source_type") or "manual",
        }
        for item in list_installed(profile_name)
        if item["name"] != "agent_bus"
    ]
