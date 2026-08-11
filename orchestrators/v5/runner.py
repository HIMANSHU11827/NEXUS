"""NEXUS V5 Shell — Full-observability Rich REPL.

Shows: perception, planning, tools+params+results, skills, memory,
verification, timing. /verbose toggles detail. Uses unified registry.
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

from nexus.commands import CommandContext, get_registry

console = Console()
_verbose = os.environ.get("NEXUS_V5_VERBOSE", "").lower() in ("1", "true", "yes")

I = {
    "plan": "\U0001f4cb", "tool": "\U0001f527", "search": "\U0001f50d",
    "cmd": "\u2699\ufe0f", "file": "\U0001f4c4", "skill": "\U0001f9e0",
    "hive": "\U0001f41d", "rag": "\U0001f4d6", "ok": "\u2705",
    "err": "\u274c", "run": "\u23f3", "verify": "\U0001f50d",
}
SEP = "\u2500" * 60
BANNER = """[bold cyan]
   N E X U S   V 5   —   Quantum Loop Shell
[/bold cyan][dim]See every decision, tool, plan — /verbose for detail[/dim]"""


def _make_sink(verbose: bool):
    """Rich sink showing everything Nexus does: phases, plans, tools, verify."""
    _starts: dict = {}

    def fn(payload):
        if not isinstance(payload, dict): return
        kind = payload.get("kind") or payload.get("type") or ""
        status = payload.get("status") or ""
        etype = payload.get("event_type") or ""
        title = payload.get("title") or payload.get("action") or ""
        tool = payload.get("tool") or payload.get("name") or ""
        target = str(payload.get("target") or "")[:60]
        result = str(payload.get("result") or payload.get("output") or "")[:200]
        params = payload.get("payload") or {}
        error = payload.get("error") or ""

        if kind == "phase" or etype.startswith("phase."):
            ph = title or etype
            if ph: console.print(f"\n  {I['run']} [bold yellow]{ph.upper()}[/bold yellow]")

        if etype.startswith("plan.") or kind == "plan":
            if status == "running":
                console.print(f"  {I['plan']} [cyan]Planning…[/cyan]")
            elif status == "done":
                steps = params.get("steps", [])
                n = len(steps) if isinstance(steps, list) else 0
                console.print(f"  {I['plan']} [green]Plan: {n} steps[/green]")
                if verbose and isinstance(steps, list):
                    for i, s in enumerate(steps[:5]):
                        d = str(s.get("description", s.get("tool", "?")))[:60]
                        console.print(f"     [dim]{i+1}. {d}[/dim]")

        if "perceiv" in etype.lower() or kind == "rag":
            src = payload.get("source", target) or target
            if status == "done" and src:
                console.print(f"  {I['ok']} [dim]Loaded {src}[/dim]")

        if kind == "skill" or etype.startswith("skill."):
            sn = payload.get("name", tool) or target
            if status in ("done", "activated"):
                console.print(f"  {I['skill']} [magenta]Skill: /{sn}[/magenta]")

        if tool:
            if status in ("running", "queued"):
                _starts[tool] = time.time()
                act = title or ""
                if verbose and params:
                    act = "  ".join(f"[dim]{k}=[/dim]{str(v)[:30]}" for k, v in list(params.items())[:3])
                console.print(f"  {I.get(kind, I['tool'])} [yellow]{tool}[/yellow] {act}")
            elif status in ("done", "completed"):
                t = _starts.pop(tool, 0)
                et = f" [dim]({time.time()-t:.1f}s)[/dim]" if t else ""
                ec = payload.get("exit_code")
                ok = ec is None or ec == 0
                ic = I["ok"] if ok else I["err"]
                clr = "green" if ok else "red"
                console.print(f"     {ic} [{clr}]{tool}[/{clr}]{et}")
                if verbose and result:
                    console.print(f"     [dim]{result[:120]}[/dim]")

        if "verif" in etype.lower():
            if status == "done":
                console.print(f"  {I['verify']} [green]Verified[/green]")
            elif status == "failed":
                console.print(f"  {I['err']} [red]Verify failed[/red]")

    return fn


def _show_help(registry):
    for cat in registry.categories():
        cmds = registry.list(cat)
        t = Table(title=f"[bold]{cat.upper()}[/bold]", box=box.ROUNDED, border_style="cyan")
        t.add_column("Command", style="bold green"); t.add_column("Description", style="dim")
        for c in cmds:
            a = f" ({', '.join(c.aliases)})" if c.aliases else ""
            t.add_row(f"/{c.name}{a}", c.description)
        console.print(t)
    console.print("[dim]/verbose — toggle detail | Anything else → V5 engine[/dim]")


async def _run_turn(loop, text, verbose=False):
    start = time.time()
    console.print(f"\n{SEP}\n[bold cyan]You:[/bold cyan] {text[:200]}\n[dim]Nexus:[/dim]")
    async for ch in loop.stream_run(text):
        ct = ch.get("type") if isinstance(ch, dict) else None
        if ct == "content":
            console.print(str(ch.get("data", "")), end="", highlight=False)
        elif ct == "done":
            d = ch.get("data", {})
            ok = d.get("success", True) if isinstance(d, dict) else True
            console.print(f"\n[dim]{I['ok'] if ok else I['err']} Done ({time.time()-start:.1f}s)[/dim]\n{SEP}")
            return
    console.print(f"\n{SEP}")


async def run_v5_repl(root_dir: str):
    global _verbose
    try:
        from orchestrators.v5.core import NexusLoopV5
    except Exception as e:
        console.print(f"[red]Load: {e}[/red]"); return
    console.print(BANNER)
    try:
        loop = NexusLoopV5(root_dir, session_id="default")
    except Exception as e:
        console.print(f"[red]Init: {e}[/red]"); return
    loop.set_work_event_sink(_make_sink(_verbose))
    reg = get_registry()
    k_ok = getattr(loop, "kernel", None) is not None
    console.print(f"[{'green' if k_ok else 'yellow'}]Kernel: {'connected' if k_ok else 'standalone'}[/]  "
                  f"Session: [bold]{loop.session_id}[/bold]  "
                  f"Commands: [bold]{len(reg.list())}[/bold]  "
                  f"Verbose: [bold]{'ON' if _verbose else 'OFF'}[/bold]")
    console.print(SEP)
    while True:
        try:
            ui = await asyncio.to_thread(console.input, Text("nexus> ", style="bold cyan"))
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]"); break
        ui = (ui or "").strip()
        if not ui: continue
        if ui.startswith("/"):
            parts = ui.split(maxsplit=1); cn = parts[0].lstrip("/").lower()
            if cn in ("quit", "exit"): console.print("[dim]Bye.[/dim]"); break
            if cn == "help": _show_help(reg); continue
            if cn == "verbose":
                _verbose = not _verbose
                loop.set_work_event_sink(_make_sink(_verbose))
                console.print(f"Verbose: [bold]{'ON' if _verbose else 'OFF'}[/bold]")
                continue
            cmd = reg.get(cn)
            if cmd:
                ctx = CommandContext(session_id=loop.session_id, loop=loop,
                    extra={"args": parts[1] if len(parts) > 1 else ""})
                try:
                    r = await cmd.execute(ctx)
                    if r.formatted: console.print(r.formatted)
                    elif r.output: console.print(r.output)
                    if r.error: console.print(f"[red]{r.error}[/red]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                continue
        try:
            await _run_turn(loop, ui, _verbose)
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            if os.environ.get("NEXUS_V5_DEBUG"): traceback.print_exc()
    if hasattr(loop, "save_memory"):
        try: loop.save_memory()
        except Exception: pass
