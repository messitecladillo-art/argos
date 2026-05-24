"""Hermes Agent Team management CLI.

Usage:
    hermes-mgmt check       # Validate configuration
    hermes-mgmt backup      # Backup the SQLite database
    hermes-mgmt info        # Show system information
    hermes-mgmt migrate     # Run database migrations
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    AGENT_TEAM_WORKSPACE_ROOT,
    DATABASE_URL,
    HERMES_HOME,
    KANBAN_BOARD,
    MCP_BUS_URL,
    SECRET_KEY,
    validate_config,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hermes Agent Team management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("check", help="Validate configuration and report issues")
    backup_p = sub.add_parser("backup", help="Backup the SQLite database")
    backup_p.add_argument("--output", "-o", help="Backup file path (default: auto-generate)")
    sub.add_parser("info", help="Show system information")
    sub.add_parser("migrate", help="Run database migrations")

    return parser.parse_args()


def cmd_check() -> int:
    print("Checking configuration...")
    issues = validate_config()
    if issues:
        for msg in issues:
            print(f"  FAIL  {msg}")
        return 1

    print(f"  OK    DATABASE_URL = {_mask_db_url(DATABASE_URL)}")
    print(f"  OK    HERMES_HOME = {HERMES_HOME}")
    print(f"  OK    SECRET_KEY = {'set' if SECRET_KEY else 'not set (dev mode)'}")
    print("All checks passed.")
    return 0


def cmd_backup(args) -> int:
    if not DATABASE_URL.startswith("sqlite:///"):
        print("Backup only supports SQLite databases.")
        return 1

    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if not db_path.is_file():
        print(f"Database file not found: {db_path}")
        return 1

    if args.output:
        dest = Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = db_path.parent / f"{db_path.stem}_backup_{ts}.db"

    shutil.copy2(db_path, dest)
    size_kb = dest.stat().st_size / 1024
    print(f"Backup created: {dest} ({size_kb:.1f} KB)")
    return 0


def cmd_info() -> int:
    print("Hermes Agent Team — System Information")
    print(f"  Python         {sys.version.split()[0]}")
    print(f"  DATABASE_URL   {_mask_db_url(DATABASE_URL)}")
    print(f"  HERMES_HOME    {HERMES_HOME}")
    print(f"  WORKSPACE_ROOT {AGENT_TEAM_WORKSPACE_ROOT}")
    print(f"  KANBAN_BOARD   {KANBAN_BOARD}")
    print(f"  MCP_BUS_URL    {MCP_BUS_URL}")
    print(f"  SECRET_KEY     {'set' if SECRET_KEY else 'not set'}")
    print(f"  API_TOKEN      {'set' if os.environ.get('API_TOKEN') else 'not set'}")
    print(f"  FLASK_DEBUG    {os.environ.get('FLASK_DEBUG', '0')}")

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        if db_path.is_file():
            size_kb = db_path.stat().st_size / 1024
            print(f"  DB size        {size_kb:.1f} KB")

    return 0


def cmd_migrate() -> int:
    from .db import init_database

    print("Running database migrations...")
    init_database()
    print("Migrations complete.")
    return 0


def _mask_db_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        return f"sqlite:///{Path(path).name}" if "/" in path or "\\" in path else url
    if "@" in url:
        return url.split("@")[0].rsplit(":", 1)[0] + ":***@" + url.split("@")[1]
    return url


def main() -> None:
    args = _parse_args()
    if args.command == "check":
        sys.exit(cmd_check())
    elif args.command == "backup":
        sys.exit(cmd_backup(args))
    elif args.command == "info":
        sys.exit(cmd_info())
    elif args.command == "migrate":
        sys.exit(cmd_migrate())
    else:
        _parse_args().print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
