"""Central command registry — single source of truth for ALL commands.

TUI, GUI, and all gateways import the same registry. Every command is
registered here with a category, description, and async handler.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)
from nexus.runtime import build_resume_prompt


def _resume_claim(path: str, session_id: str):
    """Atomically claim one checkpoint for live resume execution."""
    claim_path = f"{path}.resume.claim.json"
    now = time.time()
    try:
        if os.path.exists(claim_path):
            with open(claim_path, "r", encoding="utf-8") as handle:
                prior = json.load(handle)
            if str(prior.get("session_id") or "") != str(session_id):
                return False, "checkpoint belongs to another session", claim_path, ""
            if str(prior.get("status") or "") == "success":
                return False, "checkpoint was already resumed successfully", claim_path, ""
            if str(prior.get("status") or "") == "running" and now - float(prior.get("claimed_at") or now) < 3600:
                return False, "checkpoint resume is already in progress", claim_path, ""
            # A crashed resumptor may leave a stale running claim. Remove it
            # before the exclusive create below; a competing process can still
            # win the race and will receive FileExistsError safely.
            try:
                os.unlink(claim_path)
            except OSError:
                pass
        claim = {"session_id": str(session_id), "status": "running", "claimed_at": now,
                 "resume_id": f"resume_{uuid.uuid4().hex}"}
        fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(claim, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(claim_path)
            except OSError:
                pass
            raise
        return True, "", claim_path, claim["resume_id"]
    except FileExistsError:
        # A competing process won the exclusive create. Re-read on the next
        # command invocation rather than risking duplicate side effects.
        return False, "checkpoint resume is already in progress", claim_path, ""
    except Exception as exc:
        return False, f"could not claim checkpoint: {exc}", claim_path, ""


def _finish_resume_claim(claim_path: str, status: str, error: str = "") -> None:
    try:
        with open(claim_path, "r", encoding="utf-8") as handle:
            claim = json.load(handle)
        claim["status"] = str(status)
        claim["updated_at"] = time.time()
        if error:
            claim["error"] = str(error)[:1000]
        temporary = f"{claim_path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(claim, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, claim_path)
    except Exception:
        logger.debug("could not finalize resume claim", exc_info=True)


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
        execution: str = "shared",
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.category = category
        self.args = args or {}
        self.aliases = aliases or []
        # ``shared`` commands execute through the Python handler on every
        # client. ``client`` commands are still part of the canonical catalog,
        # but their interactive behavior belongs to the surface (Ink/browser)
        # because it needs local UI state such as the clipboard or terminal.
        self.execution = execution

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


async def _cmd_stop(ctx: CommandContext) -> CommandResult:
    """Client-owned stream cancellation; interactive clients perform the abort."""
    return CommandResult(
        output="No interactive stream is attached to this command request.",
        data={"client_action": "stop"},
    )


async def _cmd_retry(ctx: CommandContext) -> CommandResult:
    """Client-owned retry; the client preserves the exact original prompt."""
    return CommandResult(
        output="Retry: resends the last user prompt\nRequires: active session with conversation history",
        formatted="[yellow]Retry:[/yellow] resends the last user prompt",
        data={"client_action": "retry"},
    )


async def _cmd_new(ctx: CommandContext) -> CommandResult:
    import time
    if not ctx.shell:
        callback = ctx.extra.get("new_session")
        if callable(callback):
            result = callback()
            if inspect.isawaitable(result):
                result = await result
            session_id = str((result or {}).get("id") or "") if isinstance(result, dict) else str(result or "")
            if session_id:
                return CommandResult(output=f"New session: {session_id}", data={"session_id": session_id})
        return CommandResult(output="New session requires a session-capable client", success=False)
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
        return CommandResult(output="Sessions listed in the active shell.")
    callback = ctx.extra.get("list_sessions")
    if callable(callback):
        result = callback()
        if inspect.isawaitable(result):
            result = await result
        rows = result if isinstance(result, list) else (result or {}).get("sessions", [])
        lines = [f"{item.get('id')}: {item.get('title') or 'New Chat'}" for item in rows if isinstance(item, dict)]
        return CommandResult(output="\n".join(lines) if lines else "No sessions found.", data={"sessions": rows})
    return CommandResult(output="No session listing provider is attached.", success=False)


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
    if len(parts) > 1:
        callback = ctx.extra.get("load_session")
        if callable(callback):
            result = callback(parts[1])
            if inspect.isawaitable(result):
                result = await result
            session_id = str((result or {}).get("id") or parts[1]) if isinstance(result, dict) else str(result or parts[1])
            return CommandResult(output=f"Switched to session: {session_id}", data={"session_id": session_id})
    return CommandResult(output="Usage: /session <id>", success=False)


async def _cmd_history(ctx: CommandContext) -> CommandResult:
    callback = ctx.extra.get("load_history")
    if callable(callback):
        result = callback(ctx.session_id)
        if inspect.isawaitable(result):
            result = await result
        messages = result if isinstance(result, list) else (result or {}).get("history", [])
    else:
        messages = _load_session_messages(ctx)
    if not messages:
        return CommandResult(output=f"No history for session: {ctx.session_id}", data={"session_id": ctx.session_id, "messages": []})
    lines = [f"{item.get('role', 'unknown')}: {str(item.get('content', '')).strip()}" for item in messages if isinstance(item, dict)]
    return CommandResult(output="\n".join(lines), data={"session_id": ctx.session_id, "messages": messages})


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
    """Launch the NEXUS GUI or show GUI status."""
    if not ctx.shell:
        # Show GUI status instead of failing
        root = _nexus_root(ctx)
        web_dir = os.path.join(root, "apps", "web")
        has_web = os.path.isdir(web_dir)
        return CommandResult(
            output=f"GUI: {'available' if has_web else 'not installed'}\nWeb app: {web_dir if has_web else 'not found'}",
            formatted=f"[bold]GUI[/bold] {'[green]available[/green]' if has_web else '[dim]not installed[/dim]'}",
        )
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


async def _cmd_test(ctx: CommandContext) -> CommandResult:
    return await _cmd_agent_task(ctx, "test",
        "Run the relevant project tests and report actionable failures with exact evidence.")


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

async def _persist_runtime(ctx: CommandContext) -> None:
    callback = ctx.extra.get("persist_runtime")
    if not callable(callback):
        return
    result = callback()
    if inspect.isawaitable(result):
        await result


async def _apply_runtime(ctx: CommandContext) -> None:
    callback = ctx.extra.get("apply_runtime")
    if not callable(callback):
        return
    result = callback()
    if inspect.isawaitable(result):
        await result


async def _sync_runtime(ctx: CommandContext, setting: str, value: str) -> None:
    callback = ctx.extra.get(f"sync_{setting}")
    if not callable(callback):
        return
    result = callback(value)
    if inspect.isawaitable(result):
        await result


def _runtime(ctx: CommandContext) -> Optional[Dict[str, Any]]:
    value = ctx.extra.get("runtime_settings")
    return value if isinstance(value, dict) else None


def _normalize_mode(value: str) -> str:
    aliases = {"": "auto", "default": "ask", "approve": "ask", "approval": "ask", "askall": "ask", "ask_all": "ask", "once": "ask", "bypass": "all", "dontask": "all", "dont_ask": "all", "noask": "all", "allow": "allowlist", "allowed": "allowlist", "allow-list": "allowlist", "whitelist": "allowlist", "preauth": "allowlist", "pre_authorized": "allowlist", "checklist": "allowlist", "acceptedits": "auto", "accept": "auto", "auto_pilot": "auto", "autopilot": "auto"}
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return aliases.get(normalized, normalized)


def _normalize_sandbox(value: str) -> str:
    aliases = {"": "no_sandbox", "none": "no_sandbox", "off": "no_sandbox", "no": "no_sandbox", "no-sandbox": "no_sandbox", "nosandbox": "no_sandbox", "simple": "normal", "safe": "normal", "on": "normal", "advanced": "docker"}
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return aliases.get(normalized, normalized)


async def _cmd_mode(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    if isinstance(parts, str):
        parts = parts.split()
    if len(parts) > 1:
        new_mode = parts[1].strip().lower()
        resolved = _normalize_mode(new_mode)
        if resolved not in {"auto", "all", "allowlist", "ask", "plan"}:
            return CommandResult(output=f"Invalid mode: {new_mode}. Use auto, ask, allowlist, all, or plan.", success=False)
        if ctx.shell:
            ctx.shell.mode = resolved
        runtime = _runtime(ctx)
        if runtime is not None:
            runtime["mode"] = resolved
            await _apply_runtime(ctx)
            await _persist_runtime(ctx)
            await _sync_runtime(ctx, "permission_mode", resolved)
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
        model_parts = raw.split()
        is_set_syntax = len(model_parts) >= 3 and model_parts[0].lower() in {"set", "use"}
        if is_set_syntax:
            provider = model_parts[1].strip().lower()
            model = " ".join(model_parts[2:]).strip()
        elif ":" in raw:
            p, m = raw.split(":", 1)
            provider = (p or "").strip().lower()
            model = (m or "").strip()
        elif raw:
            model = raw
        if ctx.shell:
            ctx.shell.provider = provider
            ctx.shell.model = model
        runtime = _runtime(ctx)
        if runtime is not None:
            runtime["provider"] = provider
            runtime["model"] = model
            await _apply_runtime(ctx)
            await _persist_runtime(ctx)
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
    runtime = _runtime(ctx)
    if runtime is not None:
        runtime["thinking"] = new_state
        await _persist_runtime(ctx)
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
    mode = _normalize_mode(mode)
    if ctx.shell:
        ctx.shell.mode = mode
    runtime = _runtime(ctx)
    if runtime is not None:
        runtime["mode"] = mode
        await _apply_runtime(ctx)
        await _persist_runtime(ctx)
        await _sync_runtime(ctx, "permission_mode", mode)
    return CommandResult(
        output=f"Mode: {mode}",
        formatted=f"[green]Mode: {mode}[/green]",
    )


async def _cmd_config(ctx: CommandContext) -> CommandResult:
    """Show configuration from runtime context, config file, or defaults."""
    if ctx.shell:
        ctx.shell._show_config()
    runtime = _runtime(ctx)
    if runtime is not None:
        keys = ("mode", "sandbox_tier", "provider", "model", "profile", "thinking", "effort")
        return CommandResult(output=json.dumps({key: runtime.get(key) for key in keys}, indent=2, sort_keys=True))
    # Fallback: read from nexus.config.json
    root = _nexus_root(ctx)
    config_path = os.path.join(root, "nexus.config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            return CommandResult(
                output=json.dumps(cfg, indent=2, sort_keys=True),
                formatted=f"[bold]Config[/bold]\n{json.dumps(cfg, indent=2)}",
                data=cfg,
            )
        except Exception:
            pass
    # Fallback: show defaults
    defaults = {"mode": "auto", "provider": "not set", "model": "not set", "thinking": True, "effort": "medium"}
    return CommandResult(
        output=json.dumps(defaults, indent=2, sort_keys=True),
        formatted=f"[bold]Config (defaults)[/bold]\n{json.dumps(defaults, indent=2)}",
        data=defaults,
    )


async def _cmd_provider(ctx: CommandContext) -> CommandResult:
    """Comprehensive provider management: local, API, and auth providers."""
    from nexus.commands_provider import provider_command
    return await provider_command(ctx)


async def _cmd_sandbox(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    parts = parts.split() if isinstance(parts, str) else list(parts or [])
    requested = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
    runtime = _runtime(ctx)
    current = _normalize_sandbox(str((runtime or {}).get("sandbox_tier") or "no_sandbox"))
    if not requested:
        return CommandResult(output=f"Sandbox: {current}", data={"tier": current})
    tier = _normalize_sandbox(requested)
    if tier not in {"no_sandbox", "normal", "docker"}:
        return CommandResult(output=f"Invalid sandbox tier: {requested}. Use no_sandbox, normal, or docker.", success=False)
    if runtime is not None:
        runtime["sandbox_tier"] = tier
        await _apply_runtime(ctx)
        await _persist_runtime(ctx)
        await _sync_runtime(ctx, "sandbox_tier", tier)
    return CommandResult(output=f"Sandbox: {tier}", data={"tier": tier})


async def _cmd_effort(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    parts = parts.split() if isinstance(parts, str) else list(parts or [])
    requested = " ".join(parts[1:]).strip().lower() if len(parts) > 1 else ""
    runtime = _runtime(ctx)
    current = str((runtime or {}).get("effort") or "auto")
    if not requested:
        return CommandResult(output=f"Effort: {current}", data={"effort": current})
    if requested == "extra_high":
        requested = "xhigh"
    if requested not in {"auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
        return CommandResult(output=f"Invalid effort: {requested}.", success=False)
    if runtime is not None:
        runtime["effort"] = requested
        await _persist_runtime(ctx)
    return CommandResult(output=f"Effort: {requested}", data={"effort": requested})


async def _cmd_permissions(ctx: CommandContext) -> CommandResult:
    parts = ctx.extra.get("args", "")
    parts = parts.split() if isinstance(parts, str) else list(parts or [])
    runtime = _runtime(ctx)
    if runtime is None:
        return CommandResult(output=f"Permission mode: {ctx.mode}", data={"mode": ctx.mode})
    allowlist = [str(item) for item in runtime.get("permission_allowlist") or [] if str(item).strip()]
    sub = parts[1].lower() if len(parts) > 1 else ""
    if sub in {"add", "remove", "rm", "delete"}:
        entry = " ".join(parts[2:]).strip()
        if not entry:
            return CommandResult(output=f"Usage: /permissions {sub} <tool-or-command>", success=False)
        if sub == "add" and entry not in allowlist:
            allowlist.append(entry)
        elif sub in {"remove", "rm", "delete"}:
            allowlist = [item for item in allowlist if item != entry]
        runtime["permission_allowlist"] = allowlist
        await _persist_runtime(ctx)
    elif sub in {"list", "allowlist", "allowed"}:
        return CommandResult(output=f"Permission mode: {runtime.get('mode', ctx.mode)}\nAllowlist:\n" + "\n".join(f"- {item}" for item in allowlist), data={"mode": runtime.get("mode", ctx.mode), "allowlist": allowlist})
    elif sub:
        mode = _normalize_mode(sub)
        if mode not in {"auto", "all", "allowlist", "ask", "plan"}:
            return CommandResult(output=f"Invalid permission mode: {sub}", success=False)
        runtime["mode"] = mode
        await _apply_runtime(ctx)
        await _persist_runtime(ctx)
        await _sync_runtime(ctx, "permission_mode", mode)
    return CommandResult(output=f"Permission mode: {runtime.get('mode', ctx.mode)}\nAllowlist entries: {len(allowlist)}", data={"mode": runtime.get("mode", ctx.mode), "allowlist": allowlist})


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
    runtime = _runtime(ctx)
    if runtime is not None:
        info.extend([
            f"Sandbox: {runtime.get('sandbox_tier', 'normal')}",
            f"Effort: {runtime.get('effort', 'medium')}",
        ])
    output = "\n".join(info)
    formatted = "\n".join(
        f"  [dim]{k}:[/dim] [white]{v}[/white]"
        for k, v in (s.split(": ", 1) for s in info)
    )
    return CommandResult(output=output, formatted=f"[bold]System Status[/bold]\n{formatted}", data={"mode": ctx.mode, "sandbox_tier": (runtime or {}).get("sandbox_tier"), "effort": (runtime or {}).get("effort")})


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


async def _cmd_hiveteam(ctx: CommandContext) -> CommandResult:
    """List reusable Hive Agent Team templates (plug-and-play)."""
    try:
        from hive import list_team_templates
        teams = list_team_templates()
    except Exception as e:
        return CommandResult(output=f"Hive teams unavailable: {e}",
                             formatted=f"[dim]Hive teams unavailable: {e}[/dim]")
    if not teams:
        return CommandResult(output="No Agent Team templates registered",
                             formatted="[dim]No Agent Team templates registered[/dim]")
    lines = [f"  {t.name}  ({len(t.agents)} agents, workflow={t.workflow})" for t in teams]
    formatted = "\n".join(
        f"  [cyan]{t.name}[/cyan] [grey70]({len(t.agents)} agents, workflow={t.workflow})[/grey70]"
        for t in teams
    )
    return CommandResult(
        output=f"Hive Agent Teams ({len(teams)}):\n" + "\n".join(lines),
        formatted=f"[bold]Hive Agent Teams ({len(teams)})[/bold]\n{formatted}",
        data={"teams": [t.name for t in teams]},
    )


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
    """List installed skills from the skill engine."""
    try:
        from extensions.skills.engine import NexusSkillMaster
        master = NexusSkillMaster()
        skills = master.list_skills() if hasattr(master, 'list_skills') else []
        if skills:
            lines = [f"  {s.get('name', '?'):<30} {s.get('description', '')[:50]}" for s in skills]
            return CommandResult(
                output=f"Skills ({len(skills)}):\n" + "\n".join(lines),
                formatted=f"[bold]Skills ({len(skills)})[/bold]\n" + "\n".join(
                    f"  [magenta]{s.get('name', '?')}[/magenta] [dim]{s.get('description', '')[:50]}[/dim]"
                    for s in skills
                ),
                data={"skills": skills},
            )
    except Exception:
        pass
    # Fallback: scan SKILL.md files
    import glob
    skill_files = glob.glob("extensions/skills/*/SKILL.md")
    if skill_files:
        names = [os.path.basename(os.path.dirname(f)) for f in skill_files]
        lines = [f"  {n}" for n in sorted(names)]
        return CommandResult(
            output=f"Skills ({len(names)}):\n" + "\n".join(lines),
            formatted=f"[bold]Skills ({len(names)})[/bold]\n" + "\n".join(
                f"  [magenta]{n}[/magenta]" for n in sorted(names)
            ),
        )
    if ctx.shell:
        ctx.shell._show_skills()
    return CommandResult(output="No skills found", formatted="[dim]No skills installed[/dim]")


async def _cmd_tools(ctx: CommandContext) -> CommandResult:
    """List registered tools from the tool registry."""
    try:
        from extensions.tools.registry import ToolRegistry
        registry = ToolRegistry()
        tools = registry.list_tools() if hasattr(registry, 'list_tools') else []
        if tools:
            lines = [f"  {t.get('name', '?'):<30} {t.get('description', '')[:50]}" for t in tools[:50]]
            return CommandResult(
                output=f"Tools ({len(tools)}):\n" + "\n".join(lines),
                formatted=f"[bold]Tools ({len(tools)})[/bold]\n" + "\n".join(
                    f"  [green]{t.get('name', '?')}[/green] [dim]{t.get('description', '')[:50]}[/dim]"
                    for t in tools[:50]
                ),
                data={"tools": tools},
            )
    except Exception:
        pass
    # Fallback: scan built-in tool directories
    tools_dir = "extensions/tools/built_in"
    if os.path.isdir(tools_dir):
        tool_names = sorted([d for d in os.listdir(tools_dir) if os.path.isdir(os.path.join(tools_dir, d))])
        if tool_names:
            lines = [f"  {n}" for n in tool_names]
            return CommandResult(
                output=f"Tools ({len(tool_names)}):\n" + "\n".join(lines),
                formatted=f"[bold]Tools ({len(tool_names)})[/bold]\n" + "\n".join(
                    f"  [green]{n}[/green]" for n in tool_names
                ),
            )
    if ctx.shell:
        ctx.shell._show_tools()
    return CommandResult(output="No tools found", formatted="[dim]No tools registered[/dim]")


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
    """Show memory and session info from filesystem or shell context."""
    if ctx.shell:
        h = len(ctx.shell.conversation_history)
        s = ctx.shell.session_id
        return CommandResult(
            output=f"History: {h} messages, Session: {s}",
            formatted=f"[cyan]History: {h} messages[/cyan]\n[cyan]Session: {s}[/cyan]",
        )
    # Fallback: scan session files
    root = _nexus_root(ctx)
    sessions_dir = os.path.join(root, ".nexus", "sessions")
    total_size = 0
    count = 0
    if os.path.isdir(sessions_dir):
        for d in os.listdir(sessions_dir):
            dp = os.path.join(sessions_dir, d)
            if os.path.isdir(dp):
                count += 1
                for f in os.listdir(dp):
                    fp = os.path.join(dp, f)
                    if os.path.isfile(fp):
                        total_size += os.path.getsize(fp)
    memory_path = os.path.join(root, ".nexus", "memory.json")
    memories = 0
    if os.path.exists(memory_path):
        try:
            with open(memory_path) as f:
                memories = len(json.load(f))
        except Exception:
            pass
    return CommandResult(
        output=f"Session: {ctx.session_id}\nSessions: {count} ({total_size // 1024}KB)\nMemories: {memories}",
        formatted=f"[bold]Memory[/bold]\n  Session: {ctx.session_id}\n  Sessions: {count} ({total_size // 1024}KB)\n  Memories: {memories}",
        data={"session": ctx.session_id, "sessions": count, "memories": memories},
    )


async def _cmd_events(ctx: CommandContext) -> CommandResult:
    """Show work events from filesystem or shell context."""
    if ctx.shell:
        ctx.shell._show_work_events()
    # Fallback: scan event files
    root = _nexus_root(ctx)
    events_dir = os.path.join(root, ".nexus", "events")
    if os.path.isdir(events_dir):
        files = sorted([f for f in os.listdir(events_dir) if f.endswith(".json")])[-5:]
        if files:
            lines = [f"  {f}" for f in files]
            return CommandResult(
                output=f"Events ({len(files)} recent):\n" + "\n".join(lines),
                formatted=f"[bold]Events[/bold]\n" + "\n".join(f"  [cyan]{f}[/cyan]" for f in files),
            )
    return CommandResult(output="No events recorded", formatted="[dim]No events recorded[/dim]")


async def _cmd_system(ctx: CommandContext) -> CommandResult:
    """Show comprehensive system overview."""
    if ctx.shell:
        ctx.shell._show_system_map()
    # Fallback: real system overview
    import platform
    root = _nexus_root(ctx)
    subsystems = []
    for name, path in [("Core", "src/nexus"), ("Tools", "extensions/tools"),
                        ("Skills", "extensions/skills"), ("Plugins", "extensions/plugins"),
                        ("Hive", "hive"), ("Gateways", "gateways"),
                        ("Models", "models"), ("Memory", "memory"),
                        ("Queues", "queues"), ("Security", "security")]:
        full = os.path.join(root, path)
        status = "ok" if os.path.isdir(full) else "missing"
        subsystems.append(f"  {name:<15} {status}")
    return CommandResult(
        output=f"System:\n  Python: {sys.version.split()[0]}\n  Platform: {platform.platform()}\n  Root: {root}\n" + "\n".join(subsystems),
        formatted=f"[bold]System[/bold]\n  [dim]Python:[/dim] {sys.version.split()[0]}\n  [dim]Platform:[/dim] {platform.platform()}\n" + "\n".join(subsystems),
    )


async def _cmd_plugins(ctx: CommandContext) -> CommandResult:
    """Show plugin registry."""
    try:
        from extensions.plugins.registry import PluginRegistry
        registry = PluginRegistry()
        plugins = registry.list_plugins() if hasattr(registry, 'list_plugins') else []
        if plugins:
            lines = [f"  {p.get('name', '?'):<30} {p.get('status', 'active'):<10} {p.get('description', '')[:40]}" for p in plugins]
            return CommandResult(
                output=f"Plugins ({len(plugins)}):\n" + "\n".join(lines),
                formatted=f"[bold]Plugins ({len(plugins)})[/bold]\n" + "\n".join(
                    f"  [blue]{p.get('name', '?')}[/blue] [dim]{p.get('status', 'active')}[/dim] [grey70]{p.get('description', '')[:40]}[/grey70]"
                    for p in plugins
                ),
                data={"plugins": plugins},
            )
    except Exception:
        pass
    # Fallback: scan plugin directories
    plugins_dir = "extensions/plugins"
    if os.path.isdir(plugins_dir):
        plugin_names = sorted([d for d in os.listdir(plugins_dir) if os.path.isdir(os.path.join(plugins_dir, d)) and not d.startswith('_')])
        if plugin_names:
            lines = [f"  {n}" for n in plugin_names]
            return CommandResult(
                output=f"Plugins ({len(plugin_names)}):\n" + "\n".join(lines),
                formatted=f"[bold]Plugins ({len(plugin_names)})[/bold]\n" + "\n".join(
                    f"  [blue]{n}[/blue]" for n in plugin_names
                ),
            )
    if ctx.shell:
        ctx.shell._show_plugins()
    return CommandResult(output="No plugins found", formatted="[dim]No plugins installed[/dim]")


async def _cmd_forge(ctx: CommandContext) -> CommandResult:
    """Show forge/evolution subsystem status with real data."""
    root = _nexus_root(ctx)
    forge_dir = os.path.join(root, "evolution")
    items = []
    if os.path.isdir(forge_dir):
        for fn in sorted(os.listdir(forge_dir)):
            fp = os.path.join(forge_dir, fn)
            if os.path.isfile(fp):
                size = os.path.getsize(fp)
                items.append(f"  {fn:<40} {size:>8} bytes")
            elif os.path.isdir(fp):
                count = len([f for f in os.listdir(fp) if os.path.isfile(os.path.join(fp, f))])
                items.append(f"  {fn}/{' ':<38} {count:>6} files")
    if not items:
        items = ["  [dim]No evolution/forge content found[/dim]"]
    return CommandResult(
        output="Forge Status:\n" + "\n".join(items),
        formatted="[bold]Forge / Evolution[/bold]\n" + "\n".join(items),
    )


async def _cmd_providers(ctx: CommandContext) -> CommandResult:
    """List all providers by category (local/api/auth)."""
    from nexus.commands_provider import _list_all
    return _list_all()


async def _cmd_models(ctx: CommandContext) -> CommandResult:
    """List and manage models per provider."""
    from nexus.commands_models import models_command
    return await models_command(ctx)


async def _cmd_monitor(ctx: CommandContext) -> CommandResult:
    """Show agent monitor dashboard with real stats."""
    stats = {}
    try:
        from nexus.health import HealthMonitor
        monitor = HealthMonitor(_nexus_root(ctx))
        if hasattr(monitor, 'get_stats'):
            stats = monitor.get_stats()
    except Exception:
        pass
    lines = []
    if stats:
        for k, v in stats.items():
            lines.append(f"  {k:<25} {v}")
    else:
        # Fallback: show basic info
        import time
        lines = [
            f"  uptime:            {time.time():.0f}",
            f"  pid:               {os.getpid()}",
            f"  cwd:               {os.getcwd()}",
            f"  platform:          {os.name}",
        ]
    return CommandResult(
        output="Agent Monitor:\n" + "\n".join(lines),
        formatted="[bold]Agent Monitor[/bold]\n" + "\n".join(
            f"  [cyan]{k:<25}[/cyan] {v}" for k, v in (stats or {
                'uptime': f'{time.time():.0f}',
                'pid': os.getpid(),
                'cwd': os.getcwd(),
                'platform': os.name,
            }.items())
        ),
    )


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
    return os.path.join(_nexus_root(ctx), ".nexus", "logs", "sessions")


def _latest_session_file(ctx: CommandContext) -> str:
    """Path of the most recently written session JSON in .nexus/logs/sessions; '' on failure."""
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
        from nexus.main_agent.context_manager import ContextManager
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
    """Report session context usage from the latest .nexus/logs/sessions file."""
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
        formatted="[bold]Context Usage[/bold]\n" + "\n".join(formatted_lines),
        data={"messages": len(messages), "est_tokens": est_tokens, "window": window, "percent": round(pct, 1)},
    )


async def _cmd_client_catalog_entry(ctx: CommandContext) -> CommandResult:
    """Describe a cataloged interactive command without faking execution.

    A number of commands (clipboard, terminal renderer, local working
    directory, browser launch, and client-side cancellation) cannot be
    performed by the stateless HTTP command endpoint. They still belong in the
    same registry so every surface discovers the same command set. The TUI
    handles these in its client dispatcher; other clients receive an honest
    capability response.
    """
    name = str(ctx.extra.get("command") or "").strip().lstrip("/")
    return CommandResult(
        output=f"/{name} is registered as an interactive client command. Run it from the active NEXUS client.",
        data={"client_action": "interactive", "command": f"/{name}"},
    )


async def _cmd_resume(ctx: CommandContext) -> CommandResult:
    """Continue the newest unfinished checkpoint through the live V5 loop."""
    try:
        from nexus.main_agent.checkpoint import V5Checkpoint
        cp = V5Checkpoint()
        cp.root_dir = _nexus_root(ctx)
        entries = cp._checkpoint_list(limit=0)
        if not entries:
            return CommandResult(output="no data yet", formatted="[dim]No checkpoints yet[/dim]")
        data = {}
        path = ""
        session_id = str(getattr(ctx, "session_id", "default") or "default")
        terminal = {"complete", "completed", "done", "success", "succeeded", "finished"}
        # A completed checkpoint for a turn makes all earlier phase snapshots
        # of that same turn stale.  Without this fence a later /resume could
        # replay tool work that already finished successfully.
        terminal_turns = set()
        decoded = []
        for entry in entries:
            candidate = cp._checkpoint_read(str(entry.get("file") or ""))
            decoded.append((entry, candidate))
            candidate_session = str(candidate.get("session") or "")
            if candidate_session and candidate_session != session_id:
                continue
            if str(candidate.get("phase") or entry.get("phase") or "").lower() in terminal:
                turn = str(candidate.get("turn_id") or entry.get("turn_id") or "")
                if turn:
                    terminal_turns.add(turn)
        for entry, candidate in decoded:
            candidate_session = str(candidate.get("session") or "")
            turn = str(candidate.get("turn_id") or entry.get("turn_id") or "")
            if candidate_session and candidate_session != session_id:
                continue
            if turn in terminal_turns:
                continue
            if str(candidate.get("phase") or entry.get("phase") or "").lower() not in terminal:
                data, path = candidate, str(entry.get("file") or "")
                break
        if not data:
            return CommandResult(output="no unfinished checkpoint", formatted="[dim]No unfinished checkpoint[/dim]")
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
        loop = getattr(ctx, "loop", None)
        stream_run = getattr(loop, "stream_run", None)
        if callable(stream_run):
            claimed, claim_error, claim_path, resume_id = _resume_claim(path, session_id)
            if not claimed:
                return CommandResult(
                    success=False,
                    output=claim_error or "checkpoint resume unavailable",
                    error=claim_error or "checkpoint resume unavailable",
                    data={**data, "resumed": False},
                )
            evidence = data.get("context_summary") or data.get("plan") or data.get("actions") or data.get("recent_messages") or ""
            prompt = build_resume_prompt("Continue the unfinished task from the saved checkpoint.", evidence)
            response = ""
            done: Dict[str, Any] = {}
            resume_messages = data.get("recent_messages")
            resume_kwargs: Dict[str, Any] = {
                "provider": ctx.provider,
                "model": ctx.model,
                "turn_id": resume_id,
            }
            if isinstance(resume_messages, list) and resume_messages:
                resume_kwargs["conversation_history"] = resume_messages[-12:]
            async for event in stream_run(prompt, **resume_kwargs):
                if not isinstance(event, dict):
                    continue
                payload = event.get("data") if isinstance(event.get("data"), dict) else event
                for key in ("response", "content", "text", "summary"):
                    if isinstance(payload.get(key), str) and payload[key].strip():
                        response = payload[key]
                if event.get("type") == "done" and isinstance(event.get("data"), dict):
                    done = event["data"]
            # A stream without an explicit terminal event is incomplete, not
            # successful. This prevents a provider/network interruption from
            # being reported as a completed resume.
            success = bool(done) and bool(done.get("success"))
            if not success:
                _finish_resume_claim(claim_path, "failed", done.get("error") or "resume failed")
                return CommandResult(success=False, output=done.get("error") or "resume failed",
                                     error=done.get("error") or "resume failed", data={**data, "resumed": False})
            _finish_resume_claim(claim_path, "success")
            return CommandResult(output=response or "Resumed task completed", formatted=response or "[green]Resumed task completed[/green]",
                                 data={**data, "resumed": True, "resume_id": resume_id})
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
        from extensions.tools.built_in.planning.scripts.planning import PlanningTool
    except Exception:
        return CommandResult(output="no data yet", formatted="[dim]Planning tool unavailable[/dim]")
    root = _nexus_root(ctx)
    for base in (os.path.join(root, ".nexus", "workspace"), root):
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
        from nexus.main_agent.checkpoint import V5Checkpoint
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
        from extensions.plugins.built_in.manager import HookRegistry
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
        formatted="[bold]Plugin Hooks[/bold]\n" + "\n".join(
            f"  [cyan]{event:<20}[/cyan] [white]{len(hook_reg.get_hooks(event))!s:>6}[/white] handler(s)"
            for event in HookRegistry.PLUGIN_EVENTS
        ),
        data={event: len(hook_reg.get_hooks(event)) for event in HookRegistry.PLUGIN_EVENTS},
    )


async def _cmd_mcp(ctx: CommandContext) -> CommandResult:
    """List MCP servers from config/mcp_servers.json with running status (real loader shape)."""
    root = _nexus_root(ctx)
    cfg_path = ctx.extra.get("mcp_config") or os.path.join(root, "configure", "mcp_servers.json")
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
        from nexus.command_system.auth import handle_auth_login
        await handle_auth_login(SimpleNamespace(provider=provider, name="default", port=None, host="127.0.0.1"))
    except Exception as e:
        return CommandResult(output=f"login failed: {e}", success=False)
    return CommandResult(
        output=f"login: {provider} initiated",
        formatted=f"[green]Login to '{provider}' initiated[/green]\nFollow the OAuth prompts in the shell.",
    )


async def _cmd_cost(ctx: CommandContext) -> CommandResult:
    """Estimate cost for the latest run at $0.001/1K tokens from .nexus/logs/sessions."""
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


# ── Missing Critical Commands (from Claude Code / Codex / Cursor) ──────────────

async def _cmd_undo(ctx: CommandContext) -> CommandResult:
    """Revert the last workspace file changes using workspace snapshots."""
    try:
        from nexus.main_agent.workspace_snapshot import WorkspaceSnapshot
        ws = WorkspaceSnapshot(_nexus_root(ctx))
        success = ws.undo_last()
        if success:
            return CommandResult(
                output="Undo successful — last snapshot reverted",
                formatted="[green]Undo successful[/green] — last workspace snapshot reverted",
            )
        return CommandResult(
            output="Nothing to undo",
            formatted="[dim]Nothing to undo — no snapshots available[/dim]",
        )
    except Exception as exc:
        return CommandResult(output=f"Undo failed: {exc}", success=False)


async def _cmd_remember(ctx: CommandContext) -> CommandResult:
    """Save a persistent note/memory that survives across sessions."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /remember <note text>",
            formatted="[yellow]Usage:[/yellow] /remember <note text>",
        )
    # Store in .nexus/memory.json
    import json
    mem_path = os.path.join(_nexus_root(ctx), ".nexus", "memory.json")
    memories = []
    if os.path.exists(mem_path):
        try:
            with open(mem_path, "r") as f:
                memories = json.load(f)
        except Exception:
            memories = []
    import datetime
    memories.append({
        "text": args,
        "session_id": ctx.session_id,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    os.makedirs(os.path.dirname(mem_path), exist_ok=True)
    with open(mem_path, "w") as f:
        json.dump(memories, f, indent=2)
    return CommandResult(
        output=f"Remembered: {args}",
        formatted=f"[green]Remembered:[/green] {args}",
    )


async def _cmd_forget(ctx: CommandContext) -> CommandResult:
    """List memories or forget the last one."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    mem_path = os.path.join(_nexus_root(ctx), ".nexus", "memory.json")
    if not os.path.exists(mem_path):
        return CommandResult(output="No memories saved", formatted="[dim]No memories saved yet[/dim]")
    try:
        import json
        with open(mem_path, "r") as f:
            memories = json.load(f)
    except Exception:
        return CommandResult(output="No memories saved", formatted="[dim]No memories saved yet[/dim]")
    if not memories:
        return CommandResult(output="No memories saved", formatted="[dim]No memories saved yet[/dim]")
    if args in ("last", "undo", "pop"):
        removed = memories.pop()
        with open(mem_path, "w") as f:
            json.dump(memories, f, indent=2)
        return CommandResult(
            output=f"Forgot: {removed.get('text', '?')}",
            formatted=f"[yellow]Forgot:[/yellow] {removed.get('text', '?')}",
        )
    # List all memories
    lines = [f"  {i+1}. [{m.get('timestamp', '?')[:10]}] {m.get('text', '?')}" for i, m in enumerate(memories[-20:])]
    return CommandResult(
        output=f"Memories ({len(memories)}):\n" + "\n".join(lines),
        formatted=f"[bold]Memories ({len(memories)})[/bold]\n" + "\n".join(
            f"  [cyan]{i+1}.[/cyan] [dim]{m.get('timestamp', '?')[:10]}[/dim] {m.get('text', '?')}"
            for i, m in enumerate(memories[-20:])
        ),
    )


async def _cmd_search(ctx: CommandContext) -> CommandResult:
    """Search across files, commands, skills, or memory."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        return CommandResult(
            output="Usage: /search <query>",
            formatted="[yellow]Usage:[/yellow] /search <query>",
        )
    # Search files using code_search tool
    try:
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "-l", args, "--include=*.py", "--include=*.md", "--include=*.json", "."],
            capture_output=True, text=True, timeout=10, cwd=_nexus_root(ctx)
        )
        files = [f for f in result.stdout.strip().split("\n") if f and not f.startswith("./.venv") and not f.startswith("./.git")]
        if files:
            lines = [f"  {f}" for f in files[:20]]
            return CommandResult(
                output=f"Found '{args}' in {len(files)} files:\n" + "\n".join(lines),
                formatted=f"[bold]Found '{args}' in {len(files)} files[/bold]\n" + "\n".join(
                    f"  [green]{f}[/green]" for f in files[:20]
                ),
                data={"files": files, "query": args},
            )
    except Exception:
        pass
    return CommandResult(
        output=f"No results for '{args}'",
        formatted=f"[dim]No results for '{args}'[/dim]",
    )


async def _cmd_explain(ctx: CommandContext) -> CommandResult:
    """Explain the codebase structure or a specific file/module."""
    args = ctx.extra.get("args", "")
    if isinstance(args, str):
        args = args.strip()
    if not args:
        # Explain overall structure
        dirs = [d for d in os.listdir(_nexus_root(ctx)) if os.path.isdir(os.path.join(_nexus_root(ctx), d)) and not d.startswith(".")]
        lines = [f"  {d}/" for d in sorted(dirs)]
        return CommandResult(
            output=f"Nexus AI Structure:\n" + "\n".join(lines),
            formatted=f"[bold]Nexus AI Structure[/bold]\n" + "\n".join(
                f"  [cyan]{d}/[/cyan]" for d in sorted(dirs)
            ),
        )
    # Explain a specific path
    target = os.path.join(_nexus_root(ctx), args)
    if os.path.isfile(target):
        try:
            with open(target, "r") as f:
                content = f.read(2000)
            return CommandResult(
                output=f"{args}:\n{content}",
                formatted=f"[bold]{args}[/bold]\n[dim]{content}[/dim]",
            )
        except Exception:
            return CommandResult(output=f"Cannot read {args}", success=False)
    return CommandResult(output=f"Path not found: {args}", success=False)


async def _cmd_undo_status(ctx: CommandContext) -> CommandResult:
    """Show available workspace snapshots for undo."""
    try:
        from nexus.main_agent.workspace_snapshot import WorkspaceSnapshot
        ws = WorkspaceSnapshot(_nexus_root(ctx))
        snapshots = ws.list_snapshots() if hasattr(ws, 'list_snapshots') else []
        if snapshots:
            lines = [f"  {s.get('timestamp', '?')} — {s.get('description', '?')}" for s in snapshots[-10:]]
            return CommandResult(
                output=f"Snapshots ({len(snapshots)}):\n" + "\n".join(lines),
                formatted=f"[bold]Snapshots ({len(snapshots)})[/bold]\n" + "\n".join(
                    f"  [cyan]{s.get('timestamp', '?')}[/cyan] — {s.get('description', '?')}"
                    for s in snapshots[-10:]
                ),
            )
    except Exception:
        pass
    return CommandResult(output="No snapshots available", formatted="[dim]No workspace snapshots available[/dim]")


# ── Initialize Built-in Commands ────────────────────────────────────────────

def init_registry(registry: Optional[CommandRegistry] = None) -> CommandRegistry:
    """Register all built-in commands. Call once at startup."""
    reg = registry or CommandRegistry()

    builtins = [
        # general
        Command("help", "Show all commands", _cmd_help, category="general", aliases=["h", "commands"]),
        Command("clear", "Clear screen", _cmd_clear, category="general"),
        Command("exit", "Exit NEXUS", _cmd_exit, category="general", aliases=["quit"]),
        Command("stop", "Stop the active interactive run", _cmd_stop, category="general", aliases=["cancel"]),
        Command("retry", "Retry the last user prompt verbatim", _cmd_retry, category="general"),
        Command("new", "Create a new session", _cmd_new, category="general"),
        Command("sessions", "List all sessions", _cmd_sessions, category="general"),
        Command("session", "Switch to a session by ID", _cmd_session, category="general"),
        Command("history", "Show the active session history", _cmd_history, category="general", aliases=["hist"]),
        Command("run", "Execute a shell command", _cmd_run, category="general"),
        Command("gui", "Launch the NEXUS GUI", _cmd_gui, category="general"),
        Command("review", "Run an automated code review", _cmd_review, category="general"),
        Command("simplify", "Simplify the current project changes", _cmd_simplify, category="general"),
        Command("verify", "Verify project changes with tests", _cmd_verify, category="general"),
        Command("test", "Run relevant project tests", _cmd_test, category="general", aliases=["tests"]),

        # settings
        Command("mode", "Get or set mode (auto/plan/acceptEdits/dontAsk)", _cmd_mode, category="settings"),
        Command("model", "Get or set provider:model", _cmd_model, category="settings"),
        Command("provider", "Get or set the active provider", _cmd_provider, category="settings", aliases=["connect"]),
        Command("permissions", "Get or set permission mode and allowlist", _cmd_permissions, category="settings", aliases=["perm", "perms"]),
        Command("sandbox", "Get or set the sandbox tier", _cmd_sandbox, category="settings", aliases=["sb"]),
        Command("effort", "Get or set reasoning effort", _cmd_effort, category="settings"),
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
        Command("hiveteam", "List reusable Hive Agent Team templates", _cmd_hiveteam, category="info"),
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
        Command("models", "List and manage models per provider", _cmd_models, category="info"),
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

        # workspace & memory
        Command("undo", "Revert last workspace snapshot", _cmd_undo, category="general", aliases=["revert"]),
        Command("undo-status", "Show available snapshots for undo", _cmd_undo_status, category="info"),
        Command("remember", "Save a persistent note across sessions", _cmd_remember, category="general", aliases=["note", "memo"]),
        Command("forget", "List or remove saved memories", _cmd_forget, category="general"),
        Command("search", "Search files, code, or content", _cmd_search, category="general", aliases=["find", "grep"]),
        Command("explain", "Explain codebase structure or a file", _cmd_explain, category="info"),
    ]
    for cmd in builtins:
        reg.register(cmd)

    # One catalog for every client. These commands historically lived only in
    # the Ink dispatcher (and a smaller browser list), so they are marked as
    # client commands while remaining discoverable through the same registry.
    interactive_commands = [
        ("usage", "Show usage and context telemetry", "info"),
        ("conversations", "List saved conversations", "general"),
        ("load", "Load a saved conversation", "general"),
        ("rename", "Rename the active conversation", "general"),
        ("delete-session", "Delete a saved conversation", "general"),
        ("history", "Load the active conversation history", "general"),
        ("recap", "Show a recap of the current work", "info"),
        ("insights", "Show work insights", "info"),
        ("team-onboarding", "Show team onboarding guidance", "general"),
        ("btw", "Record a side question", "general"),
        ("sources", "Toggle activity source labels", "settings"),
        ("copy", "Copy the latest response or conversation", "general"),
        ("export", "Export the active conversation", "general"),
        ("paste", "Attach an image from the clipboard", "general"),
        ("pwd", "Print the active workspace directory", "workspace"),
        ("where", "Show workspace and runtime locations", "workspace"),
        ("files", "List workspace files", "workspace"),
        ("ls", "List a workspace directory", "workspace"),
        ("tree", "Show a workspace directory tree", "workspace"),
        ("cat", "Preview a workspace file", "workspace"),
        ("cd", "Change the local TUI working directory", "workspace"),
        ("add-dir", "Add a workspace directory", "workspace"),
        ("readme", "Preview the project README", "workspace"),
        ("init", "Initialize workspace guidance", "workspace"),
        ("docs", "Open or list project documentation", "workspace"),
        ("health", "Show backend and subsystem health", "info"),
        ("queue", "Show durable queue state and unfinished work", "info"),
        ("features", "List enabled runtime features", "info"),
        ("env", "Show safe runtime environment information", "info"),
        ("logs", "Show recent runtime log entries", "info"),
        ("work", "Show recent work events", "info"),
        ("debug", "Show safe runtime debugging details", "info"),
        ("doctor", "Run local NEXUS health checks", "info"),
        ("heapdump", "Write a local memory snapshot", "developer"),
        ("check", "Run a focused type, Python, or GUI check", "developer"),
        ("build", "Build the TUI and GUI clients", "developer"),
        ("settings", "Open or inspect client settings", "settings"),
        ("permissions", "View or change command permission policy", "settings"),
        ("sandbox", "View or change the sandbox tier", "settings"),
        ("provider", "View or change the active provider", "settings"),
        ("effort", "View or change reasoning effort", "settings"),
        ("fast", "Toggle fast mode", "settings"),
        ("logout", "Clear local provider overrides", "settings"),
        ("reset", "Reset a client feature or setting", "settings"),
        ("enable", "Enable a NEXUS feature", "settings"),
        ("disable", "Disable a NEXUS feature", "settings"),
        ("reload", "Reload a NEXUS subsystem", "settings"),
        ("terminal-setup", "Show terminal setup guidance", "settings"),
        ("theme", "Show or change TUI theme", "settings"),
        ("color", "Show or change output colors", "settings"),
        ("statusline", "Configure the TUI status line", "settings"),
        ("output-style", "Configure output style", "settings"),
        ("tui", "Show TUI renderer information", "settings"),
        ("keybindings", "Show keyboard bindings", "settings"),
        ("voice", "Start, stop, or inspect voice mode", "integrations"),
        ("api", "Start or inspect the local API", "integrations"),
        ("open-gui", "Open the NEXUS GUI", "integrations"),
        ("ide", "Open the workspace in an IDE", "integrations"),
        ("evolution", "Show or manage evolution", "integrations"),
        ("scheduler", "Show or manage scheduled jobs", "integrations"),
        ("schedule", "Show or manage scheduled jobs", "integrations"),
        ("loop", "Show or manage scheduled loops", "integrations"),
        ("reminders", "Show or manage reminders", "integrations"),
        ("goal", "Show or set the active goal", "general"),
        ("todo", "Add or complete a todo item", "general"),
        ("batch", "Start a multi-agent batch task", "orchestration"),
        ("fork", "Start a forked multi-agent task", "orchestration"),
        ("multi-agent", "Start a multi-agent task", "orchestration"),
        ("multi_agent", "Start a multi-agent task", "orchestration"),
        ("security-review", "Run a security-focused review", "orchestration"),
        ("code-review", "Run a code review", "orchestration"),
        ("ultrareview", "Run an extended review", "orchestration"),
        ("deep-research", "Start a deep research task", "orchestration"),
        ("ultraplan", "Start an extended planning task", "orchestration"),
        ("git", "Run a safe git inspection", "developer"),
        ("diff", "Show the current git diff summary", "developer"),
        ("branch", "Show the current git branch", "developer"),
        ("log", "Show recent git commits", "developer"),
        ("advisor", "Show advisor status", "general"),
        ("focus", "Show focus status", "general"),
        ("fewer-permission-prompts", "Show permission prompt settings", "settings"),
        ("background", "Show background task support", "general"),
        ("desktop", "Show desktop integration support", "integrations"),
        ("mobile", "Show mobile integration support", "integrations"),
        ("teleport", "Show remote session support", "integrations"),
        ("remote-control", "Show remote control support", "integrations"),
        ("remote-env", "Show remote environment support", "integrations"),
        ("chrome", "Show browser integration support", "integrations"),
        ("install-github-app", "Show GitHub integration setup", "integrations"),
        ("install-slack-app", "Show Slack integration setup", "integrations"),
        ("passes", "Show account pass status", "general"),
        ("powerup", "Show account power-up status", "general"),
        ("privacy-settings", "Show privacy settings support", "settings"),
        ("radio", "Show radio support", "general"),
        ("stickers", "Show sticker support", "general"),
        ("upgrade", "Show upgrade support", "general"),
        ("usage-credits", "Show account usage-credit support", "info"),
        ("claude-api", "Show Claude API integration support", "integrations"),
        ("run-skill-generator", "Show skill generator support", "integrations"),
        ("scroll-speed", "Show terminal scroll-speed support", "settings"),
        ("setup-bedrock", "Show Bedrock setup support", "settings"),
        ("setup-vertex", "Show Vertex setup support", "settings"),
        ("open", "Open the selected activity or panel", "general"),
        ("detail", "Open activity detail", "general"),
        ("close", "Close the active panel", "general"),
        ("panel", "Open or close a named panel", "general"),
        ("back", "Return to the previous panel", "general"),
        ("engine", "Show local engine integration support", "integrations"),
    ]
    # Import real implementations for commands that need them
    try:
        from nexus.commands_real import (
            _cmd_health as _real_health, _cmd_doctor as _real_doctor,
            _cmd_queue as _real_queue, _cmd_scheduler as _real_scheduler,
            _cmd_evolution as _real_evolution, _cmd_git as _real_git,
            _cmd_diff as _real_diff, _cmd_branch as _real_branch,
            _cmd_log as _real_log, _cmd_fork as _real_fork,
            _cmd_batch as _real_batch, _cmd_multi_agent as _real_multi_agent,
            _cmd_code_review as _real_code_review, _cmd_security_review as _real_security_review,
            _cmd_ultraplan as _real_ultraplan, _cmd_ultrareview as _real_ultrareview,
            _cmd_deep_research as _real_deep_research, _cmd_powerup as _real_powerup,
            _cmd_teleport as _real_teleport,
        )
        from nexus.commands_real_all import (
            _cmd_pwd as _r_pwd, _cmd_where as _r_where, _cmd_files as _r_files,
            _cmd_ls as _r_ls, _cmd_tree as _r_tree, _cmd_cat as _r_cat,
            _cmd_cd as _r_cd, _cmd_add_dir as _r_add_dir, _cmd_readme as _r_readme,
            _cmd_init as _r_init, _cmd_docs as _r_docs,
            _cmd_enable as _r_enable, _cmd_disable as _r_disable, _cmd_fast as _r_fast,
            _cmd_reset as _r_reset, _cmd_reload as _r_reload, _cmd_settings as _r_settings,
            _cmd_env as _r_env, _cmd_theme as _r_theme, _cmd_color as _r_color,
            _cmd_statusline as _r_statusline, _cmd_output_style as _r_output_style,
            _cmd_tui as _r_tui, _cmd_keybindings as _r_keybindings,
            _cmd_scroll_speed as _r_scroll_speed, _cmd_terminal_setup as _r_terminal_setup,
            _cmd_voice as _r_voice, _cmd_api as _r_api, _cmd_open_gui as _r_open_gui,
            _cmd_ide as _r_ide, _cmd_chrome as _r_chrome, _cmd_desktop as _r_desktop,
            _cmd_mobile as _r_mobile, _cmd_engine as _r_engine,
            _cmd_install_github_app as _r_install_github, _cmd_install_slack_app as _r_install_slack,
            _cmd_setup_bedrock as _r_setup_bedrock, _cmd_setup_vertex as _r_setup_vertex,
            _cmd_claude_api as _r_claude_api, _cmd_run_skill_generator as _r_skill_gen,
            _cmd_conversations as _r_conversations, _cmd_load as _r_load,
            _cmd_rename as _r_rename, _cmd_delete_session as _r_delete_session,
            _cmd_export as _r_export,
            _cmd_usage as _r_usage, _cmd_logs as _r_logs, _cmd_debug as _r_debug,
            _cmd_heapdump as _r_heapdump, _cmd_recap as _r_recap,
            _cmd_insights as _r_insights, _cmd_btw as _r_btw, _cmd_sources as _r_sources,
            _cmd_copy as _r_copy, _cmd_paste as _r_paste,
            _cmd_usage_credits as _r_usage_credits, _cmd_passes as _r_passes,
            _cmd_privacy_settings as _r_privacy, _cmd_radio as _r_radio,
            _cmd_stickers as _r_stickers, _cmd_upgrade as _r_upgrade,
            _cmd_advisor as _r_advisor, _cmd_focus as _r_focus,
            _cmd_fewer_permission_prompts as _r_fewer_perm, _cmd_background as _r_background,
            _cmd_check as _r_check, _cmd_build as _r_build,
            _cmd_open as _r_open, _cmd_detail as _r_detail, _cmd_close as _r_close,
            _cmd_panel as _r_panel, _cmd_back as _r_back,
            _cmd_goal as _r_goal, _cmd_todo as _r_todo,
            _cmd_features as _r_features, _cmd_logout as _r_logout, _cmd_loop as _r_loop,
            _cmd_reminders as _r_reminders, _cmd_remote_control as _r_remote_control,
            _cmd_remote_env as _r_remote_env, _cmd_retry as _r_retry, _cmd_schedule as _r_schedule,
            _cmd_team_onboarding as _r_team_onboarding, _cmd_work as _r_work,
        )
        _real_overrides = {
            "health": _real_health, "doctor": _real_doctor, "queue": _real_queue,
            "scheduler": _real_scheduler, "evolution": _real_evolution,
            "git": _real_git, "diff": _real_diff, "branch": _real_branch,
            "log": _real_log, "fork": _real_fork, "batch": _real_batch,
            "multi-agent": _real_multi_agent, "multi_agent": _real_multi_agent,
            "code-review": _real_code_review, "security-review": _real_security_review,
            "ultraplan": _real_ultraplan, "ultrareview": _real_ultrareview,
            "deep-research": _real_deep_research, "powerup": _real_powerup,
            "teleport": _real_teleport,
            "pwd": _r_pwd, "where": _r_where, "files": _r_files,
            "ls": _r_ls, "tree": _r_tree, "cat": _r_cat,
            "cd": _r_cd, "add-dir": _r_add_dir, "readme": _r_readme,
            "init": _r_init, "docs": _r_docs,
            "enable": _r_enable, "disable": _r_disable, "fast": _r_fast,
            "reset": _r_reset, "reload": _r_reload, "settings": _r_settings,
            "env": _r_env, "theme": _r_theme, "color": _r_color,
            "statusline": _r_statusline, "output-style": _r_output_style,
            "tui": _r_tui, "keybindings": _r_keybindings,
            "scroll-speed": _r_scroll_speed, "terminal-setup": _r_terminal_setup,
            "voice": _r_voice, "api": _r_api, "open-gui": _r_open_gui,
            "ide": _r_ide, "chrome": _r_chrome, "desktop": _r_desktop,
            "mobile": _r_mobile, "engine": _r_engine,
            "install-github-app": _r_install_github, "install-slack-app": _r_install_slack,
            "setup-bedrock": _r_setup_bedrock, "setup-vertex": _r_setup_vertex,
            "claude-api": _r_claude_api, "run-skill-generator": _r_skill_gen,
            "conversations": _r_conversations, "load": _r_load,
            "rename": _r_rename, "delete-session": _r_delete_session,
            "export": _r_export,
            "usage": _r_usage, "logs": _r_logs, "debug": _r_debug,
            "heapdump": _r_heapdump, "recap": _r_recap,
            "insights": _r_insights, "btw": _r_btw, "sources": _r_sources,
            "copy": _r_copy, "paste": _r_paste,
            "usage-credits": _r_usage_credits, "passes": _r_passes,
            "privacy-settings": _r_privacy, "radio": _r_radio,
            "stickers": _r_stickers, "upgrade": _r_upgrade,
            "advisor": _r_advisor, "focus": _r_focus,
            "fewer-permission-prompts": _r_fewer_perm, "background": _r_background,
            "check": _r_check, "build": _r_build,
            "open": _r_open, "detail": _r_detail, "close": _r_close,
            "panel": _r_panel, "back": _r_back,
            "goal": _r_goal, "todo": _r_todo,
            "features": _r_features, "logout": _r_logout, "loop": _r_loop,
            "reminders": _r_reminders, "remote-control": _r_remote_control,
            "remote-env": _r_remote_env, "retry": _r_retry, "schedule": _r_schedule,
            "team-onboarding": _r_team_onboarding, "work": _r_work,
        }
    except Exception:
        _real_overrides = {}

    for name, description, category in interactive_commands:
        if reg.get(name) is None:
            handler = _real_overrides.get(name, _cmd_client_catalog_entry)
            reg.register(Command(name, description, handler, category=category, execution="client"))

    # Compatibility aliases are catalog data too. Keep them here so TUI, GUI,
    # headless CLI, and gateways resolve the same spelling to the same command.
    aliases = {
        "provider": ("connect",), "model": ("models",), "sessions": ("chats",),
        "tools": ("tool",), "skills": ("skill",), "plugins": ("plugin",),
        "mcp": ("mcps", "mpc"), "enable": ("on",), "disable": ("off",),
        "agents": ("agent",), "voice": ("voi", "mic", "talk"),
        "engine": ("eng", "backend"), "git": ("gst", "gstatus"),
        "tasks": ("bashes",), "cost": ("stats",),
        "ide": ("editor",), "background": ("bg",), "desktop": ("app",),
        "mobile": ("ios", "android"), "teleport": ("tp",),
        "remote-control": ("rc",), "reload": ("reload-plugins", "reload-skills"),
        "check": ("test-check",),
        "hiveteam": ("hive-team",),
    }
    for canonical, names in aliases.items():
        command = reg.get(canonical)
        if command is None:
            continue
        for alias in names:
            if reg.get(alias) is None:
                command.aliases.append(alias)
                reg._by_name[alias] = command

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
    def create(cls, prompt: str, **kwargs: Any) -> str:
        import uuid
        task_id = str(uuid.uuid4())
        entry = {"id": task_id, "prompt": prompt, "subject": prompt, "status": "running"}
        entry.update(kwargs)
        cls._tasks.append(entry)
        return task_id

    @classmethod
    def update(cls, task_id: str, status: str) -> None:
        """Update the status of a task by ID."""
        for t in cls._tasks:
            if t["id"] == task_id:
                t["status"] = status
                return

    @classmethod
    def delete(cls, task_id: str) -> None:
        """Remove a task by ID."""
        cls._tasks = [t for t in cls._tasks if t["id"] != task_id]

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return list(cls._tasks)
