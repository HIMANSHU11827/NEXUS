"""
NEXUS boot loader.
Entry point for the local-first agent runtime.
"""

import os
import sys

from dotenv import load_dotenv
# Load .env file from the config directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env"))

_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

if os.name == "nt":
    _project_root = os.path.dirname(_root)
    _venv_scripts = os.path.abspath(os.path.join(_project_root, ".venv", "Scripts"))
    if os.path.exists(_venv_scripts):
        try:
            os.add_dll_directory(_venv_scripts)
            import sqlite3
        except Exception:
            pass

# CRITICAL FIX: PYTHONHOME env var from uv breaks Python 3.14
# It points to a broken uv-managed Python 3.11 with "SRE module mismatch"
os.environ.pop("PYTHONHOME", None)

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
    _root = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_root)

    # Use --shell or --python to explicitly launch the Python shell instead
    if "--shell" in argv or "--python" in argv:
        import asyncio
        from shell import NexusShell
        shell = NexusShell()
        asyncio.run(shell.start())
        return

    print("--- NEXUS AI: launching CLI ---", flush=True)

    import subprocess
    import time
    import urllib.request
    import re

    # Clean up any stale process listening on port 8000 to avoid binding conflict
    if os.name == "nt":
        try:
            output = subprocess.check_output("netstat -ano", shell=True, text=True)
            for line in output.splitlines():
                if ":8000 " in line and "LISTENING" in line:
                    match = re.search(r"\s+(\d+)\s*$", line)
                    if match:
                        pid = match.group(1)
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        try:
            subprocess.run("fuser -k 8000/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    cli_dir = os.path.join(_project_root, "cli")

    # Start API server in background
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        cwd=_project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready (up to 15s)
    server_ready = False
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/health")
            server_ready = True
            break
        except Exception:
            time.sleep(0.5)

    if not server_ready:
        print("[ERROR]: API server failed to start on port 8000", flush=True)
        server_proc.terminate()
        server_proc.wait()
        sys.exit(1)

    try:
        if not os.path.exists(os.path.join(cli_dir, "node_modules")):
            print("[SETUP]: Installing CLI dependencies...", flush=True)
            subprocess.run(["npm", "install"], cwd=cli_dir, shell=True, check=True)
        subprocess.run(["npm", "start"], cwd=cli_dir, shell=True)
    finally:
        server_proc.terminate()
        server_proc.wait()


if __name__ == "__main__":
    boot()
