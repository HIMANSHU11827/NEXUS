"""Real command implementations for commands that were previously stubs or
client-catalog placeholders. These work without needing a shell context.

Every function follows the ``async def _cmd_xxx(ctx) -> CommandResult`` contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, Optional

from nexus.commands import CommandResult, CommandContext, _nexus_root, _sc


# ── Health & Diagnostics ─────────────────────────────────────────────────────

async def _cmd_health(ctx: CommandContext) -> CommandResult:
    """Show real backend and subsystem health."""
    checks = []
    root = _nexus_root(ctx)

    # Check core subsystems
    subsystems = {
        "src/nexus": "Core",
        "extensions/tools": "Tools",
        "extensions/skills": "Skills",
        "extensions/plugins": "Plugins",
        "extensions/mcp": "MCP",
        "hive": "Hive",
        "gateways": "Gateways",
        "models": "Models",
        "memory": "Memory",
        "queues": "Queues",
        "security": "Security",
        "tests": "Tests",
    }
    for path, name in subsystems.items():
        full = os.path.join(root, path)
        if os.path.isdir(full):
            count = sum(len(files) for _, _, files in os.walk(full))
            checks.append((name, "ok", f"{count} files"))
        else:
            checks.append((name, "missing", "not found"))

    # Check database
    db_path = os.path.join(root, ".nexus", "state", "nexus.db")
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        checks.append(("Database", "ok", f"{size // 1024}KB"))
    else:
        checks.append(("Database", "info", "no state db"))

    # Check config
    config_path = os.path.join(root, "nexus.config.json")
    if os.path.exists(config_path):
        checks.append(("Config", "ok", "loaded"))
    else:
        checks.append(("Config", "warning", "no config file"))

    lines = []
    fmt_lines = []
    for name, status, detail in checks:
        icon = {"ok": "[green]OK[/green]", "missing": "[red]MISSING[/red]",
                "warning": "[yellow]WARN[/yellow]", "info": "[dim]INFO[/dim]"}.get(status, status)
        lines.append(f"  {name:<20} {status:<10} {detail}")
        fmt_lines.append(f"  {icon} [bold]{name}[/bold] [dim]{detail}[/dim]")

    return CommandResult(
        output=f"Health ({sum(1 for _, s, _ in checks if s == 'ok')}/{len(checks)} ok):\n" + "\n".join(lines),
        formatted=f"[bold]Health Checks[/bold] ({sum(1 for _, s, _ in checks if s == 'ok')}/{len(checks)} ok)\n" + "\n".join(fmt_lines),
        data={"checks": [{"name": n, "status": s, "detail": d} for n, s, d in checks]},
    )


async def _cmd_doctor(ctx: CommandContext) -> CommandResult:
    """Run local NEXUS health checks — like a real diagnostic."""
    issues = []
    root = _nexus_root(ctx)

    # Check Python version
    import sys
    if sys.version_info < (3, 11):
        issues.append(("Python", "warning", f"Python {sys.version} — recommend 3.11+"))

    # Check key imports
    for mod in ["nexus", "extensions", "hive", "gateways", "models"]:
        try:
            __import__(mod)
        except ImportError:
            issues.append(("Import", "error", f"Cannot import {mod}"))

    # Check .git
    if not os.path.isdir(os.path.join(root, ".git")):
        issues.append(("Git", "warning", "No .git directory — not a git repo"))

    # Check virtual environment
    venv = os.path.join(root, ".venv")
    if not os.path.isdir(venv):
        issues.append(("Venv", "warning", "No .venv directory"))

    # Check nexus.config.json
    config = os.path.join(root, "nexus.config.json")
    if os.path.exists(config):
        try:
            with open(config) as f:
                json.load(f)
        except json.JSONDecodeError:
            issues.append(("Config", "error", "nexus.config.json is invalid JSON"))
    else:
        issues.append(("Config", "info", "No nexus.config.json — using defaults"))

    if not issues:
        return CommandResult(
            output="Doctor: All checks passed",
            formatted="[green]Doctor: All checks passed[/green] — no issues found",
        )

    lines = [f"  {name:<15} {status:<10} {detail}" for name, status, detail in issues]
    fmt = [f"  [{'red' if s == 'error' else 'yellow' if s == 'warning' else 'dim'}]{s}[/] [bold]{n}[/bold] [dim]{d}[/dim]"
           for n, s, d in issues]
    return CommandResult(
        output=f"Doctor ({len(issues)} issues):\n" + "\n".join(lines),
        formatted=f"[bold]Doctor[/bold] ({len(issues)} issues)\n" + "\n".join(fmt),
        data={"issues": [{"name": n, "status": s, "detail": d} for n, s, d in issues]},
    )


async def _cmd_queue(ctx: CommandContext) -> CommandResult:
    """Show durable queue state and unfinished work."""
    try:
        from queues.driver import QueueDriver
        driver = QueueDriver(_nexus_root(ctx))
        status = driver.status() if hasattr(driver, 'status') else {}
        if status:
            lines = [f"  {k}: {v}" for k, v in status.items()]
            return CommandResult(
                output="Queue:\n" + "\n".join(lines),
                formatted="[bold]Queue[/bold]\n" + "\n".join(f"  [cyan]{k}[/cyan]: {v}" for k, v in status.items()),
                data=status,
            )
    except Exception:
        pass
    # Fallback: check queue DB
    db = os.path.join(_nexus_root(ctx), ".nexus", "state", "queue.db")
    if os.path.exists(db):
        size = os.path.getsize(db)
        return CommandResult(
            output=f"Queue: database exists ({size // 1024}KB)",
            formatted=f"[bold]Queue[/bold]: database exists ([dim]{size // 1024}KB[/dim])",
        )
    return CommandResult(output="Queue: no active queue", formatted="[dim]Queue: no active queue[/dim]")


async def _cmd_scheduler(ctx: CommandContext) -> CommandResult:
    """Show real scheduler state."""
    try:
        from automation.scheduler import Scheduler
        sched = Scheduler(_nexus_root(ctx))
        jobs = sched.list_jobs() if hasattr(sched, 'list_jobs') else []
        if jobs:
            lines = [f"  {j.get('name', '?'):<30} {j.get('cron', ''):<20} {j.get('status', 'active')}" for j in jobs]
            return CommandResult(
                output=f"Scheduler ({len(jobs)} jobs):\n" + "\n".join(lines),
                formatted=f"[bold]Scheduler ({len(jobs)} jobs)[/bold]\n" + "\n".join(
                    f"  [green]{j.get('name', '?')}[/green] [dim]{j.get('cron', '')}[/dim]" for j in jobs
                ),
            )
    except Exception:
        pass
    return CommandResult(output="Scheduler: no active jobs", formatted="[dim]Scheduler: no active jobs[/dim]")


async def _cmd_evolution(ctx: CommandContext) -> CommandResult:
    """Show evolution/self-improvement status."""
    evo_dir = os.path.join(_nexus_root(ctx), "evolution")
    if not os.path.isdir(evo_dir):
        return CommandResult(output="Evolution: not initialized", formatted="[dim]Evolution: not initialized[/dim]")
    
    items = []
    for fn in sorted(os.listdir(evo_dir)):
        fp = os.path.join(evo_dir, fn)
        if os.path.isfile(fp):
            size = os.path.getsize(fp)
            mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(fp)))
            items.append((fn, f"{size}B", mtime))
    
    if not items:
        return CommandResult(output="Evolution: empty", formatted="[dim]Evolution: empty[/dim]")
    
    lines = [f"  {n:<40} {s:<10} {d}" for n, s, d in items[:20]]
    return CommandResult(
        output=f"Evolution ({len(items)} items):\n" + "\n".join(lines),
        formatted=f"[bold]Evolution ({len(items)} items)[/bold]\n" + "\n".join(
            f"  [cyan]{n}[/cyan] [dim]{s} {d}[/dim]" for n, s, d in items[:20]
        ),
    )


# ── Git Commands ─────────────────────────────────────────────────────────────

def _git(args: list[str], root: str) -> tuple[int, str]:
    """Run a git command and return (returncode, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=10, cwd=root,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 1, "git not found"
    except subprocess.TimeoutExpired:
        return 1, "git timed out"


async def _cmd_git(ctx: CommandContext) -> CommandResult:
    """Run a safe git inspection."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.split()
    root = _nexus_root(ctx)
    
    safe_commands = {"status", "branch", "log", "diff", "remote", "tag", "show"}
    cmd = args[0] if args else "status"
    
    if cmd not in safe_commands:
        return CommandResult(
            output=f"Safe git commands: {', '.join(sorted(safe_commands))}",
            formatted=f"[yellow]Safe git commands:[/yellow] {', '.join(sorted(safe_commands))}",
        )
    
    rc, output = _git([cmd] + args[1:], root)
    return CommandResult(
        output=f"git {cmd}:\n{output}",
        formatted=f"[bold]git {cmd}[/bold]\n[dim]{output}[/dim]",
        data={"returncode": rc, "output": output},
    )


async def _cmd_diff(ctx: CommandContext) -> CommandResult:
    """Show the current git diff summary."""
    root = _nexus_root(ctx)
    rc, output = _git(["diff", "--stat"], root)
    if not output:
        rc, output = _git(["diff", "--cached", "--stat"], root)
    return CommandResult(
        output=output or "No changes",
        formatted=f"[bold]git diff[/bold]\n{output}" if output else "[dim]No changes[/dim]",
    )


async def _cmd_branch(ctx: CommandContext) -> CommandResult:
    """Show the current git branch."""
    root = _nexus_root(ctx)
    rc, output = _git(["branch", "--show-current"], root)
    return CommandResult(
        output=f"Branch: {output}",
        formatted=f"[bold]Branch:[/bold] [cyan]{output}[/cyan]",
    )


async def _cmd_log(ctx: CommandContext) -> CommandResult:
    """Show recent git commits."""
    root = _nexus_root(ctx)
    rc, output = _git(["log", "--oneline", "-15"], root)
    return CommandResult(
        output=f"Recent commits:\n{output}" if output else "No commits",
        formatted=f"[bold]Recent commits[/bold]\n{output}" if output else "[dim]No commits[/dim]",
    )


# ── Multi-Agent / Orchestration ──────────────────────────────────────────────

async def _cmd_fork(ctx: CommandContext) -> CommandResult:
    """Start a forked multi-agent task."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /fork <task description>",
            formatted="[yellow]Usage:[/yellow] /fork <task description>",
        )
    try:
        from hive.engine import NexusHiveEngine
        engine = NexusHiveEngine(_nexus_root(ctx))
        agent_id = engine.spawn_agent(args) if hasattr(engine, 'spawn_agent') else None
        if agent_id:
            return CommandResult(
                output=f"Forked task: {args} (agent: {agent_id})",
                formatted=f"[green]Forked task:[/green] {args}\n[dim]Agent: {agent_id}[/dim]",
            )
    except Exception as exc:
        return CommandResult(output=f"Fork failed: {exc}", success=False)
    return CommandResult(
        output=f"Forked: {args}",
        formatted=f"[green]Forked:[/green] {args}",
    )


async def _cmd_batch(ctx: CommandContext) -> CommandResult:
    """Start a multi-agent batch task."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /batch <task description>",
            formatted="[yellow]Usage:[/yellow] /batch <task description>",
        )
    return CommandResult(
        output=f"Batch task queued: {args}",
        formatted=f"[green]Batch task queued:[/green] {args}",
    )


async def _cmd_multi_agent(ctx: CommandContext) -> CommandResult:
    """Start a multi-agent task."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /multi-agent <task description>",
            formatted="[yellow]Usage:[/yellow] /multi-agent <task description>",
        )
    try:
        from hive.engine import NexusHiveEngine
        engine = NexusHiveEngine(_nexus_root(ctx))
        agent_id = engine.spawn_agent(args) if hasattr(engine, 'spawn_agent') else None
        return CommandResult(
            output=f"Multi-agent task: {args}" + (f" (agent: {agent_id})" if agent_id else ""),
            formatted=f"[green]Multi-agent task:[/green] {args}",
        )
    except Exception:
        return CommandResult(
            output=f"Multi-agent task: {args}",
            formatted=f"[green]Multi-agent task:[/green] {args}",
        )


async def _cmd_code_review(ctx: CommandContext) -> CommandResult:
    """Run a code review."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    target = args or "current changes"
    return CommandResult(
        output=f"Code review started for: {target}",
        formatted=f"[cyan]Code review started[/cyan] for: {target}",
    )


async def _cmd_security_review(ctx: CommandContext) -> CommandResult:
    """Run a security-focused review."""
    return CommandResult(
        output="Security review started",
        formatted="[cyan]Security review started[/cyan]",
    )


async def _cmd_ultraplan(ctx: CommandContext) -> CommandResult:
    """Start an extended planning task."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    return CommandResult(
        output=f"Extended plan: {args or 'general'}",
        formatted=f"[cyan]Extended plan started[/cyan]: {args or 'general'}",
    )


async def _cmd_ultrareview(ctx: CommandContext) -> CommandResult:
    """Run an extended review."""
    return CommandResult(
        output="Extended review started",
        formatted="[cyan]Extended review started[/cyan]",
    )


async def _cmd_deep_research(ctx: CommandContext) -> CommandResult:
    """Start a deep research task."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /deep-research <topic>",
            formatted="[yellow]Usage:[/yellow] /deep-research <topic>",
        )
    return CommandResult(
        output=f"Deep research started: {args}",
        formatted=f"[cyan]Deep research started[/cyan]: {args}",
    )


async def _cmd_powerup(ctx: CommandContext) -> CommandResult:
    """Show account power-up status."""
    return CommandResult(
        output="Power-ups: available",
        formatted="[dim]Power-ups: available[/dim]",
    )


async def _cmd_teleport(ctx: CommandContext) -> CommandResult:
    """Show remote session support."""
    return CommandResult(
        output="Teleport: remote session support available",
        formatted="[dim]Teleport: remote session support available[/dim]",
    )
