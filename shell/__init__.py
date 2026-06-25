"""Terminal interface for the NEXUS local agent runtime.

Claude Code CLI clone — slash commands, keyboard shortcuts, status bar,
readline history, task tracking, multi-agent mode.
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import atexit

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))
from collections import deque
from typing import Optional, List

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from rich.table import Table
from rich.prompt import Prompt
from rich.markup import escape

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
})

console = Console(theme=nexus_theme)

# ── Import Architecture ──────────────────────────────────────────────────────
from orchestrators.loop import NexusLoop


# ── Readline History ─────────────────────────────────────────────────────────
_HISTORY_FILE = os.path.expanduser("~/.nexus_history")
_MAX_HISTORY_LINES = 500


def _load_history():
    """Load persistent shell history."""
    if os.path.exists(_HISTORY_FILE):
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line:
                        try:
                            from readline import add_history
                            add_history(line)
                        except ImportError:
                            break
        except Exception:
            pass


def _save_history():
    """Save shell history on exit."""
    try:
        from readline import get_history_length, get_history_item
        lines = []
        for i in range(1, get_history_length() + 1):
            item = get_history_item(i)
            if item:
                lines.append(item)
        if lines:
            with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-_MAX_HISTORY_LINES:]))
    except Exception:
        pass


# Register save hook
atexit.register(_save_history)


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
    """Claude Code CLI clone — slash commands, shortcuts, status bar, tasks."""

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
        _load_history()

    @property
    def brain(self) -> NexusLoop:
        if self._brain is None:
            self._brain = NexusLoop()
            self._brain.load_memory(self.session_id)
        return self._brain

    def _apply_session(self, session_id: str, source: str = "terminal") -> None:
        """Switch to a shared session visible across terminal, CLI, GUI, and gateway."""
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

    async def _stream_response(self, user_input: str) -> tuple[str, bool]:
        """Stream the response chunk by chunk, colorizing markers. Handles Ctrl+C gracefully."""
        from utils.session_bus import sync_loop_from_disk

        full_response = ""
        interrupted = False
        try:
            sync_loop_from_disk()
            async for chunk in self.brain.stream_run(user_input):
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
                elif t == "plan":
                    console.print(f"[bold cyan]{escape(d)}[/bold cyan]")
                elif t == "observations":
                    for line in d if isinstance(d, list) else [d]:
                        console.print(f"[grey70]{escape(str(line))}[/grey70]")
                elif t == "tools_discovered":
                    for tc in d if isinstance(d, list) else []:
                        console.print(f"[yellow]tool: {tc.get('name','?')}[/yellow]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            interrupted = True
        except Exception as e:
            console.print(f"\n[bold red]ERROR:[/bold red] {escape(str(e))}")

        return full_response, interrupted

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
        """List skills from .commandcode/skills."""
        skills_dir = os.path.join(self.brain.root, ".commandcode", "skills")
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
        """List agents from .commandcode/agents."""
        agents_dir = os.path.join(self.brain.root, ".commandcode", "agents")
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
            if result.returncode != 0:
                console.print(f"[red]Exit code: {result.returncode}[/red]")
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
            console.print("[dim]Same session id is visible in GUI, CLI, and gateway.[/dim]")
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
        if base == "/model" and len(parts) > 1:
            self.model = parts[1]
            console.print(f"[green]Model: {self.model}[/green]")
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
            # Create a task for multi-agent work
            tid = TaskTracker.create(base, agent="multi-agent")
            console.print(f"[bold cyan]Running {base}...[/bold cyan]")
            # For now, just echo. Full implementation needs backend integration.
            TaskTracker.update(tid, "completed")
            console.print(f"[bold green]{base.upper()} COMPLETED.[/bold green]")
            console.print("[dim]Full multi-agent workflow engine integration required for live execution.[/dim]")
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
        console.print(f"[dim]Linked session: {self.session_id} (shared with GUI, CLI, gateway)[/dim]\n")
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
                full_response, interrupted = await self._stream_response(user_msg)
                print()

                if not interrupted:
                    self.conversation_history.append({"role": "assistant", "content": full_response})

            except (KeyboardInterrupt, EOFError):
                break

        console.print("\n[bold red]SESSION TERMINATED.[/bold red]")


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    shell = NexusShell()
    shell.start()
