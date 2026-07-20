"""Central command registry — single source of truth for ALL commands.

TUI, GUI, and all gateways import the same registry. Every command is
registered here with a category, description, and async handler.
"""

from __future__ import annotations

import asyncio
import logging
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
    from shell import TaskTracker
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
    from shell import TaskTracker
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
    if ctx.shell:
        ctx.shell._show_agents()
    return CommandResult()


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
    ]
    for cmd in builtins:
        reg.register(cmd)

    return reg


# ── Auto-init on import ────────────────────────────────────────────────────
_registry = CommandRegistry()
init_registry(_registry)


def get_registry() -> CommandRegistry:
    return _registry
