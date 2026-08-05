"""Central command registry — single source of truth for ALL commands.

TUI, GUI, and all gateways import the same registry. Every command is
registered here with a category, description, and async handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandContext:
    """Context passed to every command handler."""
    session_id: str = "default"
    mode: str = "auto"
    provider: str = "lm_studio"
    model: str = "kimi-k2.6"
    thinking: bool = True
    loop: Any = None          # NexusLoop instance (optional)
    shell: Any = None         # NexusShell instance (optional)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result returned by every command handler."""
    success: bool = True
    output: str = ""
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    formatted: str = ""       # Rich-markup formatted output (TUI)
    content_type: str = "text"


class Command:
    """A registered slash command with metadata and handler."""

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[[CommandContext], Awaitable[CommandResult]],
        category: str = "general",
        args: Optional[Dict[str, str]] = None,
        aliases: Optional[List[str]] = None,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.category = category
        self.args = args or {}
        self.aliases = aliases or []

    async def execute(self, ctx: CommandContext) -> CommandResult:
        try:
            return await self.handler(ctx)
        except Exception as e:
            logger.warning("command '%s' failed: %s", self.name, e, exc_info=True)
            return CommandResult(success=False, error=str(e), output=f"Error: {e}")

    def __repr__(self) -> str:
        return f"<Command /{self.name} [{self.category}]>"


class CommandRegistry:
    """Singleton registry of all slash commands."""

    _instance: Optional[CommandRegistry] = None

    def __new__(cls) -> CommandRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands: Dict[str, Command] = {}
            cls._instance._by_name: Dict[str, Command] = {}
            cls._instance._initialized = False
        return cls._instance

    def register(self, cmd: Command) -> None:
        self._commands[cmd.name] = cmd
        self._by_name[cmd.name] = cmd
        for alias in cmd.aliases:
            self._by_name[alias] = cmd
        logger.debug("Registered command: /%s [%s]", cmd.name, cmd.category)

    def get(self, name: str) -> Optional[Command]:
        name = name.lstrip("/").lower()
        return self._by_name.get(name)

    def list(self, category: str = "") -> List[Command]:
        cmds = list(self._commands.values())
        if category:
            cmds = [c for c in cmds if c.category == category]
        return sorted(cmds, key=lambda c: c.name)

    def categories(self) -> List[str]:
        cats = set()
        for c in self._commands.values():
            cats.add(c.category)
        return sorted(cats)

    def execute(self, name: str, ctx: CommandContext) -> Awaitable[CommandResult]:
        cmd = self.get(name)
        if not cmd:
            raise ValueError(f"Unknown command: /{name}")
        return cmd.execute(ctx)

    @property
    def all_commands(self) -> Dict[str, Command]:
        return dict(self._commands)


# ── Status color helper ───────────────────────────────────────────────────────

def _sc(status: str) -> str:
    return {"success": "green", "running": "cyan", "failed": "red", "pending": "grey50"}.get(status, "white")


# ── General Commands ───────────────────────────────────────────────────────────

async def _cmd_help(ctx: CommandContext) -> CommandResult:
    reg = CommandRegistry()
    lines = []
    for cat in reg.categories():
        lines.append(f"\n[{cat}]")
        for cmd in reg.list(cat):
            lines.append(f"  /{cmd.name:<15} {cmd.description}")
    output = "\n".join(lines).strip()
    formatted = f"[bold cyan]NEXUS Commands[/bold cyan]\n{output}"
    return CommandResult(output=output, formatted=formatted, data={"categories": reg.categories()})


async def _cmd_clear(ctx: CommandContext) -> CommandResult:
    import os
    os.system("cls" if os.name == "nt" else "clear")
    return CommandResult(output="Screen cleared", formatted="", content_type="text")


async def _cmd_exit(ctx: CommandContext) -> CommandResult:
    return CommandResult(output="exit", formatted="[bold red]SESSION TERMINATED.[/bold red]", data={"exit": True})


async def _cmd_new(ctx: CommandContext) -> CommandResult:
    import time
    if not ctx.shell:
        return CommandResult(output="New session requires a shell context", success=False)
    ctx.shell._apply_session(f"session_{int(time.time())}")
    if ctx.loop:
        ctx.loop.save_memory()
    return CommandResult(
        output=f"New session: {ctx.shell.session_id}",
        formatted=f"[green]New session: {ctx.shell.session_id}[/green]\n[dim]Same session id is visible in GUI and gateway.[/dim]",
    )


async def _cmd_sessions(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._list_sessions()
    return CommandResult()


async def _cmd_session(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    if len(parts) > 1 and ctx.shell:
        ctx.shell._apply_session(parts[1])
        return CommandResult(
            output=f"Switched to session: {ctx.shell.session_id}",
            formatted=f"[green]Switched to session: {ctx.shell.session_id}[/green]",
        )
    return CommandResult(output="Usage: /session <id>", success=False)


async def _cmd_run(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    if len(parts) > 1:
        command = " ".join(parts[1:])
        if ctx.shell:
            try:
                asyncio.get_running_loop().create_task(ctx.shell._run_bash(command))
            except RuntimeError:
                return CommandResult(output="No running event loop", success=False)
        return CommandResult(output=f"Running: {command}", formatted=f"[cyan]Command started:[/cyan] {command}")
    return CommandResult(output="Usage: /run <command>", success=False)


async def _cmd_gui(ctx: CommandContext) -> CommandResult:
    if not ctx.shell:
        return CommandResult(output="GUI requires a shell context", success=False)
    import os as _os
    import subprocess as _sp
    script_path = _os.path.join(ctx.shell.brain.root, "scripts", "run-gui.ps1")
    if not _os.path.exists(script_path):
        return CommandResult(output=f"GUI script not found: {script_path}", success=False)
    _sp.Popen(
        ["powershell", "-NoLogo", "-ExecutionPolicy", "Bypass", "-File", script_path],
        cwd=ctx.shell.brain.root,
        creationflags=_sp.CREATE_NEW_CONSOLE if _os.name == "nt" else 0,
    )
    return CommandResult(
        output="Launching NEXUS GUI...",
        formatted="[bold cyan]Launching NEXUS GUI via PowerShell...[/bold cyan]\nBackend API: http://127.0.0.1:8000\nReact Frontend: http://127.0.0.1:5173",
    )


async def _cmd_review(ctx: CommandContext) -> CommandResult:
    return await _cmd_agent_task(ctx, "review",
        "Review the current project changes. Report concrete defects with file evidence and verify relevant tests.")


async def _cmd_simplify(ctx: CommandContext) -> CommandResult:
    return await _cmd_agent_task(ctx, "simplify",
        "Simplify the current project changes without changing behavior. Verify the result with relevant tests.")


async def _cmd_verify(ctx: CommandContext) -> CommandResult:
    return await _cmd_agent_task(ctx, "verify",
        "Verify the current project changes with relevant tests and report exact evidence, failures, and next actions.")


async def _cmd_agent_task(ctx: CommandContext, name: str, prompt: str) -> CommandResult:
    from nexus.commands import TaskTracker
    tid = TaskTracker.create(f"/{name}", agent="multi-agent")
    TaskTracker.update(tid, "running")
    if ctx.shell:
        ctx.shell._pending_agent_prompt = prompt
        ctx.shell._pending_task_id = tid
    return CommandResult(
        output=f"{name.title()} started · task {tid}",
        formatted=f"[bold cyan]{name.title()} started · task {tid}[/bold cyan]",
    )


# ── Settings Commands ──────────────────────────────────────────────────────────

async def _cmd_mode(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    if len(parts) > 1:
        new_mode = parts[1].strip().lower()
        aliases = {
            "accept": "acceptEdits", "acceptedits": "acceptEdits", "accept_edits": "acceptEdits",
            "dontask": "dontAsk", "dont_ask": "dontAsk",
            "plan": "plan", "auto": "auto", "default": "auto",
        }
        resolved = aliases.get(new_mode, new_mode)
        if ctx.shell:
            ctx.shell.mode = resolved
        return CommandResult(output=f"Mode: {resolved}", formatted=f"[green]Mode: {resolved}[/green]")
    return CommandResult(
        output=f"Current mode: {ctx.mode}",
        formatted=f"[yellow]Current mode:[/yellow] {ctx.mode}\n[grey70]Allowed: auto, plan, acceptEdits, dontAsk[/grey70]",
    )


async def _cmd_model(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    if len(parts) > 1:
        raw = " ".join(parts[1:]).strip()
        provider = ctx.provider
        model = ctx.model
        if ":" in raw:
            p, m = raw.split(":", 1)
            provider = (p or "").strip().lower()
            model = (m or "").strip()
        elif raw:
            model = raw
        if ctx.shell:
            ctx.shell.provider = provider
            ctx.shell.model = model
        return CommandResult(
            output=f"Provider: {provider}, Model: {model}",
            formatted=f"[green]Provider:[/green] {provider}\n[green]Model:[/green] {model}",
        )
    return CommandResult(
        output=f"Provider: {ctx.provider}, Model: {ctx.model}",
        formatted=f"[cyan]Provider:[/cyan] {ctx.provider}\n[cyan]Model:[/cyan] {ctx.model}",
    )


async def _cmd_thinking(ctx: CommandContext) -> CommandResult:
    new_state = not ctx.thinking
    if ctx.loop and hasattr(ctx.loop, 'configure_thinking'):
        ctx.loop.configure_thinking(new_state)
    state = "ON" if new_state else "OFF"
    return CommandResult(
        output=f"Thinking: {state}",
        formatted=f"[cyan]Thinking mode: {state}[/cyan]",
        data={"thinking": new_state},
    )


async def _cmd_auto(ctx: CommandContext) -> CommandResult:
    return await _cmd_mode_shortcut(ctx, "auto")


async def _cmd_plan(ctx: CommandContext) -> CommandResult:
    return await _cmd_mode_shortcut(ctx, "plan")


async def _cmd_accept(ctx: CommandContext) -> CommandResult:
    return await _cmd_mode_shortcut(ctx, "acceptEdits")


async def _cmd_dontask(ctx: CommandContext) -> CommandResult:
    return await _cmd_mode_shortcut(ctx, "dontAsk")


async def _cmd_mode_shortcut(ctx: CommandContext, mode: str) -> CommandResult:
    if ctx.shell:
        ctx.shell.mode = mode
    return CommandResult(
        output=f"Mode: {mode}",
        formatted=f"[green]Mode: {mode}[/green]",
    )


async def _cmd_config(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_config()
    return CommandResult()


# ── Info Commands ─────────────────────────────────────────────────────────────

async def _cmd_status(ctx: CommandContext) -> CommandResult:
    info = [
        f"Session: {ctx.session_id}",
        f"Mode: {ctx.mode}",
        f"Provider: {ctx.provider}",
        f"Model: {ctx.model}",
        f"Thinking: {'ON' if ctx.thinking else 'OFF'}",
    ]
    if ctx.loop:
        info.append(f"Agent: {getattr(ctx.loop, 'agent_id', 'default')}")
    output = "\n".join(info)
    formatted = "\n".join(
        f"  [dim]{k}:[/dim] [white]{v}[/white]"
        for k, v in (s.split(": ", 1) for s in info)
    )
    return CommandResult(output=output, formatted=f"[bold]System Status[/bold]\n{formatted}", data={"mode": ctx.mode})


async def _cmd_version(ctx: CommandContext) -> CommandResult:
    import sys
    lines = [
        "NEXUS AI v2.1",
        "  Shell: Rich-based TUI",
        "  Backend: FastAPI port 8000",
        "  GUI: React 19 + Vite port 5173",
        f"  Providers: {ctx.provider}:{ctx.model}",
        f"  Python: {sys.version.split()[0]}",
        "  Hive: Sub-agent engine active",
    ]
    formatted_lines = [
        f"[bold]{'NEXUS AI v2.1':^50}[/bold]",
        "  [dim]Shell:[/dim] Rich-based TUI",
        "  [dim]Backend:[/dim] FastAPI port 8000",
        "  [dim]GUI:[/dim] React 19 + Vite port 5173",
        f"  [dim]Providers:[/dim] {ctx.provider}:{ctx.model}",
        f"  [dim]Python:[/dim] {sys.version.split()[0]}",
        "  [dim]Hive:[/dim] Sub-agent engine active",
    ]
    return CommandResult(output="\n".join(lines), formatted="\n".join(formatted_lines))


async def _cmd_hive(ctx: CommandContext) -> CommandResult:
    agents = []
    if ctx.loop and hasattr(ctx.loop, 'hive') and ctx.loop.hive:
        for a in ctx.loop.hive.list_agents():
            agents.append({"id": a.agent_id, "persona": a.persona, "status": a.status, "task": a.task[:60]})
    if agents:
        lines = [f"  {a['persona']}:{a['id'][:8]} -> {a['status']} | {a['task']}" for a in agents]
        formatted = "\n".join(
            f"  [cyan]{a['persona']}[/cyan] [dim]{a['id'][:8]}[/dim] [{_sc(a['status'])}]{a['status']}[/{_sc(a['status'])}] [grey70]{a['task']}[/grey70]"
            for a in agents
        )
        return CommandResult(
            output=f"Active sub-agents: {len(agents)}\n" + "\n".join(lines),
            formatted=f"[bold]Hive Agents ({len(agents)})[/bold]\n{formatted}",
            data={"agents": agents},
        )
    return CommandResult(output="No active sub-agents", formatted="[dim]No active sub-agents[/dim]")


async def _cmd_tasks(ctx: CommandContext) -> CommandResult:
    from nexus.commands import TaskTracker
    tasks = TaskTracker.list()
    if tasks:
        lines = [f"  {t['id']:<10} {t['subject'][:50]:<50} [{t['status']}]" for t in tasks]
        formatted_lines = [
            f"  [cyan]{t['id']:<10}[/cyan] [white]{t['subject'][:50]:<50}[/white] [{_sc(t['status'])}]{t['status']}[/{_sc(t['status'])}]"
            for t in tasks
        ]
        return CommandResult(
            output=f"Tasks ({len(tasks)}):\n" + "\n".join(lines),
            formatted=f"[bold]Tasks ({len(tasks)})[/bold]\n" + "\n".join(formatted_lines),
            data={"tasks": tasks},
        )
    return CommandResult(output="No active tasks", formatted="[dim]No active tasks[/dim]")


async def _cmd_skills(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_skills()
    return CommandResult()


async def _cmd_tools(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_tools()
    return CommandResult()


async def _cmd_agents(ctx: CommandContext) -> CommandResult:
    """List registered subagents: live Hive workers + .claude/agents specialists."""
    entries = []
    # Real listing: hive engine's list_agents (hive/engine.py) for live workers.
    try:
        from hive import NexusHiveEngine
        engine = NexusHiveEngine(_nexus_root(ctx))
        for a in engine.list_agents():
            entries.append({
                "name": str(getattr(a, "agent_id", "") or "sub"),
                "kind": "hive",
                "persona": str(getattr(a, "persona", "") or ""),
                "status": str(getattr(a, "status", "") or ""),
            })
    except Exception:
        pass
    # Fallback listing: .claude/agents/*.md specialist agent defs.
    agents_dir = os.path.join(_nexus_root(ctx), ".claude", "agents")
    if os.path.isdir(agents_dir):
        for fn in sorted(os.listdir(agents_dir)):
            if fn.endswith(".md") and not fn.startswith("_"):
                entries.append({"name": fn[:-3], "kind": "specialist", "persona": "", "status": "defined"})
    if not entries:
        return CommandResult(output="no data yet", formatted="[dim]No registered subagents yet[/dim]")
    lines = [
        f"  {e['kind']:<11} {e['name']:<28} {e['persona'][:24]:<24} {e['status']}"
        for e in entries
    ]
    return CommandResult(
        output=f"Agents ({len(entries)}):\n" + "\n".join(lines),
        formatted=f"[bold]Agents ({len(entries)})[/bold]\n" + "\n".join(
            f"  [cyan]{e['kind']}[/cyan] [white]{e['name']:<28}[/white] [grey70]{e['persona'][:24]:<24}[/grey70] [{_sc(e['status'])}]{e['status']}[/{_sc(e['status'])}]"
            for e in entries
        ),
        data={"agents": entries},
    )


async def _cmd_memory(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        h = len(ctx.shell.conversation_history)
        s = ctx.shell.session_id
        return CommandResult(
            output=f"History: {h} messages, Session: {s}",
            formatted=f"[cyan]History: {h} messages[/cyan]\n[cyan]Session: {s}[/cyan]",
        )
    return CommandResult(output="No shell context", success=False)


async def _cmd_events(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_work_events()
    return CommandResult()


async def _cmd_system(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_system_map()
    return CommandResult()


async def _cmd_plugins(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_plugins()
    return CommandResult()


async def _cmd_forge(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_forge_status()
    return CommandResult()


async def _cmd_providers(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_provider_dashboard()
    return CommandResult()


async def _cmd_monitor(ctx: CommandContext) -> CommandResult:
    if ctx.shell:
        ctx.shell._show_agent_monitor()
    return CommandResult()


# ── Shared helpers for state-backed commands ──────────────────────────────

def _nexus_root(ctx: CommandContext) -> str:
    """Resolve the project root; tests may pin it via ctx.extra['root']."""
    overrides = (
        ctx.extra.get("root")
        or getattr(ctx.loop, "root_dir", None)
        or getattr(ctx.loop, "root", None)
        or (getattr(getattr(ctx, "shell", None), "brain", None) and getattr(ctx.shell.brain, "root", None))
    )
    return str(overrides or os.getcwd())


def _sessions_dir(ctx: CommandContext) -> str:
    return os.path.join(_nexus_root(ctx), "logs", "sessions")


def _latest_session_file(ctx: CommandContext) -> str:
    """Path of the most recently written session JSON in logs/sessions; '' on failure."""
    directory = ctx.extra.get("sessions_dir") or _sessions_dir(ctx)
    if not os.path.isdir(directory):
        return ""
    candidates = [
        os.path.join(directory, fn)
        for fn in os.listdir(directory)
        if fn.endswith(".json") and not fn.endswith(".meta")
    ]
    if not candidates:
        return ""
    return max(candidates, key=os.path.getmtime)


def _load_session_messages(ctx: CommandContext) -> List[Dict[str, Any]]:
    """Read the latest session JSON into a message list; [] on any failure."""
    path = _latest_session_file(ctx)
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict)]


# ── Compact / Context / Resume / Plans / Rewind / Hooks / MCP / Login / Cost ──

async def _cmd_compact(ctx: CommandContext) -> CommandResult:
    """Wire to the real V5 compactor (orchestrators/v5/context_manager.py)."""
    messages = getattr(getattr(ctx, "shell", None), "conversation_history", None)
    if not isinstance(messages, list):
        runtime = getattr(getattr(ctx, "loop", None), "runtime", None)
        runtime_mem = getattr(runtime, "memory", None) if runtime else None
        messages = runtime_mem if isinstance(runtime_mem, list) else []
    if not messages:
        return CommandResult(output="no data yet", formatted="[dim]No conversation history to compact[/dim]")
    try:
        from orchestrators.v5.context_manager import ContextManager
        mgr = ContextManager(_nexus_root(ctx))
        compacted = mgr.compact_context(list(messages))
        dropped = len(messages) - len(compacted)
        return CommandResult(
            output=f"compacted: {len(messages)} -> {len(compacted)} messages (dropped {dropped})",
            formatted=f"[green]compacted:[/green] {len(messages)} -> {len(compacted)} messages (dropped {dropped})",
            data={"before": len(messages), "after": len(compacted), "dropped": dropped},
        )
    except Exception as e:
        return CommandResult(output=f"compact failed: {e}", success=False)


async def _cmd_context(ctx: CommandContext) -> CommandResult:
    """Report session context usage from the latest logs/sessions file."""
    messages = _load_session_messages(ctx)
    if not messages:
        return CommandResult(output="no data yet", formatted="[dim]No session data yet[/dim]")
    est_tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages)
    window = 200000
    pct = (est_tokens / window) * 100
    lines = [
        f"Session: {ctx.session_id}",
        f"Messages: {len(messages)}",
        f"Est tokens: {est_tokens}",
        f"Window: {window:,}",
        f"Utilization: {pct:.1f}%",
    ]
    formatted_lines = [
        "  [dim]Messages:[/dim] [white]%d[/white]" % len(messages),
        "  [dim]Est tokens:[/dim] [cyan]%d[/cyan]" % est_tokens,
        "  [dim]Window:[/dim] [white]%s[/white]" % f"{window:,}",
        "  [dim]Utilization:[/dim] [green]%.1f%%[/green]" % pct,
    ]
    return CommandResult(
        output="\n".join(lines),
        formatted=f"[bold]Context Usage[/bold]\n" + "\n".join(formatted_lines),
        data={"messages": len(messages), "est_tokens": est_tokens, "window": window, "percent": round(pct, 1)},
    )


async def _cmd_resume(ctx: CommandContext) -> CommandResult:
    """Resume the latest run by reading the newest .nexus_v5 checkpoint (real V5Checkpoint reader)."""
    try:
        from orchestrators.v5.checkpoint import V5Checkpoint
        cp = V5Checkpoint()
        cp.root_dir = _nexus_root(ctx)
        entries = cp._checkpoint_list(limit=1)
        if not entries:
            return CommandResult(output="no data yet", formatted="[dim]No checkpoints yet[/dim]")
        path = str(entries[0].get("file") or "")
        data = cp._checkpoint_read(path)
        if not data:
            return CommandResult(output="no data yet", formatted="[dim]Checkpoint unreadable[/dim]")
        lines = [
            f"Checkpoint: {os.path.basename(path)}",
            f"Turn: {data.get('turn_id', '')}  phase: {data.get('phase', '')}",
        ]
        summary = data.get("context_summary")
        if summary:
            lines.append(f"Summary: {str(summary)[:160]}")
        plan = data.get("plan") or data.get("actions")
        if plan:
            plan_str = str(plan)
            lines.append("Next plan/actions: " + plan_str[:200])
        return CommandResult(
            output="\n".join(lines),
            formatted="[bold]Resume[/bold]\n" + "\n".join(f"  {ln}" for ln in lines),
            data=data,
        )
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]No checkpoints yet[/dim]")


async def _cmd_plans(ctx: CommandContext) -> CommandResult:
    """Read the current todo.md plan via the real PlanningTool._read_plan reader."""
    try:
        from tools.planning.scripts.planning import PlanningTool
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]Planning tool unavailable[/dim]")
    root = _nexus_root(ctx)
    for base in (os.path.join(root, "workspace"), root):
        try:
            tool = PlanningTool(root_dir=base)
            plan = tool._read_plan()
        except Exception:
            plan = ""
        if plan:
            return CommandResult(
                output=plan,
                formatted=f"[bold]Plan (todo.md)[/bold]\n{plan}",
                data={"file": os.path.join(base, "todo.md"), "plan": plan},
            )
    return CommandResult(output="no data yet", formatted="[dim]No todo.md plan yet[/dim]")


async def _cmd_rewind(ctx: CommandContext) -> CommandResult:
    """List recent checkpoints and describe what a rewind WOULD do (informational only)."""
    try:
        from orchestrators.v5.checkpoint import V5Checkpoint
        cp = V5Checkpoint()
        cp.root_dir = _nexus_root(ctx)
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]No checkpoints yet[/dim]")
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    limit = 5
    if len(parts) > 1:
        try:
            limit = max(1, min(int(parts[1]), 20))
        except ValueError:
            pass
    entries = cp._checkpoint_list(limit=limit)
    if not entries:
        return CommandResult(output="no data yet", formatted="[dim]No checkpoints yet[/dim]")
    lines = ["Last checkpoints:"]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"  {index}. {os.path.basename(str(entry.get('file') or ''))} "
            f"(turn={entry.get('turn_id', '')} phase={entry.get('phase', '')})"
        )
    target = os.path.basename(str(entries[0].get("file") or ""))
    lines.append("")
    lines.append(f"confirm rewind to 1 → runtime resets to checkpoint '{target}'")
    lines.append("  (file to re-read: " + str(entries[0].get("file") or "") + ")")
    lines.append("Nothing has been changed; this command is informational.")
    formatted_lines = [f"  [cyan]{ln}[/cyan]" if i else f"[bold]{ln}[/bold]" for i, ln in enumerate(lines)]
    return CommandResult(
        output="\n".join(lines),
        formatted="\n".join(formatted_lines),
        data={"candidates": entries},
    )


async def _cmd_hooks(ctx: CommandContext) -> CommandResult:
    """List configured plugin hooks from the real HookRegistry (plugins/manager.py)."""
    try:
        from plugins.manager import HookRegistry
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]Hook registry unavailable[/dim]")
    hook_reg = None
    kernel_plugins = getattr(getattr(ctx, "loop", None), "plugins", None)
    if kernel_plugins is not None:
        hook_reg = getattr(kernel_plugins, "hook_registry", None)
    if hook_reg is None:
        hook_reg = HookRegistry()
    lines = [f"  {event:<20} {len(hook_reg.get_hooks(event))} handler(s)" for event in HookRegistry.PLUGIN_EVENTS]
    return CommandResult(
        output=f"Plugin hooks ({sum(len(hook_reg.get_hooks(e)) for e in HookRegistry.PLUGIN_EVENTS)}):\n" + "\n".join(lines),
        formatted=f"[bold]Plugin Hooks[/bold]\n" + "\n".join(
            f"  [cyan]{event:<20}[/cyan] [white]{len(hook_reg.get_hooks(event))!s:>6}[/white] handler(s)"
            for event in HookRegistry.PLUGIN_EVENTS
        ),
        data={event: len(hook_reg.get_hooks(event)) for event in HookRegistry.PLUGIN_EVENTS},
    )


async def _cmd_mcp(ctx: CommandContext) -> CommandResult:
    """List MCP servers from config/mcp_servers.json with running status (real loader shape)."""
    root = _nexus_root(ctx)
    cfg_path = ctx.extra.get("mcp_config") or os.path.join(root, "config", "mcp_servers.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            servers = json.load(fh)
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]No MCP servers configured[/dim]")
    if isinstance(servers, dict) and isinstance(servers.get("servers"), list):
        # Mirrors the documented {"servers": [...]} shape handled in registry.init_mcp_tools.
        normalized = {}
        for index, item in enumerate(servers["servers"]):
            if isinstance(item, dict):
                normalized[str(item.get("name") or f"server_{index}")] = item
        servers = normalized
    if not isinstance(servers, dict) or not servers:
        return CommandResult(output="no data yet", formatted="[dim]No MCP servers configured[/dim]")
    live_clients = getattr(getattr(ctx, "loop", None), "_mcp_clients", None)
    foreign_names = {}
    if isinstance(live_clients, dict):
        for name, client in live_clients.items():
            foreign_names[str(getattr(client, "command", ""))] = name
    elif isinstance(live_clients, list):
        for client in live_clients:
            foreign_names[str(getattr(client, "command", ""))] = getattr(client, "command", "")
    lines = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        command = str(cfg.get("command") or cfg.get("cmd") or "")
        running = command in foreign_names
        enabled = cfg.get("enabled", cfg.get("active", True)) is not False
        status = "running" if running else ("configured" if enabled else "disabled")
        lines.append(f"  {name:<24} {status}")
    return CommandResult(
        output=f"MCP servers ({len(lines)}):\n" + "\n".join(lines),
        formatted="[bold]MCP Servers[/bold]\n" + "\n".join(lines),
        data={"servers": [name for name in servers if isinstance(servers.get(name), dict)]},
    )


async def _cmd_login(ctx: CommandContext) -> CommandResult:
    """Alias to the auth CLI login: delegates to commands.auth.handle_auth_login."""
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    provider = parts[1] if len(parts) > 1 else ""
    if not provider:
        return CommandResult(output="Usage: /login <provider>", success=False)
    try:
        from types import SimpleNamespace
        from commands.auth import handle_auth_login
        await handle_auth_login(SimpleNamespace(provider=provider, name="default", port=None, host="127.0.0.1"))
    except Exception as e:
        return CommandResult(output=f"login failed: {e}", success=False)
    return CommandResult(
        output=f"login: {provider} initiated",
        formatted=f"[green]Login to '{provider}' initiated[/green]\nFollow the OAuth prompts in the shell.",
    )


async def _cmd_cost(ctx: CommandContext) -> CommandResult:
    """Estimate cost for the latest run at $0.001/1K tokens from logs/sessions."""
    messages = _load_session_messages(ctx)
    if not messages:
        return CommandResult(output="no data yet", formatted="[dim]No session data yet[/dim]")
    in_tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages if m.get("role") == "user")
    out_tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages if m.get("role") == "assistant")
    rate = 0.001  # dollars per 1K tokens
    est_cost = (in_tokens + out_tokens) / 1000.0 * rate
    lines = [
        f"Session: {ctx.session_id}",
        f"Input tokens: {in_tokens}",
        f"Output tokens: {out_tokens}",
        f"Est cost: ${est_cost:.4f} @ ${rate}/1K tokens",
    ]
    formatted_lines = [
        "  [dim]Input tokens:[/dim] [cyan]%d[/cyan]" % in_tokens,
        "  [dim]Output tokens:[/dim] [cyan]%d[/cyan]" % out_tokens,
        f"  [dim]Est cost:[/dim] [green]${est_cost:.4f}[/green] [grey70]@ ${rate}/1K[/grey70]",
    ]
    return CommandResult(
        output="\n".join(lines),
        formatted="[bold]Estimated Cost[/bold]\n" + "\n".join(formatted_lines),
        data={"input_tokens": in_tokens, "output_tokens": out_tokens, "est_cost": round(est_cost, 4)},
    )


# ── Initialize Built-in Commands ────────────────────────────────────────────

def init_registry(registry: Optional[CommandRegistry] = None) -> CommandRegistry:
    """Register all built-in commands. Call once at startup."""
    reg = registry or CommandRegistry()

    builtins = [
        # general
        Command("help", "Show all commands", _cmd_help, category="general", aliases=["h"]),
        Command("clear", "Clear screen", _cmd_clear, category="general"),
        Command("exit", "Exit NEXUS", _cmd_exit, category="general", aliases=["quit"]),
        Command("new", "Create a new session", _cmd_new, category="general"),
        Command("sessions", "List all sessions", _cmd_sessions, category="general"),
        Command("session", "Switch to a session by ID", _cmd_session, category="general"),
        Command("run", "Execute a shell command", _cmd_run, category="general"),
        Command("gui", "Launch the NEXUS GUI", _cmd_gui, category="general"),
        Command("review", "Run an automated code review", _cmd_review, category="general"),
        Command("simplify", "Simplify the current project changes", _cmd_simplify, category="general"),
        Command("verify", "Verify project changes with tests", _cmd_verify, category="general"),

        # settings
        Command("mode", "Get or set mode (auto/plan/acceptEdits/dontAsk)", _cmd_mode, category="settings"),
        Command("model", "Get or set provider:model", _cmd_model, category="settings"),
        Command("thinking", "Toggle thinking mode on/off", _cmd_thinking, category="settings"),
        Command("auto", "Switch to auto mode", _cmd_auto, category="settings"),
        Command("plan", "Switch to plan mode", _cmd_plan, category="settings"),
        Command("accept", "Switch to accept-edits mode", _cmd_accept, category="settings"),
        Command("dontask", "Switch to dont-ask mode", _cmd_dontask, category="settings"),
        Command("config", "Show current configuration", _cmd_config, category="settings"),

        # info
        Command("status", "System status overview", _cmd_status, category="info", aliases=["s"]),
        Command("version", "Show version information", _cmd_version, category="info"),
        Command("hive", "Show active sub-agent hive status", _cmd_hive, category="info"),
        Command("tasks", "Show active tasks", _cmd_tasks, category="info", aliases=["t"]),
        Command("skills", "List installed skills", _cmd_skills, category="info"),
        Command("tools", "List registered tools", _cmd_tools, category="info"),
        Command("agents", "List active agents", _cmd_agents, category="info"),
        Command("memory", "Show memory and session info", _cmd_memory, category="info"),
        Command("events", "Show work events for the session", _cmd_events, category="info"),
        Command("system", "Show comprehensive system overview", _cmd_system, category="info"),
        Command("plugins", "Show plugin registry", _cmd_plugins, category="info"),
        Command("forge", "Show forge/evolution subsystem status", _cmd_forge, category="info"),
        Command("providers", "Show provider dashboard with health", _cmd_providers, category="info"),
        Command("monitor", "Show agent monitor dashboard", _cmd_monitor, category="info"),
        Command("compact", "Compact the conversation context", _cmd_compact, category="general"),
        Command("context", "Report session context usage (tokens, % window)", _cmd_context, category="info"),
        Command("resume", "Resume the latest run from its checkpoint", _cmd_resume, category="general"),
        Command("plans", "Show the current todo.md plan", _cmd_plans, category="general"),
        Command("rewind", "List checkpoints and preview a rewind (no changes)", _cmd_rewind, category="general"),
        Command("hooks", "List configured plugin hooks", _cmd_hooks, category="info"),
        Command("mcp", "List MCP servers and status", _cmd_mcp, category="info"),
        Command("login", "Login to an OAuth provider (auth CLI bridge)", _cmd_login, category="settings"),
        Command("cost", "Estimate cost of the latest run", _cmd_cost, category="info"),
    ]
    for cmd in builtins:
        reg.register(cmd)

    return reg


# ── Auto-init on import ────────────────────────────────────────────────────
_registry = CommandRegistry()
init_registry(_registry)


def get_registry() -> CommandRegistry:
    return _registry


# ── Task Tracker (moved from legacy shell/) ─────────────────────────────

class TaskTracker:
    """Simple in-memory task registry for /verify, /test, etc."""
    _tasks: list[dict[str, Any]] = []

    @classmethod
    def create(cls, prompt: str) -> str:
        import uuid
        task_id = str(uuid.uuid4())
        cls._tasks.append({"id": task_id, "prompt": prompt, "status": "running"})
        return task_id

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return list(cls._tasks)
