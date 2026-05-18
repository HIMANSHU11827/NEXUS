"""
NEXUS boot loader.
Entry point for the local-first agent runtime.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time
import logging

logging.getLogger().setLevel(logging.ERROR)
for _logger in ["NEXUS_KERNEL", "NEXUS_LOCAL_BRAIN", "NEXUS_ROUTER", "unified_loop"]:
    logging.getLogger(_logger).setLevel(logging.ERROR)
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

from rich.console import Console

console = Console()

def boot():
    argv = sys.argv
    is_cli = len(argv) > 1

    if not is_cli:
        print("--- NEXUS AI: local agent runtime booting ---", flush=True)
        print("[SYSTEM]: Direct tools, memory, routing, and verification enabled.", flush=True)

    _root = os.path.dirname(os.path.abspath(__file__))

    from orchestrators.loop import NexusLoop
    from shell import NexusSimpleShell
    
    # Optional TypeScript/Ink interface.
    use_ink = "--ink" in argv or "--ts" in argv or "--cli" in argv

    if use_ink:
        print("[SYSTEM]: Launching High-Fidelity TypeScript/Ink Interface...", flush=True)
        import subprocess
        cli_dir = os.path.join(_root, "cli")
        try:
            # Check if node_modules exists, if not, hint to user
            if not os.path.exists(os.path.join(cli_dir, "node_modules")):
                print("[WARNING]: node_modules not found in 'cli/' directory. Falling back to Simple CLI...")
                shell = NexusSimpleShell()
            else:
                subprocess.run(["npm", "start"], cwd=cli_dir, shell=True)
                return
        except Exception as e:
            print(f"[SYSTEM_ERROR]: Failed to launch Ink CLI: {e}")
            print("[SYSTEM]: Falling back to Simple CLI...")
            shell = NexusSimpleShell()
    else:
        # Default to Simple CLI as requested
        shell = NexusSimpleShell()
    
    shell.start()


if __name__ == "__main__":
    boot()
