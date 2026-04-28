from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import ipaddress

from sqlalchemy import select
import yaml

from ..config import HERMES_HOME, now_iso
from ..db.models import AgentSkillInstallRecord
from ..db.session import SessionLocal
from . import registry, skill_frontmatter


SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
SKILL_PATH_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
MAX_SKILL_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILE_BYTES = 5 * 1024 * 1024
MAX_SKILL_FILE_COUNT = 500
GIT_CLONE_TIMEOUT_SECONDS = 120


class SkillError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SkillSourceInfo:
    slug: str
    name: str
    description: str
    body: str
    path: Path


@dataclass
class ResolvedSourceDir:
    path: Path
    subdir: str


def _agent_profile_name(agent_id: str) -> str:
    agent = _find_agent(agent_id)
    return agent["profile_name"]


def _find_agent(agent_id: str) -> dict:
    from ..models.store import store

    agent = store.find_agent(agent_id)
    if agent is None:
        raise SkillError("agent not found", status_code=404)
    return agent


def _validate_skill_locator(slug: str) -> str:
    value = (slug or "").strip().strip("/")
    if not value:
        raise SkillError("invalid skill slug")
    parts = value.split("/")
    if any(part in {".", ".."} or not SKILL_PATH_SEGMENT_RE.fullmatch(part) for part in parts):
        raise SkillError("invalid skill slug")
    return "/".join(parts)


def _skill_md_file(skill_path: Path) -> Path:
    return skill_path / "SKILL.md"


def _skill_entry_from_path(skill_path: Path, *, skills_root: Path | None = None) -> dict | None:
    skill_md = _skill_md_file(skill_path)
    if not skill_path.is_dir() or not skill_md.exists():
        return None
    slug = (
        skill_path.relative_to(skills_root).as_posix()
        if skills_root is not None
        else skill_path.name
    )
    content = skill_md.read_text(encoding="utf-8")
    try:
        frontmatter, body = skill_frontmatter.parse(content)
        error = ""
    except yaml.YAMLError as exc:
        frontmatter = {}
        body = content
        error = f"invalid frontmatter: {exc.__class__.__name__}"
    return {
        "slug": slug,
        "name": str(frontmatter.get("name") or slug),
        "description": str(frontmatter.get("description") or frontmatter.get("name") or slug),
        "path": str(skill_path.resolve(strict=False)),
        "body": body,
        "error": error,
    }


def _iter_skill_dirs(skills_dir: Path) -> list[Path]:
    if not skills_dir.exists():
        return []
    items: list[Path] = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        try:
            relative = skill_md.relative_to(skills_dir)
        except ValueError:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        items.append(skill_md.parent)
    return items


def _load_install_records(profile_name: str) -> dict[str, AgentSkillInstallRecord]:
    with SessionLocal() as session:
        records = session.scalars(
            select(AgentSkillInstallRecord).where(
                AgentSkillInstallRecord.profile_name == profile_name
            )
        ).all()
    return {record.slug: record for record in records}


def _load_install_record(profile_name: str, slug: str) -> AgentSkillInstallRecord | None:
    with SessionLocal() as session:
        return session.scalar(
            select(AgentSkillInstallRecord).where(
                AgentSkillInstallRecord.profile_name == profile_name,
                AgentSkillInstallRecord.slug == slug,
            )
        )


def _upsert_install_record(profile_name: str, slug: str, payload: dict) -> None:
    with SessionLocal.begin() as session:
        record = session.scalar(
            select(AgentSkillInstallRecord).where(
                AgentSkillInstallRecord.profile_name == profile_name,
                AgentSkillInstallRecord.slug == slug,
            )
        )
        if record is None:
            record = AgentSkillInstallRecord(profile_name=profile_name, slug=slug)
            session.add(record)
        record.source_type = payload.get("source_type") or "git"
        record.source_url = payload.get("source_url") or ""
        record.source_ref = payload.get("source_ref") or ""
        record.resolved_commit_sha = payload.get("resolved_commit_sha") or ""
        record.subdir = payload.get("subdir") or ""
        record.installed_at = payload.get("installed_at") or now_iso()
        record.last_error = payload.get("last_error") or ""
        record.created_at = record.created_at or now_iso()
        record.updated_at = now_iso()


def _delete_install_record(profile_name: str, slug: str) -> None:
    with SessionLocal.begin() as session:
        record = session.scalar(
            select(AgentSkillInstallRecord).where(
                AgentSkillInstallRecord.profile_name == profile_name,
                AgentSkillInstallRecord.slug == slug,
            )
        )
        if record is not None:
            session.delete(record)


def validate_source_url(url: str) -> None:
    parsed = urlparse((url or "").strip())
    if not parsed.geturl():
        raise SkillError("repo_url is required")
    if parsed.scheme != "https":
        raise SkillError("only https:// is supported")
    host = parsed.hostname or ""
    if not host:
        raise SkillError("invalid repo_url")
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise SkillError(
                    f"host resolves to private/reserved address: {ip}"
                )
    except socket.gaierror as exc:
        raise SkillError(f"cannot resolve host: {host}") from exc


def _validate_slug(slug: str) -> str:
    value = (slug or "").strip().lower()
    if not SKILL_SLUG_RE.fullmatch(value):
        raise SkillError("invalid slug")
    return value


def _infer_repo_name(repo_url: str) -> str:
    last = (repo_url.rstrip("/").split("/")[-1] or "skill").removesuffix(".git")
    return re.sub(r"[^a-z0-9_-]+", "-", last.lower()).strip("-") or "skill"


def _repo_subdir_path(repo_dir: Path, subdir: str) -> Path:
    if not subdir:
        return repo_dir
    candidate = (repo_dir / subdir).resolve(strict=False)
    repo_root = repo_dir.resolve(strict=False)
    if candidate != repo_root and repo_root not in candidate.parents:
        raise SkillError("subdir escapes repository root")
    if not candidate.exists() or not candidate.is_dir():
        raise SkillError("subdir not found")
    return candidate


def _resolve_source_dir(repo_dir: Path, subdir: str) -> ResolvedSourceDir:
    source_dir = _repo_subdir_path(repo_dir, subdir)
    if subdir or (source_dir / "SKILL.md").exists():
        return ResolvedSourceDir(path=source_dir, subdir=subdir)
    skill_dirs = [path.parent for path in source_dir.rglob("SKILL.md") if ".git" not in path.parts]
    if len(skill_dirs) == 1:
        discovered_subdir = skill_dirs[0].relative_to(repo_dir).as_posix()
        return ResolvedSourceDir(path=skill_dirs[0], subdir=discovered_subdir)
    if not skill_dirs:
        raise SkillError("SKILL.md not found")
    raise SkillError("multiple skills found, please specify subdir")


def _normalize_skill_dir(source_dir: Path, target_slug: str) -> SkillSourceInfo:
    skill_md = source_dir / "SKILL.md"
    if not skill_md.exists():
        raise SkillError("SKILL.md not found")
    content = skill_md.read_text(encoding="utf-8")
    try:
        frontmatter, body = skill_frontmatter.parse(content)
    except yaml.YAMLError as exc:
        raise SkillError(f"invalid frontmatter: {exc.__class__.__name__}") from exc
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    source_name = str(frontmatter.get("name") or "").strip()
    if not source_name:
        raise SkillError("SKILL.md frontmatter missing required field: name")
    frontmatter["name"] = target_slug
    frontmatter["description"] = str(frontmatter.get("description") or source_name or target_slug)
    skill_md.write_text(skill_frontmatter.dump(frontmatter, body), encoding="utf-8")
    return SkillSourceInfo(
        slug=target_slug,
        name=target_slug,
        description=str(frontmatter["description"]),
        body=body,
        path=source_dir,
    )


def _validate_symlink(path: Path, root: Path) -> None:
    target = os.readlink(path)
    if os.path.isabs(target):
        raise SkillError(f"absolute symlink is not allowed: {path.name}")
    resolved = (path.parent / target).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise SkillError(f"symlink escapes skill directory: {path.name}")


def _validate_skill_tree(root: Path) -> None:
    total_bytes = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current_dir = Path(dirpath)
        for dirname in list(dirnames):
            child = current_dir / dirname
            if child.is_symlink():
                _validate_symlink(child, root)
        for filename in filenames:
            path = current_dir / filename
            if path.is_symlink():
                _validate_symlink(path, root)
                continue
            stat = path.stat()
            file_count += 1
            total_bytes += stat.st_size
            if file_count > MAX_SKILL_FILE_COUNT:
                raise SkillError("skill file count exceeds limit")
            if stat.st_size > MAX_SKILL_FILE_BYTES:
                raise SkillError(f"file too large: {filename}")
            if total_bytes > MAX_SKILL_TOTAL_BYTES:
                raise SkillError("skill total size exceeds limit")


def _replace_skill_dir(target_dir: Path, prepared_dir: Path) -> None:
    parent = target_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    trash_dir = parent / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = None
    try:
        if target_dir.exists():
            backup_dir = trash_dir / f"{target_dir.name}.{now_iso().replace(':', '-')}"
            target_dir.rename(backup_dir)
        prepared_dir.rename(target_dir)
        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if target_dir.exists() and not prepared_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        if backup_dir and backup_dir.exists() and not target_dir.exists():
            backup_dir.rename(target_dir)
        raise


def list_installed(profile_name: str) -> list[dict]:
    skills_dir = registry.skills_dir_for(profile_name)
    records = _load_install_records(profile_name)
    items: list[dict] = []
    for child in _iter_skill_dirs(skills_dir):
        entry = _skill_entry_from_path(child, skills_root=skills_dir)
        if entry is None:
            continue
        record = records.get(entry["slug"])
        items.append(
            {
                "slug": entry["slug"],
                "name": entry["name"],
                "description": entry["description"],
                "path": entry["path"],
                "source_type": record.source_type if record else "local",
                "source_url": record.source_url if record else "",
                "source_ref": record.source_ref if record else "",
                "resolved_commit_sha": record.resolved_commit_sha if record else "",
                "subdir": record.subdir if record else "",
                "installed_at": record.installed_at if record else "",
                "has_db_record": bool(record),
                "error": entry["error"] or (record.last_error if record else ""),
            }
        )
    return items


def get_skill(profile_name: str, slug: str) -> dict | None:
    slug = _validate_skill_locator(slug)
    path = registry.skill_md_path(profile_name, slug)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    try:
        frontmatter, body = skill_frontmatter.parse(content)
        error = ""
    except yaml.YAMLError as exc:
        frontmatter = {}
        body = content
        error = f"invalid frontmatter: {exc.__class__.__name__}"
    record = _load_install_record(profile_name, slug)
    return {
        "slug": slug,
        "frontmatter": frontmatter,
        "body": body,
        "content": content,
        "path": str(path.resolve(strict=False)),
        "source_type": record.source_type if record else "local",
        "source_url": record.source_url if record else "",
        "source_ref": record.source_ref if record else "",
        "resolved_commit_sha": record.resolved_commit_sha if record else "",
        "subdir": record.subdir if record else "",
        "installed_at": record.installed_at if record else "",
        "has_db_record": bool(record),
        "error": error or (record.last_error if record else ""),
    }


def install_from_git(
    agent_id: str,
    *,
    repo_url: str,
    ref: str = "",
    subdir: str = "",
    slug: str | None = None,
) -> dict:
    profile_name = _agent_profile_name(agent_id)
    validate_source_url(repo_url)
    repo_url = repo_url.strip()
    ref = (ref or "").strip()
    subdir = (subdir or "").strip().strip("/")

    skills_dir = registry.skills_dir_for(profile_name)
    skills_dir.mkdir(parents=True, exist_ok=True)

    tmp_root = HERMES_HOME / "tmp" / f"skill_install_{uuid.uuid4().hex}"
    repo_dir = tmp_root / "repo"
    prepared_parent = skills_dir / f".tmp_{uuid.uuid4().hex}"
    prepared_dir = prepared_parent / "content"
    try:
        tmp_root.mkdir(parents=True, exist_ok=True)
        clone_args = ["git", "clone", "--depth=1"]
        if ref:
            clone_args.extend(["--branch", ref])
        clone_args.extend([repo_url, str(repo_dir)])
        subprocess.run(
            clone_args,
            check=True,
            timeout=GIT_CLONE_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        resolved_commit_sha = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        ).stdout.strip()
        source_ref = ref
        if not source_ref:
            source_ref = subprocess.run(
                ["git", "-C", str(repo_dir), "symbolic-ref", "--short", "HEAD"],
                check=False,
                timeout=30,
                capture_output=True,
                text=True,
            ).stdout.strip()
        resolved_source = _resolve_source_dir(repo_dir, subdir)
        source_dir = resolved_source.path
        effective_subdir = resolved_source.subdir
        inferred_slug = slug or _skill_entry_from_path(source_dir)
        if isinstance(inferred_slug, dict):
            inferred_slug = inferred_slug["name"]
        target_slug = _validate_slug(slug or inferred_slug or _infer_repo_name(repo_url))

        shutil.copytree(source_dir, prepared_dir, symlinks=True)
        git_dir = prepared_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        info = _normalize_skill_dir(prepared_dir, target_slug)
        _validate_skill_tree(prepared_dir)

        existing_record = _load_install_record(profile_name, target_slug)
        target_dir = registry.skill_dir(profile_name, target_slug)
        if target_dir.exists():
            if existing_record is None:
                raise SkillError(
                    "skill slug already exists with different source, uninstall it first",
                    status_code=409,
                )
            same_source = (
                existing_record.source_type == "git"
                and existing_record.source_url == repo_url
                and (existing_record.subdir or "") == effective_subdir
            )
            if not same_source:
                raise SkillError(
                    "skill slug already exists with different source, uninstall it first",
                    status_code=409,
                )

        prepared_parent.mkdir(parents=True, exist_ok=True)
        _replace_skill_dir(target_dir, prepared_dir)
        _upsert_install_record(
            profile_name,
            target_slug,
            {
                "source_type": "git",
                "source_url": repo_url,
                "source_ref": source_ref,
                "resolved_commit_sha": resolved_commit_sha,
                "subdir": effective_subdir,
                "installed_at": now_iso(),
                "last_error": "",
            },
        )
        return {
            "slug": target_slug,
            "name": info.name,
            "description": info.description,
            "path": str(target_dir.resolve(strict=False)),
            "source_type": "git",
            "source_url": repo_url,
            "source_ref": source_ref,
            "resolved_commit_sha": resolved_commit_sha,
            "subdir": effective_subdir,
            "installed_at": now_iso(),
            "has_db_record": True,
        }
    except subprocess.TimeoutExpired as exc:
        raise SkillError("git clone timed out") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise SkillError(stderr or "git clone failed") from exc
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        shutil.rmtree(prepared_parent, ignore_errors=True)


def uninstall(agent_id: str, slug: str) -> None:
    profile_name = _agent_profile_name(agent_id)
    slug = _validate_skill_locator(slug)
    target_dir = registry.skill_dir(profile_name, slug)
    if not target_dir.exists():
        _delete_install_record(profile_name, slug)
        return
    if not _skill_md_file(target_dir).exists():
        return
    shutil.rmtree(target_dir, ignore_errors=True)
    _delete_install_record(profile_name, slug)


def reinstall(agent_id: str, slug: str) -> dict:
    profile_name = _agent_profile_name(agent_id)
    slug = _validate_skill_locator(slug)
    record = _load_install_record(profile_name, slug)
    if record is None:
        raise SkillError("手动安装的 skill 无法自动升级")
    if record.source_type != "git":
        raise SkillError(f"unsupported source_type: {record.source_type}")
    return install_from_git(
        agent_id,
        repo_url=record.source_url,
        ref=record.source_ref or "",
        subdir=record.subdir or "",
        slug=record.slug,
    )


def skill_summary(profile_name: str) -> list[dict]:
    return [
        {
            "slug": item["slug"],
            "name": item["name"],
            "description": item["description"],
            "source_type": item["source_type"],
        }
        for item in list_installed(profile_name)
    ]
