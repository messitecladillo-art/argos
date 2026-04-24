from __future__ import annotations

import subprocess

from ..config import PROFILE_NAME_RE


class ProfileError(RuntimeError):
    """Raised when the hermes CLI fails for a non-business reason."""


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
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
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
