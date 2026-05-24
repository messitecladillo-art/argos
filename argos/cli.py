"""Argos management CLI.

Usage:
    argos-cli check       # Validate configuration
    argos-cli backup      # Backup the SQLite database
    argos-cli info        # Show system information
    argos-cli migrate     # Run database migrations
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import (
    AGENT_TEAM_WORKSPACE_ROOT,
    DATABASE_URL,
    HERMES_HOME,
    KANBAN_BOARD,
    MCP_BUS_URL,
    SECRET_KEY,
    validate_config,
)

console = Console()


def _banner() -> None:
    title = Text("\nA R G O S", style="bold bright_cyan")
    subtitle = Text("Multi-Agent Collaboration System", style="dim italic")
    console.print(Panel(
        title + "\n" + subtitle,
        border_style="bright_cyan",
        padding=(1, 8),
    ))
    console.print()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Argos -- Multi-Agent Collaboration System CLI",
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
    _banner()
    console.print(Rule("Configuration Check", style="cyan"))
    console.print()

    issues = validate_config()
    if issues:
        console.print("[bold red]Issues found:[/bold red]")
        for msg in issues:
            console.print(f"  [red]✗[/red] {msg}")
        console.print()
        return 1

    tree = Tree(Text("All checks passed", style="green bold"), guide_style="dim cyan")
    tree.add(f"DATABASE_URL  [dim]=[/dim] {_mask_db_url(DATABASE_URL)}")
    tree.add(f"HERMES_HOME   [dim]=[/dim] {HERMES_HOME}")
    sec = tree.add("SECRET_KEY")
    if SECRET_KEY:
        sec.add("[green]set[/green]")
    else:
        sec.add("[yellow]not set (dev mode)[/yellow]")

    console.print(Panel(tree, border_style="green", title="PASS"))
    console.print()
    return 0


def cmd_backup(args) -> int:
    _banner()
    console.print(Rule("Database Backup", style="cyan"))
    console.print()

    if not DATABASE_URL.startswith("sqlite:///"):
        console.print("[red]Backup only supports SQLite databases.[/red]")
        return 1

    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if not db_path.is_file():
        console.print(f"[red]Database file not found:[/red] {db_path}")
        return 1

    if args.output:
        dest = Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = db_path.parent / f"{db_path.stem}_backup_{ts}.db"

    with console.status("[bold cyan]Creating backup...", spinner="dots"):
        time.sleep(0.15)
        shutil.copy2(db_path, dest)

    size_kb = dest.stat().st_size / 1024
    console.print()

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim", width=8)
    info.add_column()
    info.add_row("Path", str(dest))
    info.add_row("Size", f"[green bold]{size_kb:.1f} KB[/green bold]")

    console.print(Panel(info, border_style="green", title="[green]Backup Complete[/green]"))
    console.print()
    return 0


def cmd_info() -> int:
    _banner()
    console.print(Rule("System Information", style="cyan"))
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
    table.add_column("Key", style="dim cyan", width=18)
    table.add_column("Value")

    table.add_row("Python", Text(sys.version.split()[0], style="bold"))
    table.add_row("DATABASE_URL", _mask_db_url(DATABASE_URL))
    table.add_row("HERMES_HOME", str(HERMES_HOME))
    table.add_row("WORKSPACE_ROOT", str(AGENT_TEAM_WORKSPACE_ROOT))
    table.add_row("KANBAN_BOARD", KANBAN_BOARD)
    table.add_row("MCP_BUS_URL", MCP_BUS_URL)

    sec_style = "green bold" if SECRET_KEY else "yellow"
    table.add_row("SECRET_KEY", f"[{sec_style}]{'set' if SECRET_KEY else 'not set'}[/{sec_style}]")

    api_style = "green bold" if os.environ.get("API_TOKEN") else "dim"
    table.add_row("API_TOKEN", f"[{api_style}]{'set' if os.environ.get('API_TOKEN') else 'not set'}[/{api_style}]")

    debug = os.environ.get("FLASK_DEBUG", "0")
    debug_style = "yellow bold" if debug == "1" else "dim"
    table.add_row("FLASK_DEBUG", f"[{debug_style}]{debug}[/{debug_style}]")

    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        if db_path.is_file():
            size_kb = db_path.stat().st_size / 1024
            table.add_row("DB size", f"[green]{size_kb:.1f} KB[/green]")
        else:
            table.add_row("DB size", "[yellow]not created yet[/yellow]")

    console.print(Panel(table, border_style="blue"))
    console.print()
    return 0


def cmd_migrate() -> int:
    from .db import init_database

    _banner()
    console.print(Rule("Database Migration", style="cyan"))
    console.print()

    with console.status("[bold cyan]Running Alembic migrations...", spinner="dots"):
        init_database()

    console.print()
    console.print(Panel("[green bold]Migrations complete.[/green bold]", border_style="green"))
    console.print()
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
        console.print(Panel(
            Text("\nA R G O S\n", style="bold bright_cyan") +
            Text("Multi-Agent Collaboration System\n", style="dim italic") +
            Text("\nUse --help for available commands.\n", style="dim"),
            border_style="bright_cyan",
            padding=(1, 8),
        ))
        console.print()
        sys.exit(0)


if __name__ == "__main__":
    main()
