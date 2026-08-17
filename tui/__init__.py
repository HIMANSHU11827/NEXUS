"""Compatibility shell for the historical ``python -m nexus --shell`` path.

The Ink TUI is the primary interface, but keeping this small adapter avoids
breaking scripts and integrations that import the old Rich shell API.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from typing import Any

from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.table import Table

console = Console()


class TaskTracker:
    _tasks: list[dict[str, Any]] = []

    @classmethod
    def create(cls, prompt: str) -> str:
        task_id = str(uuid.uuid4())
        cls._tasks.append({"id": task_id, "prompt": prompt, "status": "running"})
        return task_id

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return list(cls._tasks)


class NexusShell:
    def __init__(self, brain: Any | None = None) -> None:
        self._brain = brain
        self.session_id = "default"
        self.conversation_history: list[dict[str, str]] = []
        self.mode = "auto"
        self._pending_agent_prompt: str | None = None
        self._pending_task_id: str | None = None

    def _run_bash(self, command: str) -> int:
        console.print(f"Command started: {command}")
        root = getattr(self._brain, "root", os.getcwd())
        from sandbox.risk import CommandRiskScorer

        assessment = CommandRiskScorer().assess(command)
        if assessment.blocked:
            console.print(f"Command blocked: {assessment.summary()}", style="red")
            return 1
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                shell=True,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            console.print("Command timed out after 120s", style="red")
            return 1
        except OSError as exc:
            console.print(f"Command failed to start: {exc}")
            return 1
        if completed.stdout:
            console.print(completed.stdout.rstrip())
        if completed.stderr:
            console.print(completed.stderr.rstrip(), style="red")
        console.print(f"Command completed · exit code {completed.returncode}")
        return completed.returncode

    def _handle_slash(self, value: str) -> bool:
        from nexus.commands import CommandContext, get_registry

        parts = value.strip().split(maxsplit=1)
        command = get_registry().get(parts[0] if parts else "")
        if command is None or command.execution != "shared":
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return False
        try:
            result = asyncio.run(command.execute(CommandContext(
                session_id=self.session_id,
                shell=self,
                extra={"args": value, "command": parts[0] if parts else ""},
            )))
        except RuntimeError:
            return False
        if not result.success:
            console.print(result.error or result.output, style="red")
            return True
        console.print(result.output or result.formatted)
        return True

    @staticmethod
    def _render_event(event: dict[str, Any]) -> None:
        visibility = event.get("visibility") or event.get("payload", {}).get("visibility")
        if visibility == "internal":
            return
        related = event.get("related_command") or event.get("target")
        if related:
            console.print(f"$ {related}")
        details = []
        if event.get("status"):
            details.append(str(event["status"]))
        if event.get("exit_code") is not None:
            details.append(f"exit {event['exit_code']}")
        if event.get("duration_ms") is not None:
            details.append(f"{event['duration_ms']}ms")
        if details:
            console.print(" · ".join(details))

    async def _stream_response(self, prompt: str):
        text_parts: list[str] = []
        interrupted = False
        files: list[Any] = []
        tools: list[Any] = []
        if self._brain is None:
            return "", False, files, tools
        try:
            async for item in self._brain.stream_run(prompt):
                kind = item.get("type") if isinstance(item, dict) else None
                if kind == "content":
                    text_parts.append(str(item.get("data", "")))
                elif kind == "status":
                    console.print(str(item.get("data", "")).strip("[]"))
                elif kind == "tools_discovered":
                    tools.extend(item.get("tool_calls", []))
                    console.print("Tools:")
                    for call in item.get("tool_calls", []):
                        name = call.get("name", "tool")
                        command = call.get("arguments", {}).get("command")
                        console.print(f"- {name}" + (f": {command}" if command else ""))
                elif kind == "work_event":
                    event = item.get("event", item)
                    if isinstance(event, dict):
                        self._render_event(event)
                elif kind == "file":
                    files.append(item)
                elif kind == "error":
                    console.print(str(item.get("data", "")), style="red")
        except (asyncio.CancelledError, KeyboardInterrupt):
            interrupted = True
        return "".join(text_parts), interrupted, files, tools


    # Display Methods (called by nexus/commands.py handlers)

    def _show_skills(self):
        try:
            from skills.engine import NexusSkillEngine
            e = NexusSkillEngine(); skills = e.list_skills()
        except ImportError:
            try:
                from skills import NexusSkillMaster
                e = NexusSkillMaster(); skills = e.list_skills()
            except Exception as ex:
                console.print(f"[red]Skills unavailable: {ex}[/red]"); return
        if not skills: console.print("[yellow]No skills installed.[/yellow]"); return
        t = Table(title="NEXUS Skills", box=box.ROUNDED)
        t.add_column("Name", style="cyan"); t.add_column("Category", style="green")
        t.add_column("Mode", style="magenta"); t.add_column("Status")
        t.add_column("Description", style="dim")
        for s in skills:
            n = s.get("name", "?"); c = s.get("category", "general")
            m = s.get("mode", "inject"); a = "ACTIVE" if s.get("active") else "DISABLED"
            d = (s.get("description", "") or "")[:60]
            st = "green" if s.get("active") else "red"
            t.add_row(f"/{n}", c, m, f"[{st}]{a}[/{st}]", d)
        console.print(t)
        console.print(f"[dim]{len(skills)} skills[/dim]")

    def _show_tools(self):
        try:
            import tools
            reg = tools.ToolRegistry() if hasattr(tools, 'ToolRegistry') else None
            tl = reg.list_tools() if reg else {}
        except Exception:
            console.print("[yellow]Tool registry not available.[/yellow]"); return
        if not tl: console.print("[dim]No tools registered.[/dim]"); return
        t = Table(title="Tools", box=box.ROUNDED)
        t.add_column("Name", style="cyan"); t.add_column("Description", style="dim")
        for n, m in (tl.items() if isinstance(tl, dict) else []):
            t.add_row(n, str(m)[:60])
        console.print(t)

    def _show_agents(self):
        try:
            from hive import NexusHiveEngine
            h = NexusHiveEngine(); agents = h.list_agents()
        except Exception:
            console.print("[yellow]Hive unavailable.[/yellow]"); return
        if not agents: console.print("[dim]No active agents.[/dim]"); return
        t = Table(title="Hive Agents", box=box.ROUNDED)
        t.add_column("ID", style="cyan"); t.add_column("Persona", style="green")
        t.add_column("Status"); t.add_column("Task", style="dim")
        for a in agents:
            t.add_row(getattr(a, "agent_id", "?")[:12], getattr(a, "persona", "?"),
                      getattr(a, "status", "?"), getattr(a, "task", "")[:50])
        console.print(t)

    def _show_plugins(self):
        try:
            from plugins import PluginManager
            pm = PluginManager(); pl = getattr(pm, "_plugins", {})
        except Exception:
            console.print("[yellow]Plugins unavailable.[/yellow]"); return
        if not pl: console.print("[dim]No plugins loaded.[/dim]"); return
        t = Table(title="Plugins", box=box.ROUNDED)
        t.add_column("Name", style="cyan"); t.add_column("Version")
        for n, p in pl.items():
            t.add_row(n, str(getattr(p, "version", "?")))
        console.print(t)


    def _show_forge_status(self):
        lines = ["[bold]Forge Status[/bold]", ""]
        try:
            from evolution.skill_forge.scripts.forge import SkillForge
            SkillForge("."); lines.append("[green]Skill Forge: Active[/green]")
        except: lines.append("[dim]Skill Forge: idle[/dim]")
        try:
            from evolution.tool_forge.scripts.engine import ToolForge
            lines.append("[green]Tool Forge: Active[/green]")
        except: lines.append("[dim]Tool Forge: idle[/dim]")
        console.print(Panel("\n".join(lines), title="Forge", border_style="blue"))

    def _show_provider_dashboard(self):
        try:
            from configure.profiles import NexusProfiles
            p = NexusProfiles(); providers = getattr(p, "_profiles", {})
        except: providers = {}
        if not providers:
            console.print("[yellow]No providers configured.[/yellow]"); return
        t = Table(title="Providers", box=box.ROUNDED)
        t.add_column("Provider", style="cyan"); t.add_column("Model", style="green")
        for n, c in providers.items():
            m = c.get("model", "?") if isinstance(c, dict) else str(c)
            t.add_row(n, str(m))
        console.print(t)

    def _show_agent_monitor(self):
        lines = []
        try:
            from skills.engine import NexusSkillEngine
            e = NexusSkillEngine(); h = e.health_report()
            lines.append(f"Skills: {h['total_skills']} total, {h['active_skills']} active")
        except: lines.append("[dim]Skill health unavailable[/dim]")
        console.print(Panel("\n".join(lines), title="Monitor", border_style="green"))

    def _show_work_events(self):
        d = os.path.join(os.getcwd(), "workspace", "work_events")
        if not os.path.isdir(d):
            console.print("[dim]No work events recorded.[/dim]"); return
        fs = sorted([f for f in os.listdir(d) if f.endswith(".jsonl")],
                     key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)[:1]
        if not fs: console.print("[dim]No event files.[/dim]"); return
        evs = []
        try:
            with open(os.path.join(d, fs[0]), "r", encoding="utf-8") as f:
                for line in f:
                    try: evs.append(json.loads(line))
                    except: pass
        except: console.print("[red]Failed to read events.[/red]"); return
        rec = evs[-15:]
        t = Table(title=f"Events ({fs[0]})", box=box.ROUNDED)
        t.add_column("Type", style="cyan"); t.add_column("Status")
        t.add_column("Title", style="dim")
        for ev in rec:
            t.add_row(ev.get("event_type", "?"), str(ev.get("status", "")),
                      str(ev.get("title", ""))[:50])
        console.print(t)

    def _show_system_map(self):
        lines = ["[bold]NEXUS System Map[/bold]", ""]
        try:
            from skills.engine import NexusSkillEngine
            e = NexusSkillEngine(); h = e.health_report()
            lines.append(f"[cyan]Skills:[/cyan] {h['total_skills']} loaded, {h['active_skills']} active")
        except: lines.append("[cyan]Skills:[/cyan] [dim]unavailable[/dim]")
        try:
            from hive import NexusHiveEngine
            a = NexusHiveEngine().list_agents()
            lines.append(f"[cyan]Hive:[/cyan] {len(a)} agents")
        except: lines.append("[cyan]Hive:[/cyan] [dim]idle[/dim]")
        try:
            from permissions import PermissionSystem
            lines.append(f"[cyan]Permissions:[/cyan] {PermissionSystem().mode}")
        except: pass
        console.print(Panel("\n".join(lines), title="System", border_style="cyan"))


__all__ = ["NexusShell", "TaskTracker", "console"]
