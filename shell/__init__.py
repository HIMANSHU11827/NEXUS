"""TUI (Rich) for the NEXUS local agent runtime.

Real-time TUI showing thinking, tools, plugins, MCP, skills, hive.
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import asyncio
import atexit
import json
import re
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))
from collections import deque
from typing import Optional, List, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.table import Table
from rich.prompt import Prompt
from rich.markup import escape
from rich.syntax import Syntax
from rich.box import ROUNDED

# ── Custom Theme for NEXUS ───────────────────────────────────────────────────
nexus_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "nexus": "bold magenta",
    "user": "bold blue",
    "system": "italic grey50",
    "tool": "italic grey70",
    "agent": "bold cyan",
    "task": "bold yellow",
    "skill": "bold green",
    "dim": "grey50",
    "path": "underline blue",
})

console = Console(theme=nexus_theme)

# ── Import Architecture ──────────────────────────────────────────────────────
from orchestrators.loop import NexusLoop

# ── Spinner System ──────────────────────────────────────────────────────────
_SPINNER_DEFAULTS = {
    "thinking": {"spinner": ["✢", "✶", "✻", "✽", "✾", "✤"], "speed": 50, "color": "yellow", "compact": "thinking..."},
    "tools":    {"spinner": ["◉", "○", "◉", "○"], "speed": 100, "color": "green", "compact": "tools..."},
    "plugins":  {"spinner": ["◇", "◈", "◆", "◈"], "speed": 80, "color": "cyan", "compact": "plugins..."},
    "mcp":      {"spinner": ["∿", "∽", "∿", "∽"], "speed": 120, "color": "magenta", "compact": "mcp..."},
    "skills":   {"spinner": ["▣", "□", "▣", "□"], "speed": 80, "color": "blue", "compact": "skills..."},
    "hive":     {"spinner": ["⬡", "⬢", "⬡", "⬢"], "speed": 80, "color": "white", "compact": "hive..."},
    "settings": {"spinner": ["⦾", "⦿", "⦾", "⦿"], "speed": 100, "color": "gray", "compact": "settings..."},
    "compact":  {"spinner": ["╫", "╪", "╫", "╪"], "speed": 80, "color": "dim", "compact": "compacting..."},
}

class CategorySpinner:
    """Cycles through spinner frames at configured speed."""

    def __init__(self, category: str, config: dict | None = None):
        cat = (config or {}).get(category) or _SPINNER_DEFAULTS.get(category) or {}
        self.frames: list[str] = cat.get("spinner", ["."])
        self.speed: float = cat.get("speed", 100) / 1000.0
        self.color: str = cat.get("color", "white")
        self.compact: str = cat.get("compact", "")
        self._i = 0

    def next(self) -> str:
        f = self.frames[self._i % len(self.frames)]
        self._i += 1
        return f


# ── Task Tracking ────────────────────────────────────────────────────────────
class TaskTracker:
    """Lightweight in-memory task tracking."""

    _tasks: List[dict] = []
    _counter = 0

    @classmethod
    def create(cls, subject: str, agent: str = "") -> str:
        cls._counter += 1
        tid = f"task_{cls._counter}"
        cls._tasks.append({
            "id": tid,
            "subject": subject,
            "status": "pending",
            "agent": agent
        })
        return tid

    @classmethod
    def update(cls, tid: str, status: str) -> bool:
        for t in cls._tasks:
            if t["id"] == tid:
                t["status"] = status
                return True
        return False

    @classmethod
    def list(cls) -> List[dict]:
        return cls._tasks

    @classmethod
    def clear_completed(cls):
        cls._tasks = [t for t in cls._tasks if t["status"] != "completed"]


# ── Shell ────────────────────────────────────────────────────────────────────
class NexusShell:
    """NEXUS TUI (Rich) — slash commands, shortcuts, status bar, tasks."""

    MAX_HISTORY = 50
    COMMANDS = {
        "/help": "Show help",
        "/exit": "Exit NEXUS",
        "/quit": "Exit NEXUS",
        "/clear": "Clear screen",
        "/new": "New session",
        "/sessions": "List sessions",
        "/session": "Switch session",
        "/model": "Switch model",
        "/provider": "Switch provider",
        "/mode": "Set mode",
        "/agent": "Switch agent",
        "/skills": "List skills",
        "/tools": "List tools",
        "/agents": "List agents",
        "/tasks": "Show tasks",
        "/status": "System status",
        "/run": "Run bash command",
        "/auto": "Auto mode",
        "/plan": "Plan mode",
        "/accept": "Accept edits mode",
        "/dontask": "Dont ask mode",
        "/review": "Run code review",
        "/simplify": "Run simplify",
        "/verify": "Verify changes",
        "/memory": "Show memory info",
        "/events": "Show shared mission/work events for this session",
        "/save": "Save conversation",
        "/load": "Load conversation",
        "/gui": "Launch GUI",
        "/workflow": "Run workflow from YAML",
        "/thinking": "Toggle thinking mode on/off",
    }

    def __init__(self):
        self._brain: Optional[NexusLoop] = None
        self.is_running = False
        self.conversation_history: deque = deque(maxlen=self.MAX_HISTORY)
        self.session_id = "default"
        self.model = "kimi-k2.6"
        self.mode = "auto"
        self.provider = "lm_studio"
        self._scripted_inputs: Optional[list] = None
        self._scripted_index = 0
        self._pending_agent_prompt: Optional[str] = None
        self._pending_task_id: Optional[str] = None
        self._load_history()

    def _load_history(self):
        try:
            history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nexus_history.json")
            if os.path.exists(history_file):
                with open(history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    self.conversation_history = deque(data, maxlen=self.MAX_HISTORY)
        except Exception:
            pass

    def _save_history(self):
        try:
            history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nexus_history.json")
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(list(self.conversation_history), f, indent=2)
        except Exception:
            pass

    @property
    def brain(self) -> NexusLoop:
        if self._brain is None:
            self._brain = NexusLoop()
            self._brain.load_memory(self.session_id)
        return self._brain

    def _apply_session(self, session_id: str, source: str = "terminal") -> None:
        """Switch to a shared session visible across TUI, GUI, and gateway."""
        from utils.session_bus import set_active_session_id

        self.session_id = session_id
        self.brain.load_memory(session_id)
        set_active_session_id(self.brain.root, session_id, source=source)

    def _show_banner(self):
        from shell.assets import BANNER_PRO
        console.clear()
        console.print(BANNER_PRO)
        console.print()
        self._show_status_bar()

    def _show_status_bar(self):
        """Compact status bar: model, mode, session, health."""
        mode_color = {
            "auto": "green",
            "plan": "cyan",
            "acceptedits": "magenta",
            "dontask": "red"
        }.get(self.mode, "grey")
        health = "● online"
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel()
            stats = kernel.get_stats()
            status = stats.get("status", "OK")
            health = f"● {status}"
        except Exception:
            health = "● starting"

        console.print(
            f"[bold magenta]◈ NEXUS[/bold magenta] "
            f"[grey30]v2.1[/grey30] | "
            f"[cyan]{self.model}[/cyan] | "
            f"[{mode_color}]{self.mode}[/{mode_color}] | "
            f"[green]{self.session_id}[/green] | "
            f"[green]{health}[/green]"
        )

    def _show_stats(self):
        """Show a compact one-line stats bar. Fails gracefully if kernel not ready."""
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel()
            stats = kernel.get_stats()
            cpu = stats.get("load", {}).get("cpu", "?")
            ram = stats.get("load", {}).get("ram", "?")
            uptime = stats.get("uptime", 0)
            mode = "?"
            try:
                mode = getattr(self.brain.base_router, "mode", "?")
            except AttributeError:
                pass
            status = stats.get("status", "OK")
            status_color = "green" if status == "healthy" else "yellow"
            console.print(
                f"[cyan]CPU[/cyan] [yellow]{cpu}[/yellow] | "
                f"[cyan]RAM[/cyan] [yellow]{ram}[/yellow] | "
                f"[cyan]UPTIME[/cyan] {uptime}s | "
                f"[cyan]MODE[/cyan] [magenta]{mode}[/magenta] | "
                f"[cyan]STATUS[/cyan] [{status_color}]{status}[/{status_color}]",
                highlight=False
            )
        except ImportError:
            console.print("[yellow]Kernel module not installed — skipping stats[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Kernel not ready ({type(e).__name__}) — starting up...[/yellow]")

    async def _show_thinking_animation(self, stop_event: asyncio.Event, category: str = "thinking"):
        """Animated spinner for a given category."""
        spinner = CategorySpinner(category)
        start = time.monotonic()
        try:
            while not stop_event.is_set():
                elapsed = time.monotonic() - start
                frame = spinner.next()
                label = spinner.compact or f"{category}..."
                sys.stdout.write(f"\r[cyan]◈ NEXUS[/cyan] [dim]──[/dim] [{spinner.color}]{frame}[/{spinner.color}] [{spinner.color}]{label}[/{spinner.color}] [dim]{elapsed:.1f}s[/dim]")
                sys.stdout.flush()
                await asyncio.sleep(spinner.speed)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _cat_marker(category: str) -> str:
        """Return the first spinner frame for a category, or '●' as fallback."""
        cat = _SPINNER_DEFAULTS.get(category, {})
        frames = cat.get("spinner", [])
        return frames[0] if frames else "●"

    def _format_detail(self, kind: str, event: dict) -> Panel:
        """Format a detail Panel for a single event."""
        title = kind.upper()
        lines: list[str] = []

        if kind == "subagent":
            title = f"HIVE: {event.get('persona', event.get('action', 'subagent'))}"
            for k in ("persona", "task", "result", "status", "target"):
                v = event.get(k)
                if v:
                    lines.append(f"[bold]{k}[/bold]  {escape(str(v)[:500])}")
        elif kind == "mcp":
            server = event.get("server", "?")
            tool = event.get("tool_name", event.get("action", "?"))
            title = f"MCP: {server}.{tool}"
            for k in ("server", "tool_name", "arguments", "result", "status"):
                v = event.get(k)
                if v:
                    txt = json.dumps(v, indent=2, default=str) if isinstance(v, (dict, list)) else str(v)
                    lines.append(f"[bold]{k}[/bold]  {escape(txt[:500])}")
        elif kind == "skill":
            title = f"SKILL: {event.get('action', '?')}"
            for k in ("action", "description", "result", "status", "target"):
                v = event.get(k)
                if v:
                    lines.append(f"[bold]{k}[/bold]  {escape(str(v)[:500])}")
        elif kind == "plugin":
            title = f"PLUGIN: {event.get('action', '?')}"
            for k in ("action", "args", "result", "status"):
                v = event.get(k)
                if v:
                    txt = json.dumps(v, indent=2, default=str) if isinstance(v, (dict, list)) else str(v)
                    lines.append(f"[bold]{k}[/bold]  {escape(txt[:500])}")
        elif kind in ("web", "search", "tool", "web_search"):
            title = "WEB SEARCH"
            for k in ("query", "sources", "result", "target"):
                v = event.get(k)
                if v:
                    txt = json.dumps(v, indent=2, default=str) if isinstance(v, (dict, list)) else str(v)
                    lines.append(f"[bold]{k}[/bold]  {escape(txt[:500])}")
        elif kind in ("command", "bash"):
            title = "BASH"
            cmd = event.get("command") or event.get("target") or event.get("related_command", "")
            lines.append(f"[bold]command[/bold]  {escape(cmd[:300])}")
            for k in ("output", "exit_code", "duration_ms", "status"):
                v = event.get(k)
                if v is not None:
                    lines.append(f"[bold]{k}[/bold]  {escape(str(v)[:500])}")
        elif kind in ("file", "edit", "read"):
            title = "FILE"
            for k in ("target", "path", "file_action", "diff", "lines", "content"):
                v = event.get(k)
                if v is not None:
                    txt = str(v)[:600] if k in ("diff", "content") else str(v)
                    lines.append(f"[bold]{k}[/bold]  {escape(txt[:500])}")
        else:
            for k, v in event.items():
                if v is not None:
                    txt = json.dumps(v, indent=2, default=str) if isinstance(v, (dict, list)) else str(v)
                    lines.append(f"[bold]{k}[/bold]  {escape(txt[:500])}")

        body = "\n".join(lines) if lines else "[dim]no details[/dim]"
        return Panel(body, title=f"[bold]{title}[/bold]", border_style="grey50", box=ROUNDED, padding=(1, 2))

    def _render_interactive_summary(self, all_events: list[dict], total_time: float, tools_used: list[dict], errors: list[str]) -> None:
        """Render an interactive list of events that can be expanded via keyboard."""
        if not all_events and not errors:
            return

        tool_names = list(dict.fromkeys(t["name"] for t in tools_used)) if tools_used else None
        console.print()
        console.print(f"[dim]── done ──[/dim]")
        if tool_names:
            console.print(f"[bold green]✔[/bold green] [dim]{total_time:.1f}s[/dim]  [dim]{', '.join(tool_names)}[/dim]")
        if errors:
            console.print(f"[red]⚠ {len(errors)} error(s)[/red]")

        if not all_events:
            return

        console.print()
        console.print(f"[dim]── details ──[/dim]")
        used = [t["name"] + (f": {t['summary'][:60]}" if t.get("summary") else "") for t in tools_used[:6]]
        if used:
            console.print(f"[bold]Tools:[/bold] [dim]{' | '.join(used)}[/dim]")

        grouped: list[tuple[str, str, list[int]]] = []
        kind_icon = {
            "subagent": self._cat_marker("hive"),
            "mcp": self._cat_marker("mcp"),
            "skill": self._cat_marker("skills"),
            "plugin": self._cat_marker("plugins"),
            "web": self._cat_marker("tools"),
            "search": self._cat_marker("tools"),
            "tool": self._cat_marker("tools"),
            "web_search": self._cat_marker("tools"),
            "bash": self._cat_marker("tools"),
            "command": self._cat_marker("tools"),
            "file": "📄", "edit": "📄", "read": "📄",
        }

        prev_kind = None
        prev_action = None
        group_indices: list[int] = []
        group_label = ""

        for i, ev in enumerate(all_events):
            kind = ev.get("kind", "?")
            action = ev.get("action") or ev.get("name") or kind
            label = f"{action}" if action and action != kind else kind
            if kind == prev_kind and action == prev_action and len(group_indices) < 9:
                group_indices.append(i)
            else:
                if group_indices:
                    grouped.append((group_label, kind, group_indices))
                group_indices = [i]
                icon = kind_icon.get(kind, "●")
                if kind == "subagent":
                    group_label = f"[magenta]{icon} hive:[/magenta] {ev.get('persona', label)}"
                elif kind == "mcp":
                    server = ev.get("server", "")
                    tool_name = ev.get("tool_name", label)
                    group_label = f"[blue]{icon} MCP:[/blue] {server}.{tool_name}"
                elif kind in ("skill", "plugin"):
                    group_label = f"[green]{icon} {kind}:[/green] {label}"
                elif kind in ("web", "search", "tool", "web_search"):
                    group_label = f"[cyan]{icon} {label}[/cyan]"
                elif kind in ("bash", "command"):
                    group_label = f"[cyan]{icon} $ {label}[/cyan]"
                elif kind in ("file", "edit", "read"):
                    f_action = ev.get("file_action") or "modified"
                    group_label = f"[cyan]{icon} {f_action}:[/cyan] {ev.get('target','')}"
                else:
                    group_label = f"[cyan]{icon} {label}[/cyan]"
                group_label = f"[dim]{len(grouped)+1}.[/dim] {group_label}"
                prev_kind = kind
                prev_action = action
        if group_indices:
            grouped.append((group_label, kind, group_indices))

        for idx, (label, kind, indices) in enumerate(grouped):
            count = f" [dim](×{len(indices)})[/dim]" if len(indices) > 1 else ""
            console.print(f"  {label}{count}")

        if sys.stdin.isatty():
            console.print()
            console.print("[dim]Enter # to expand, or ENTER to continue:[/dim] ", end="")
            try:
                choice = input().strip()
            except (EOFError, KeyboardInterrupt):
                return

            if choice and choice.isdigit():
                n = int(choice)
                if 1 <= n <= len(grouped):
                    _, _, indices = grouped[n - 1]
                    for idx in indices:
                        ev = all_events[idx]
                        panel = self._format_detail(ev.get("kind", "?"), ev)
                        console.print(panel)

    async def _stream_response(self, user_input: str) -> tuple[str, bool, list[dict], list[dict]]:
        """Real-time streaming with thinking animation, tools, plugins, MCP, skills, hive display."""
        full_response = ""
        interrupted = False
        all_events: list[dict] = []
        tools_used: list[dict] = []
        files_changed: list[dict] = []
        errors: list[str] = []
        start_time = time.monotonic()
        thinking_event = asyncio.Event()
        spinner_task = asyncio.create_task(self._show_thinking_animation(thinking_event))

        try:
            async for chunk in self.brain.stream_run(user_input):
                if not thinking_event.is_set():
                    thinking_event.set()
                    spinner_task.cancel()
                    try:
                        await spinner_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    elapsed = time.monotonic() - start_time
                    spinner = CategorySpinner("thinking")
                    sys.stdout.write(f"\r[cyan]◈ NEXUS[/cyan] [dim]──[/dim] [{spinner.color}]{spinner.frames[0]}[/{spinner.color}] [bold]{spinner.compact or 'thinking'}[/bold] [dim]{elapsed:.1f}s[/dim]     \n")
                    sys.stdout.flush()

                t = chunk.get("type", "?")
                d = chunk.get("data", "")

                if t == "content":
                    console.print(d, end="")
                    full_response += d

                elif t == "status":
                    label = d.strip()
                    if label.startswith("[error") or label.startswith("[aborted"):
                        console.print(f"[bold red]{escape(d)}[/bold red]")
                    else:
                        console.print(f"[grey50 italic]{escape(d)}[/grey50 italic]")

                elif t == "observations":
                    for line in d if isinstance(d, list) else [d]:
                        console.print(f"[grey70]{escape(str(line))}[/grey70]")

                elif t == "plan":
                    console.print(f"[bold cyan]{escape(d)}[/bold cyan]")

                elif t == "tools_discovered":
                    calls = chunk.get("tool_calls", d if isinstance(d, list) else [])
                    for tc in calls:
                        name = tc.get("name", "?")
                        args = tc.get("arguments") or tc.get("parameters") or {}
                        summary = str(args.get("command") or args.get("path") or args.get("query") or "").strip()
                        summary = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*\S+", r"\1=[REDACTED]", summary)
                        m = self._cat_marker("tools")
                        console.print(f"  [cyan]{m}[/cyan] [bold]{name}[/bold] [dim]{summary[:120]}[/dim]")
                        tools_used.append({"name": name, "summary": summary[:160]})
                        all_events.append({"kind": "tool", "name": name, "arguments": args})

                elif t == "work_event":
                    event = chunk.get("event") or d or {}
                    if isinstance(event, str):
                        continue
                    visibility = str(event.get("visibility", "public")).lower()
                    if visibility == "internal":
                        continue
                    kind = (str(event.get("kind") or event.get("type") or "").lower()).split(".")[0]
                    status = str(event.get("status") or "running").lower()
                    action = str(event.get("action") or event.get("title") or "")
                    target = str(event.get("target") or event.get("command") or event.get("path") or event.get("query") or event.get("related_command") or "")

                    if status in ("error", "failed", "blocked"):
                        errors.append(action)
                        console.print(f"  [red]●[/red] [bold]{action}[/bold] [dim]{target[:120]}[/dim]")
                        all_events.append({"kind": "error", "action": action, "target": target, "status": status, **event})
                        if status in ("error", "failed"):
                            interrupted = True
                        continue

                    if kind == "stage":
                        continue

                    if kind == "subagent":
                        persona = str(event.get("persona") or action)
                        m = self._cat_marker("hive")
                        console.print(f"  [magenta]{m}[/magenta] [bold]{persona}[/bold] [dim]{target[:80]}[/dim]")
                        tools_used.append({"name": f"hive:{persona}", "summary": target[:160]})
                        all_events.append({"kind": kind, "persona": persona, "target": target, **event})
                        continue

                    if kind == "mcp":
                        server = str(event.get("server") or "")
                        tool_name = str(event.get("tool_name") or action)
                        m = self._cat_marker("mcp")
                        console.print(f"  [blue]{m}[/blue] [bold]MCP:[/bold] [bold]{tool_name}[/bold] [dim]server={server} {target[:60]}[/dim]")
                        tools_used.append({"name": f"mcp:{tool_name}", "summary": target[:160]})
                        all_events.append({"kind": kind, "server": server, "tool_name": tool_name, "target": target, **event})
                        continue

                    if kind == "skill":
                        m = self._cat_marker("skills")
                        console.print(f"  [green]{m}[/green] [bold]skill:[/bold] [bold]{action}[/bold] [dim]{target[:80]}[/dim]")
                        tools_used.append({"name": f"skill:{action}", "summary": target[:160]})
                        all_events.append({"kind": kind, "action": action, "target": target, **event})
                        continue

                    if kind == "plugin":
                        m = self._cat_marker("plugins")
                        console.print(f"  [yellow]{m}[/yellow] [bold]plugin:[/bold] [bold]{action}[/bold] [dim]{target[:80]}[/dim]")
                        tools_used.append({"name": f"plugin:{action}", "summary": target[:160]})
                        all_events.append({"kind": kind, "action": action, "target": target, **event})
                        continue

                    if kind in ("file", "edit", "read"):
                        f_action = event.get("file_action") or "modified"
                        console.print(f"  [cyan]●[/cyan] [bold]{f_action}[/bold] [dim]{target[:120]}[/dim]")
                        if target:
                            files_changed.append({"path": target, "action": f_action})
                        all_events.append({"kind": kind, "file_action": f_action, "target": target, **event})
                        continue

                    if kind in ("command", "bash"):
                        cmd = event.get("command") or target
                        suffix = ""
                        ec = event.get("exit_code")
                        if ec is not None:
                            suffix = f" [dim]exit {ec}[/dim]"
                        elif status == "running":
                            suffix = f" [dim]{status}[/dim]"
                        elif status in ("success", "completed"):
                            suffix = f" [dim]✓ done[/dim]"
                        elif status and status not in ("pending", "queued"):
                            suffix = f" [dim]{status}[/dim]"
                        else:
                            suffix = ""
                        dur = event.get("duration_ms")
                        if dur is not None:
                            suffix += f" [dim]{dur}ms[/dim]"
                        if status == "success":
                            suffix += f" [dim]{status}[/dim]"
                        m = self._cat_marker("tools")
                        console.print(f"  [cyan]{m}[/cyan] [bold]$[/bold] [dim]{cmd[:120]}[/dim]{suffix}")
                        tools_used.append({"name": "bash", "summary": cmd[:160]})
                        all_events.append({"kind": "command", "command": cmd, **event})
                        continue

                    if kind in ("search", "web", "tool"):
                        m = self._cat_marker("tools")
                        console.print(f"  [cyan]{m}[/cyan] [bold]{action or kind}[/bold] [dim]{target[:120]}[/dim]")
                        tools_used.append({"name": kind, "summary": target[:160]})
                        all_events.append({"kind": kind, "action": action, "target": target, **event})
                        continue

                    console.print(f"  [cyan]●[/cyan] [bold]{action or kind}[/bold] [dim]{target[:120]}[/dim]")
                    all_events.append({"kind": kind, "action": action, "target": target, **event})

                elif t in ("error", "tool_error"):
                    console.print(f"  [red]●[/red] [bold]ERROR:[/bold] [dim]{escape(str(d)[:200])}[/dim]")
                    errors.append(str(d))
                    all_events.append({"kind": "error", "message": str(d)})
                    interrupted = True

        except asyncio.CancelledError:
            if not thinking_event.is_set():
                thinking_event.set()
                spinner_task.cancel()
            console.print("\n[yellow]Cancelled.[/yellow]")
            interrupted = True
        except Exception as e:
            if not thinking_event.is_set():
                thinking_event.set()
                spinner_task.cancel()
            console.print(f"\n[bold red]ERROR:[/bold red] {escape(str(e))}")
            interrupted = True
        finally:
            if not thinking_event.is_set():
                thinking_event.set()
                spinner_task.cancel()

        total_time = time.monotonic() - start_time

        self._render_interactive_summary(all_events, total_time, tools_used, errors)

        return full_response, interrupted, files_changed, tools_used

    def _read_user_input(self) -> str:
        if sys.stdin.isatty():
            return Prompt.ask(f"[bold blue]nexus[/bold blue] [{self.mode}]")
        print("nexus: ", end="", flush=True)
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")

    def _show_help(self):
        table = Table(title="NEXUS AI Commands", box=None)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description", style="grey70")
        for cmd, desc in sorted(self.COMMANDS.items()):
            table.add_row(cmd, desc)
        console.print(table)
        console.print()
        console.print("[bold grey]Shortcuts:[/bold grey] ^C abort / exit  ^L clear  ^T tasks")

    def _list_sessions(self):
        """List saved sessions from the session directory."""
        session_dir = os.path.join(self.brain.root, "logs", "sessions")
        if not os.path.exists(session_dir):
            console.print("[yellow]No sessions yet.[/yellow]")
            return
        files = [f for f in os.listdir(session_dir) if f.endswith(".json")]
        table = Table(title="Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        for f in sorted(files):
            sid = f.replace(".json", "")
            meta_path = os.path.join(session_dir, f"{sid}.meta")
            title = "Untitled"
            if os.path.exists(meta_path):
                try:
                    import json
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                        title = meta.get("title", "Untitled")
                except Exception:
                    pass
            table.add_row(sid, title)
        console.print(table)

    def _show_tasks(self):
        """Show active tasks."""
        tasks = TaskTracker.list()
        if not tasks:
            console.print("[grey50]No active tasks.[/grey50]")
            return
        table = Table(title="Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Subject", style="white")
        table.add_column("Status", style="yellow")
        table.add_column("Agent", style="magenta")
        for t in tasks:
            status_color = "green" if t["status"] == "completed" else "yellow" if t["status"] == "in_progress" else "grey"
            table.add_row(
                t["id"],
                t["subject"][:50],
                f"[{status_color}]{t['status']}[/{status_color}]",
                t.get("agent", "")
            )
        console.print(table)

    def _show_work_events(self, limit: int = 20):
        """Show mission timeline events shared with GUI/CLI for the active session."""
        events_path = os.path.join(
            self.brain.root, "workspace", "work_events", f"{self.session_id}.jsonl"
        )
        if not os.path.exists(events_path):
            console.print(f"[yellow]No work events for session {self.session_id}.[/yellow]")
            console.print("[dim]Start a mission in GUI or terminal — events appear on all surfaces.[/dim]")
            return
        rows = []
        try:
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            console.print(f"[red]Failed to read work events: {e}[/red]")
            return
        if not rows:
            console.print(f"[yellow]No work events for session {self.session_id}.[/yellow]")
            return
        table = Table(title=f"Work Events — {self.session_id}")
        table.add_column("Status", style="yellow")
        table.add_column("Action", style="cyan")
        table.add_column("Target", style="white")
        table.add_column("Source", style="magenta")
        for event in rows[-limit:]:
            table.add_row(
                str(event.get("status", "")),
                str(event.get("action", event.get("kind", "")))[:40],
                str(event.get("target", ""))[:50],
                str(event.get("source", event.get("tool", "")))[:20],
            )
        console.print(table)

    def _show_status(self):
        """Show system status."""
        self._show_status_bar()
        self._show_stats()
        console.print(f"[cyan]Session:[/cyan] {self.session_id}")
        console.print(f"[cyan]Model:[/cyan] {self.model}")
        console.print(f"[cyan]Mode:[/cyan] {self.mode}")
        console.print(f"[cyan]Tasks:[/cyan] {len(TaskTracker.list())}")

    def _show_skills(self):
        """List skills from .opencode/skills."""
        skills_dir = os.path.join(self.brain.root, ".opencode", "skills")
        if not os.path.isdir(skills_dir):
            console.print("[yellow]No skills directory found.[/yellow]")
            return
        table = Table(title="Skills")
        table.add_column("Name", style="green")
        table.add_column("Description", style="grey70")
        for name in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, name, "SKILL.md")
            desc = ""
            if os.path.exists(skill_path):
                try:
                    with open(skill_path, "r", encoding="utf-8") as f:
                        desc = f.readline().strip().lstrip("# ")[:60]
                except Exception:
                    pass
            table.add_row(name, desc or "NEXUS skill")
        console.print(table)

    def _show_agents(self):
        """List agents from .opencode/agents."""
        agents_dir = os.path.join(self.brain.root, ".opencode", "agents")
        if not os.path.isdir(agents_dir):
            console.print("[yellow]No agents directory found.[/yellow]")
            return
        table = Table(title="Agents")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Status", style="green")
        for fname in sorted(os.listdir(agents_dir)):
            if fname.endswith(".yaml"):
                name = fname.replace(".yaml", "")
                table.add_row(name, name.replace("-", " ").title(), "idle")
        console.print(table)

    def _show_tools(self):
        """List registered tools."""
        table = Table(title="NEXUS AI Registered Tools")
        table.add_column("Tool Name", style="magenta")
        table.add_column("Type", style="cyan")
        table.add_column("Safe", style="green")
        table.add_column("Description", style="yellow")
        try:
            from tools.nexus_tools.registry import ToolRegistry
            registry = ToolRegistry()
            for name in sorted(registry.list_tools()):
                tool = registry.get(name)
                if tool:
                    is_read = "Read-Only" if tool.is_read_only() else "Write/Edit"
                    is_safe = "Yes" if tool.is_concurrency_safe() else "No"
                    table.add_row(name, is_read, is_safe, tool.description[:60])
            console.print(table)
        except ImportError:
            console.print("[yellow]Tool registry not available.[/yellow]")

    def _run_bash(self, command: str):
        """Run a bash command safely."""
        import subprocess
        dangerous = {"rm -rf", "sudo", "mkfs", "dd if=", "> /dev", ":(){"}
        lowered = command.lower()
        for d in dangerous:
            if d in lowered:
                console.print(f"[bold red]BLOCKED:[/bold red] Dangerous command: {d}")
                return
        console.print(f"[dim]Command started: {command[:200]}[/dim]")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            if result.stdout:
                console.print(result.stdout[:5000])
            if result.stderr:
                console.print(f"[yellow]{result.stderr[:2000]}[/yellow]")
            ec = result.returncode
            console.print(f"[dim]Command completed · exit code {ec}[/dim]")
            return ec
        except subprocess.TimeoutExpired:
            console.print("[yellow]Command timed out after 30s[/yellow]")
        except Exception as e:
            console.print(f"[bold red]ERROR:[/bold red] {e}")

    def _handle_slash(self, cmd: str) -> bool:
        """Handle slash commands. Returns True if handled."""
        lower = cmd.lower()
        parts = cmd.split()
        base = parts[0].lower()

        if base in ("/exit", "/quit"):
            self.is_running = False
            return True
        if base == "/help":
            self._show_help()
            return True
        if base == "/clear":
            self._show_banner()
            return True
        if base == "/new":
            import time
            self._apply_session(f"session_{int(time.time())}")
            self.brain.save_memory()
            console.print(f"[green]New session: {self.session_id}[/green]")
            console.print("[dim]Same session id is visible in GUI and gateway.[/dim]")
            return True
        if base == "/sessions":
            self._list_sessions()
            return True
        if base == "/session" and len(parts) > 1:
            self._apply_session(parts[1])
            console.print(f"[green]Switched to session: {self.session_id}[/green]")
            return True
        if base == "/events":
            self._show_work_events()
            return True
        if base == "/model":
            if len(parts) > 1:
                new_model = parts[1]
                self.model = new_model
                try:
                    p = getattr(self.brain.base_router, "provider", None)
                    if p and hasattr(p, "model"):
                        p.model = new_model
                except Exception:
                    pass
                console.print(f"[green]✓ Model: {new_model}[/green]")
            else:
                console.print(f"[bold]Current model:[/bold] {self.model}")
                console.print(f"[bold]Usage:[/bold] [cyan]/model <name>[/cyan] — switch model")
            return True
        if base == "/provider":
            if len(parts) > 1:
                new_prov = parts[1]
                self.provider = new_prov
                try:
                    self.brain.set_override(new_prov)
                except Exception:
                    pass
                console.print(f"[green]✓ Provider: {new_prov}[/green]")
            else:
                console.print(f"[bold]Current provider:[/bold] {self.provider}")
                console.print(f"[bold]Usage:[/bold] [cyan]/provider <name>[/cyan] — switch provider")
            return True
        if base == "/mode" and len(parts) > 1:
            self.mode = parts[1].lower()
            console.print(f"[green]Mode: {self.mode}[/green]")
            return True
        if base == "/agent" and len(parts) > 1:
            console.print(f"[green]Agent: {parts[1]}[/green]")
            return True
        if base == "/auto":
            self.mode = "auto"
            console.print("[green]Mode: auto[/green]")
            return True
        if base == "/plan":
            self.mode = "plan"
            console.print("[green]Mode: plan[/green]")
            return True
        if base == "/accept":
            self.mode = "acceptEdits"
            console.print("[green]Mode: acceptEdits[/green]")
            return True
        if base == "/dontask":
            self.mode = "dontAsk"
            console.print("[green]Mode: dontAsk[/green]")
            return True
        if base == "/skills":
            self._show_skills()
            return True
        if base == "/tools":
            self._show_tools()
            return True
        if base == "/agents":
            self._show_agents()
            return True
        if base == "/tasks":
            self._show_tasks()
            return True
        if base == "/thinking":
            new_state = not self.brain.thinking_mode
            self.brain.configure_thinking(new_state)
            state = "ON" if new_state else "OFF"
            console.print(f"[cyan]Thinking mode: {state} (native model thinking)[/cyan]")
            return True
        if base == "/status":
            self._show_status()
            return True
        if base == "/run" and len(parts) > 1:
            self._run_bash(" ".join(parts[1:]))
            return True
        if base == "/memory":
            console.print(f"[cyan]History: {len(self.conversation_history)} messages[/cyan]")
            console.print(f"[cyan]Session: {self.session_id}[/cyan]")
            return True
        if base == "/gui":
            console.print("[bold cyan]Starting NEXUS GUI...[/bold cyan]")
            import subprocess
            try:
                subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/run-gui.ps1"],
                    cwd=self.brain.root,
                    creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0) if os.name == "nt" else 0
                )
                console.print("[bold green]GUI launched.[/bold green]")
                console.print("Backend API: http://127.0.0.1:8000")
                console.print("React Frontend: http://127.0.0.1:5173")
            except Exception as e:
                console.print(f"[bold red]Failed:[/bold red] {e}")
            return True
        if base == "/workflow" and len(parts) > 1:
            yaml_path = " ".join(parts[1:])
            if not os.path.exists(yaml_path):
                console.print(f"[bold red]ERROR:[/bold red] YAML not found: {yaml_path}")
                return True
            console.print(f"[bold cyan]Running workflow from {yaml_path}...[/bold cyan]")
            try:
                from orchestrators.workflow_engine import NexusWorkflow
                wf = NexusWorkflow()
                results = wf.run_from_yaml(yaml_path)
                console.print(f"[bold green]WORKFLOW COMPLETED.[/bold green]")
                console.print(results)
            except Exception as e:
                console.print(f"[bold red]WORKFLOW FAILED:[/bold red] {e}")
            return True
        if base in ("/review", "/simplify", "/verify"):
            prompts = {
                "/review": "Review the current project for code quality, bugs, and improvements",
                "/simplify": "Analyze and suggest simplifications for the current project code",
                "/verify": "Verify the current project changes work correctly and pass all tests",
            }
            self._pending_agent_prompt = prompts.get(base, f"Run {base}")
            self._pending_task_id = TaskTracker.create(base, agent="multi-agent")
            TaskTracker.update(self._pending_task_id, "running")
            console.print(f"[bold cyan]Created {base} task...[/bold cyan]")
            console.print("[dim]Full multi-agent workflow engine integration required.[/dim]")
            return True

        return False

    async def start(self):
        from utils.session_bus import get_active_session_id

        active = get_active_session_id(self.brain.root, self.session_id)
        if active != self.session_id:
            self._apply_session(active)

        self._show_banner()
        self._show_stats()
        console.print("[bold cyan]NEXUS Terminal v2.1[/bold cyan] — Type [bold red]/help[/bold red] for commands.")
        console.print(f"[dim]Linked session: {self.session_id} (shared with GUI, gateway)[/dim]\n")
        self.is_running = True

        while self.is_running:
            try:
                user_msg = self._read_user_input()

                if not user_msg:
                    continue

                if user_msg.lower() in ("exit", "quit"):
                    break

                # Handle slash commands
                if user_msg.startswith("/"):
                    handled = self._handle_slash(user_msg)
                    if handled:
                        continue

                self.conversation_history.append({"role": "user", "content": user_msg})
                console.print("[dim italic]processing...[/dim italic]")
                full_response, interrupted, files_changed, tools_used = await self._stream_response(user_msg)
                print()

                if not interrupted:
                    self.conversation_history.append({"role": "assistant", "content": full_response})

            except (KeyboardInterrupt, EOFError):
                break

        console.print("\n[bold red]SESSION TERMINATED.[/bold red]")


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(NexusShell().start())
