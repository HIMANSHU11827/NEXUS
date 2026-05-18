"""Terminal interface for the NEXUS local agent runtime."""

import os
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.theme import Theme
from rich.table import Table
from rich.prompt import Prompt
from rich.layout import Layout

# ── Custom Theme for NEXUS
nexus_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "nexus": "bold magenta",
    "user": "bold blue",
    "system": "italic grey50",
    "tool": "italic grey70"
})

console = Console(theme=nexus_theme)

# ── Import Assets
from assets import BANNER_PRO

# ── Import Architecture
from orchestrators.loop import NexusLoop

class C:
    BLUE = '\033[94m'
    GRAY = '\033[90m'
    RESET = '\033[0m'

class NexusPremiumShell:
    """Base class for all NEXUS Shells."""
    def __init__(self):
        self._brain = None
        self.is_running = False

    def _clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    @property
    def brain(self) -> NexusLoop:
        if self._brain is None:
            from orchestrators.loop import NexusLoop
            self._brain = NexusLoop()
        return self._brain

    def run_command(self, user_input: str):
        self.brain.sync_memory()
        print(f"\n[*] NEXUS is thinking...", flush=True)
        full_response = ""
        for chunk in self.brain.stream_run(user_input):
            if "[* Processing Tools...]" in chunk: continue
            full_response += chunk
            print(chunk, end="", flush=True)
        print("\n", flush=True)

class NexusSimpleShell(NexusPremiumShell):
    """The 'Neural Terminal' - High-speed, immersive, and data-rich."""
    
    def __init__(self):
        super().__init__()
        self.layout = Layout()
        self._setup_layout()
        self.conversation_history = []
        self._scripted_inputs = None
        self._scripted_index = 0

    def _setup_layout(self):
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )
        self.layout["main"].split_row(
            Layout(name="convo", ratio=4),
            Layout(name="stats", ratio=1)
        )

    def _get_header(self):
        return Panel(
            Text("NEXUS AI | LOCAL AGENT RUNTIME | OPERATOR DASHBOARD", justify="center", style="bold magenta"),
            style="magenta"
        )

    def _get_stats_panel(self):
        from core.kernel import get_nexus_kernel
        kernel = get_nexus_kernel()
        stats = kernel.get_stats()
        
        table = Table(show_header=False, box=None)
        table.add_row("STATUS", "[green]HEALTHY[/green]")
        table.add_row("BRAIN", f"[cyan]{self.brain.router.base_router.mode}[/cyan]")
        table.add_row("CPU", f"[yellow]{stats['load']['cpu']}[/yellow]")
        table.add_row("RAM", f"[yellow]{stats['load']['ram']}[/yellow]")
        table.add_row("UPTIME", f"{stats['uptime']}s")
        
        return Panel(table, title="[bold]TELEMETRY[/bold]", border_style="cyan")

    def _get_footer(self):
        return Panel(
            Text("exit: quit | clear: reset view", justify="center", style="system"),
            border_style="grey50",
        )

    def _get_convo_panel(self, current_chunk=""):
        history_text = ""
        for msg in self.conversation_history[-5:]: # Last 5
            role = "[bold magenta]NEXUS[/bold magenta]" if msg["role"] == "assistant" else "[bold blue]USER[/bold blue]"
            history_text += f"{role}: {msg['content']}\n\n"
        
        if current_chunk:
            history_text += f"[bold magenta]NEXUS[/bold magenta]: {current_chunk}"
            
        return Panel(
            history_text, 
            title="[bold]COGNITIVE_FEED[/bold]", 
            border_style="magenta",
            padding=(1, 2)
        )

    def _show_banner(self):
        console.clear()
        console.print(BANNER_PRO)
        console.print("\n[bold cyan]SYSTEM READY.[/bold cyan] Type [bold red]'exit'[/bold red] to terminate session.\n")

    def _read_user_input(self) -> str:
        if sys.stdin.isatty():
            return Prompt.ask("[bold blue]nexus[/bold blue]")
        if self._scripted_inputs is None:
            self._scripted_inputs = [line.rstrip("\r\n") for line in sys.stdin.readlines()]
        print("nexus: ", end="", flush=True)
        if self._scripted_index >= len(self._scripted_inputs):
            raise EOFError
        line = self._scripted_inputs[self._scripted_index]
        self._scripted_index += 1
        return line

    def start(self):
        self._show_banner()
        self.is_running = True
        while self.is_running:
            try:
                user_msg = self._read_user_input()
                if user_msg.lower() in ["exit", "/exit", "quit", "clear"]:
                    if user_msg.lower() == "clear": self._show_banner(); continue
                    break
                
                if not user_msg: continue
                
                self.conversation_history.append({"role": "user", "content": user_msg})
                
                # Live streaming
                with Live(self.layout, refresh_per_second=10, screen=False) as live:
                    self.layout["header"].update(self._get_header())
                    self.layout["footer"].update(self._get_footer())
                    self.layout["stats"].update(self._get_stats_panel())
                    
                    full_response = ""
                    for chunk in self.brain.stream_run(user_msg):
                        if "[* Processing Tools...]" in chunk: continue
                        full_response += chunk
                        self.layout["convo"].update(self._get_convo_panel(full_response))
                        self.layout["stats"].update(self._get_stats_panel()) # Dynamic update

                self.conversation_history.append({"role": "assistant", "content": full_response})
                print("\n") # Reset console position after Live

            except (KeyboardInterrupt, EOFError): break
        console.print("\n[bold red]SESSION TERMINATED.[/bold red]")
