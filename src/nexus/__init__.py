"""
NEXUS AI — Boot loader.
Entry point for the local-first autonomous agent runtime.
"""

import argparse
import asyncio
import logging
import os
import secrets
import shutil
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("nexus")

try:
    from importlib.metadata import version as _v
    __version__ = _v("nexus-ai")
except Exception:
    __version__ = "2.0.0"

BANNER = """
[bold cyan]    ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
    ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
    ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
    ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
    ██║ ╚████║██████╗██╔╝ ██╗╚██████╔╝███████║
    ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝[/bold cyan]
"""


def _resolve_root() -> str:
    root_env = os.environ.get("NEXUS_ROOT")
    if root_env and os.path.isdir(os.path.join(root_env, "src")):
        _project = root_env
    else:
        _root = os.path.dirname(os.path.abspath(__file__))  # .../src/nexus
        _src = os.path.dirname(_root)  # .../src
        _project = os.path.dirname(_src)  # repository root
        if not os.path.exists(os.path.join(_project, "nexus.config.json")):
            _project = os.getcwd()
            _src = os.path.join(_project, "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
    # Project root first (config files, apps/, extensions/, ...), then src/ for
    # the nexus.* namespace. No top-level `nexus` dir exists at the repo root,
    # so nothing is shadowed.
    if sys.path and sys.path[0] != _project:
        sys.path.insert(0, _project)
    if _project not in sys.path:
        sys.path.insert(0, _project)
    return _project


def _setup_environment() -> str:
    project_root = _resolve_root()

    # Support both the legacy config/.env and the repository-root .env while
    # allowing explicitly injected process settings to win.
    load_dotenv(os.path.join(project_root, ".env"), override=False)
    load_dotenv(os.path.join(project_root, "configure", ".env"), override=False)

    if os.name == "nt":
        venv_scripts = os.path.join(project_root, ".venv", "Scripts")
        if os.path.exists(venv_scripts):
            try:
                os.add_dll_directory(venv_scripts)
                import sqlite3
            except Exception:
                logger.warning("DLL setup failed", exc_info=True)

    os.environ.pop("PYTHONHOME", None)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logging.getLogger().setLevel(logging.ERROR)
    for name in ["NEXUS_KERNEL", "NEXUS_LOCAL_BRAIN", "NEXUS_ROUTER", "unified_loop"]:
        logging.getLogger(name).setLevel(logging.ERROR)
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    return project_root


def _check_first_run(project_root: str) -> bool:
    setup_complete = os.path.join(project_root, "configure", ".setup_complete")
    if os.path.exists(setup_complete):
        return False

    first_run_flag = os.path.join(project_root, "configure", ".first_run")
    if os.path.exists(first_run_flag):
        return True

    env_path = os.path.join(project_root, "configure", ".env")
    if not os.path.exists(env_path):
        return True
    try:
        with open(env_path, encoding="utf-8") as f:
            content = f.read()
        placeholders = ["your_", "= ", "=,"]
        return any(p in content for p in placeholders) or not content.strip()
    except Exception:
        return True


def _mark_setup_complete(project_root: str, mode: str = "manual") -> None:
    import json
    config_dir = os.path.join(project_root, "configure")
    os.makedirs(config_dir, exist_ok=True)
    first_run_flag = os.path.join(config_dir, ".first_run")
    complete_path = os.path.join(config_dir, ".setup_complete")
    payload = {
        "mode": mode,
        "version": __version__,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(complete_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    try:
        if os.path.exists(first_run_flag):
            os.remove(first_run_flag)
    except Exception:
        logger.warning("Failed to remove first-run flag", exc_info=True)


def _quick_configure(project_root: str) -> None:
    from apps.tui.setup_wizard import (
        load_env,
        load_provider_yml,
        save_env,
        save_provider_yml,
    )

    config_dir = os.path.join(project_root, "configure")
    os.makedirs(config_dir, exist_ok=True)

    env = load_env(project_root)
    env.setdefault("NEXUS_SANDBOX_TIER", "normal")
    save_env(project_root, env)

    cfg = load_provider_yml(project_root)
    cfg.setdefault("version", "1.1.0")
    cfg.setdefault("default_provider", "ollama")
    providers = cfg.setdefault("providers", {})
    providers.setdefault("ollama", {
        "model": "llama3",
        "endpoint": "http://127.0.0.1:11434/api/chat",
        "temperature": 0.7,
        "max_tokens": 4096,
    })
    fallback = cfg.setdefault("fallback_chain", [])
    if "ollama" not in fallback:
        fallback.insert(0, "ollama")
    save_provider_yml(project_root, cfg)

    settings_path = os.path.join(config_dir, "settings.yml")
    if not os.path.exists(settings_path):
        import yaml
        settings = {
            "temperature": 0.7,
            "max_tokens": 4096,
            "max_turns": 10,
            "permission_mode": "auto",
            "auto_save": True,
            "thinking_mode": True,
            "log_level": "INFO",
            "language": "en",
            "sandbox_tier": "normal",
            "theme": {
                "name": "dark",
                "primary": "bold magenta",
                "accent": "bold cyan",
                "success": "bold green",
                "panel_border": "cyan",
            },
        }
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.dump(settings, f, default_flow_style=False, sort_keys=False)

    _mark_setup_complete(project_root, "quick")


def _apply_command_alias(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    invoked_as = Path(argv[0]).stem.lower()
    command_aliases = {
        "nexus-tui": "--tui",
        "nexus-shell": "--shell",
        "nexus-gui": "--gui",
        "nexus-server": "--server",
        "nexus-api": "--server",
        "nexus-gateway": "--gateway",
        "nexus-v5": "--v5",
        "nexus-setup": "--setup",
        "nexus-configure": "--setup",
        "nexus-config": "--setup",
        "nexus-settings": "--setup",
        "nexus-quick": "--quick",
        "nexus-reset": "--reset",
        "nexus-export": "--export",
        "nexus-export-full": "--export-full",
        "nexus-import": "--import",
        "nexus-import-full": "--import-full",
    }
    special_aliases = {
        "nexus-version": "--version",
        "nexus-help": "--help",
    }
    flag = command_aliases.get(invoked_as) or special_aliases.get(invoked_as)
    if not flag or flag in argv[1:]:
        return argv
    return [argv[0], flag, *argv[1:]]


async def _wait_for_health(url: str, timeout: float = 15.0, label: str = "service") -> bool:
    import httpx
    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task(f"[cyan]Waiting for {label}...", total=None)
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            while time.monotonic() - start < timeout:
                try:
                    r = await client.get(url, timeout=2.0)
                    if r.status_code < 500:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            return False


def _make_parser() -> argparse.ArgumentParser:
    prog = os.path.basename(sys.argv[0]) if sys.argv[0] and sys.argv[0] != "-m" else "python -m nexus"
    p = argparse.ArgumentParser(
        prog=prog,
        description="NEXUS AI - Local-first autonomous agent runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m nexus                    Start TUI (default)
  nexus                              Start TUI (default)
  nexus-tui                          Start TUI
  nexus-gui                          Start GUI + backend
  nexus-server                       Start API server only
  nexus-gateway                      Start gateway
  nexus-setup                        Run setup wizard
  nexus-configure                    Run setup wizard
  python -m nexus --gui              Start GUI + backend
  python -m nexus --server           Start API server only
  python -m nexus --gateway          Start gateway
  python -m nexus --v5               Start the V5 engine REPL
  python -m nexus --setup            Run setup wizard
  python -m nexus --quick            Quick start (skip wizard)
  python -m nexus --reset            Factory reset + setup wizard
  python -m nexus --export cfg.zip   Export config only
  python -m nexus --export-full bak.zip  Export everything
  python -m nexus --import cfg.zip   Import config
  python -m nexus --import-full bak.zip  Import full system backup
  python -m nexus --version          Show version""",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--tui", action="store_true", help="Start TUI (default)")
    group.add_argument("--shell", action="store_true", help="Start the compatibility shell (falls back to Ink TUI when legacy shell is unavailable)")
    group.add_argument("--gui", action="store_true", help="Start GUI + backend")
    group.add_argument("--server", action="store_true", help="Start API server only")
    group.add_argument("--supervise", action="store_true", help="Run the API under a durable crash/restart supervisor")
    group.add_argument("--gateway", action="store_true", help="Start gateway")
    group.add_argument("--v5", action="store_true", help="Start the V5 engine (interactive REPL)")
    group.add_argument("--autonomous", action="store_true", help="Start the 24/7 durable task-queue driver (pulls tasks and runs them forever)")
    group.add_argument("--mission", type=str, metavar="GOAL", help="Start a 24/7 long-horizon mission for GOAL (decomposed into milestones, run until done, survives restart)")
    group.add_argument("--setup", action="store_true", help="Run setup wizard")
    group.add_argument("--quick", action="store_true", help="Quick start with defaults")
    group.add_argument("--reset", action="store_true", help="Reset config to factory defaults")
    group.add_argument("--export", type=str, metavar="PATH", help="Export config to a zip file")
    group.add_argument("--export-full", type=str, metavar="PATH", help="Export everything (config+memory+knowledge+workspace+logs+auth)")
    group.add_argument("--import", dest="import_path", type=str, metavar="PATH", help="Import config from a zip file")
    group.add_argument("--import-full", dest="import_full_path", type=str, metavar="PATH", help="Import full system backup")
    group.add_argument("--observe", nargs="?", const="default", metavar="SESSION", help="Stream public canonical events without starting GUI/TUI")
    p.add_argument("--version", "-v", action="store_true", help="Show version")
    p.add_argument("--after-sequence", type=int, default=0, help="Resume event observation after this sequence")
    p.add_argument("--observe-format", choices=("json", "text"), default="json", help="Observer output format")
    p.add_argument("--observe-once", action="store_true", help="Replay persisted events and exit")
    # Wire the `auth` subcommand tree (login/logout/add-key/list/set-default/...)
    # so `nexus auth login <provider>` actually reaches commands.auth handlers.
    try:
        from nexus.command_system.auth import init_auth_cli
        subparsers = p.add_subparsers(dest="command")
        init_auth_cli(subparsers)
    except Exception as exc:  # never break normal boot if auth wiring fails
        print(f"warning: auth CLI unavailable: {exc}")
    return p


def _print_banner(console):
    console.print(BANNER)
    console.print(f"  v{__version__} - python {sys.version_info.major}.{sys.version_info.minor}")
    console.print()


def _reset_config(project_root: str):
    config_dir = os.path.join(project_root, "configure")
    for fname in [".env", "provider.yml", "settings.yml", "system.yml"]:
        path = os.path.join(config_dir, fname)
        if os.path.exists(path):
            os.remove(path)
    for fname in [".env.template"]:
        src = os.path.join(config_dir, fname)
        if os.path.exists(src):
            import shutil
            dst = os.path.join(config_dir, ".env")
            shutil.copy2(src, dst)
    first_run_flag = os.path.join(config_dir, ".first_run")
    Path(first_run_flag).touch()


def _get_user_data_dirs(project_root: str):
    return {
        "configure": os.path.join(project_root, "configure"),
        "memory": os.path.join(project_root, "memory"),
        "knowledge": os.path.join(project_root, "knowledge"),
        "workspace": os.path.join(project_root, ".nexus", "workspace"),
        "logs": os.path.join(project_root, ".nexus", "logs"),
        "nexus_dotdir": os.path.join(project_root, ".nexus"),
        "opencode_memory": os.path.join(project_root, ".opencode", "memory"),
        "opencode_skills": os.path.join(project_root, ".opencode", "skills"),
        "evolution": os.path.join(project_root, "evolution", "memory_forge"),
        "rag": os.path.join(project_root, "knowledge", "rag", "atlas"),
    }


def _export_full_system(project_root: str, output_path: str):
    import json
    import zipfile
    dirs = _get_user_data_dirs(project_root)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, dirpath in dirs.items():
            if os.path.isdir(dirpath):
                for root, _dirs, files in os.walk(dirpath):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, project_root)
                        zf.write(fpath, arcname)
        global_auth = os.path.join(os.path.expanduser("~"), ".nexus", "auth")
        if os.path.isdir(global_auth):
            for root, _dirs, files in os.walk(global_auth):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.join("_global_auth", os.path.relpath(fpath, os.path.join(os.path.expanduser("~"), ".nexus")))
                    zf.write(fpath, arcname)
    meta = {"version": __version__, "exported_from": project_root, "type": "full-system"}
    with open(output_path + ".meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def _import_full_system(project_root: str, import_path: str):
    import zipfile
    with zipfile.ZipFile(import_path, "r") as zf:
        for member in zf.namelist():
            if member.startswith("_global_auth/"):
                target = os.path.join(os.path.expanduser("~"), ".nexus", os.path.relpath(member, "_global_auth"))
            else:
                target = os.path.join(project_root, member)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            zf.extract(member, os.path.dirname(target))


def _export_config(project_root: str, output_path: str):
    import json
    import zipfile
    config_dir = os.path.join(project_root, "configure")
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(config_dir):
            fpath = os.path.join(config_dir, fname)
            if os.path.isfile(fpath) and not fname.endswith(".lock"):
                zf.write(fpath, fname)
    meta = {"version": __version__, "exported_from": project_root}
    meta_path = output_path + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


def _import_config(project_root: str, import_path: str):
    import zipfile
    config_dir = os.path.join(project_root, "configure")
    with zipfile.ZipFile(import_path, "r") as zf:
        zf.extractall(config_dir)
    from apps.tui.setup_wizard import run
    run(project_root)


def _kill_windows_port(port: int) -> None:
    """Release a designated Nexus API/GUI port on every supported platform.

    The historical name is retained for compatibility with launcher tests and
    callers, but stale-port cleanup is no longer Windows-only. Only processes
    whose command line looks like the Nexus API or GUI toolchain are touched;
    unrelated services listening on the same port are left alone.
    """
    try:
        import psutil

        markers = (
            ("uvicorn", "server", "nexus")
            if port == 8000
            else ("vite", "npm", "node", "nexus", "gui")
        )
        processes = {}
        for connection in psutil.net_connections(kind="tcp"):
            address = connection.laddr
            if connection.status != psutil.CONN_LISTEN or not address or address.port != port:
                continue
            if not connection.pid:
                continue
            try:
                process = psutil.Process(connection.pid)
                command_line = " ".join(process.cmdline()).lower()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
            if any(marker in command_line for marker in markers):
                processes[process.pid] = process

        for process in processes.values():
            descendants = process.children(recursive=True)
            for child in reversed(descendants):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    pass
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass

        if processes:
            gone, alive = psutil.wait_procs(list(processes.values()), timeout=3.0)
            for process in alive:
                try:
                    process.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    pass
    except Exception:
        logger.warning("Failed to clear port %s", port, exc_info=True)


def _server_process_group_kwargs() -> dict:
    """Give the launcher ownership of the API process tree it starts."""
    import subprocess

    if os.name == "nt":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200),
        }
    return {"start_new_session": True}


def _terminate_server_process(proc) -> None:
    """Terminate and reap the API child and any launcher-owned descendants."""
    if proc is None:
        return
    import subprocess

    try:
        running = proc.poll() is None
    except Exception:
        running = True
    if running:
        pid = getattr(proc, "pid", None)
        tree_stopped = False
        try:
            if pid and os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                )
                tree_stopped = result.returncode == 0
            elif pid:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
                tree_stopped = True
        except (OSError, subprocess.SubprocessError, ValueError):
            logger.debug("API process-tree termination unavailable", exc_info=True)
        if not tree_stopped:
            try:
                proc.terminate()
            except (OSError, ProcessLookupError):
                pass
    try:
        proc.wait(timeout=5.0)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        logger.debug("API process reap failed", exc_info=True)


def _run_owned_foreground_process(command, cwd: str, *, env=None) -> int:
    """Run an interactive child while retaining ownership of its process tree."""
    import subprocess

    kwargs = {
        "cwd": cwd,
        **_server_process_group_kwargs(),
    }
    if env is not None:
        kwargs["env"] = env
    proc = subprocess.Popen(command, **kwargs)
    try:
        return proc.wait()
    finally:
        if proc.poll() is None:
            _terminate_server_process(proc)


def _api_is_ready(token: str | None = None) -> bool:
    """Return whether the local API accepts the launcher credentials."""
    try:
        import httpx
        api_token = (token or os.environ.get("NEXUS_DASHBOARD_TOKEN", "")).strip()
        if not api_token:
            return False
        headers = {"Authorization": f"Bearer {api_token}"}
        health = httpx.get("http://127.0.0.1:8000/api/health", headers=headers, timeout=1.5)
        status = httpx.get("http://127.0.0.1:8000/api/status", headers=headers, timeout=1.5)
        # Voice is optional and can initialise after the API. Gate TUI startup
        # on the core server contract, not an optional peripheral service.
        return health.status_code == 200 and status.status_code == 200
    except Exception:
        return False


def _api_is_current(token: str | None = None) -> bool:
    """Distinguish the current server contract from an older stale process."""
    try:
        import httpx
        api_token = (token or os.environ.get("NEXUS_DASHBOARD_TOKEN", "")).strip()
        if not api_token:
            return False
        response = httpx.get(
            "http://127.0.0.1:8000/api/status",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=1.5,
        )
        payload = response.json() if response.status_code == 200 else {}
        return isinstance(payload, dict) and "provider_status" in payload
    except Exception:
        return False


def _port_is_listening(port: int) -> bool:
    """Small local probe used to avoid starting duplicate GUI processes."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _find_npm_executable() -> str | None:
    if os.name == "nt":
        return shutil.which("npm.cmd") or shutil.which("npm.exe") or shutil.which("npm")
    return shutil.which("npm")


def _find_tui_runner(tui_dir: str) -> list[str] | None:
    bin_dir = os.path.join(tui_dir, "node_modules", ".bin")
    local_tsx = os.path.join(bin_dir, "tsx.cmd" if os.name == "nt" else "tsx")
    if os.path.exists(local_tsx):
        return [local_tsx, "nexus-tui.tsx"]

    npx = shutil.which("npx.cmd") if os.name == "nt" else shutil.which("npx")
    if npx:
        return [npx, "tsx", "nexus-tui.tsx"]

    npm = _find_npm_executable()
    if npm:
        return [npm, "run", "start", "--silent"]

    return None


def _run_ink_tui(project_root: str, console, wait_for_api: bool = True) -> int:
    import subprocess

    # A console is only passed by boot(); console=None means a programmatic or
    # test-driven launch, which must skip the interactive-only checks and the
    # API-readiness wait instead of blocking.
    interactive = console is not None
    if console is None:
        from rich.console import Console
        console = Console()

    if interactive and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        console.print(
            "[yellow]NEXUS TUI needs an interactive terminal. Start `nexus` from "
            "PowerShell, Command Prompt, Windows Terminal, or a WSL shell.[/yellow]"
        )
        return 1

    tui_dir = os.path.join(project_root, "apps", "tui")
    tui_entry = os.path.join(tui_dir, "nexus-tui.tsx")
    if not os.path.exists(tui_entry):
        console.print("[red]Ink TUI not found.[/red]")
        return 1

    runner = _find_tui_runner(tui_dir)
    if not runner:
        console.print("[red]Node TUI runner not found.[/red]")
        return 1

    # The API requires an authenticated status request. Use a per-launch,
    # high-entropy local token and pass it to both child processes. This avoids
    # relying on a stale config token or the old, invalid short fallback.
    launch_env = os.environ.copy()
    api_token = secrets.token_urlsafe(32)
    launch_env["NEXUS_DASHBOARD_TOKEN"] = api_token

    backend_proc = None
    reuse_existing_api = os.environ.get("NEXUS_REUSE_API", "").lower() in {"1", "true", "yes", "on"}
    try:
        if not reuse_existing_api:
            _kill_windows_port(8000)
        if reuse_existing_api and _api_is_ready(api_token):
            backend_proc = None
        else:
            backend_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "apps.api:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=launch_env,
                **_server_process_group_kwargs(),
            )

            # Ink immediately requests a new session and panel state. Do not show a
            # blank, apparently broken TUI while its owned backend is still booting.
            # Only wait when launched interactively; headless/programmatic callers
            # (console=None or wait_for_api=False) must not block on readiness.
            if wait_for_api and interactive:
                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    if _api_is_ready(api_token):
                        break
                    if backend_proc.poll() is not None:
                        console.print("[red]NEXUS API exited before the TUI could start.[/red]")
                        return int(backend_proc.returncode or 1)
                    time.sleep(0.2)
                else:
                    console.print("[red]NEXUS API did not become ready within 30 seconds.[/red]")
                    return 1

        result = subprocess.run(runner, cwd=tui_dir, env=launch_env)
        return result.returncode
    finally:
        if backend_proc:
            _terminate_server_process(backend_proc)


def _run_rich_shell() -> int:
    """Launch the V5 Rich shell (replaces legacy shell/ adapter)."""
    from nexus.main_agent.runner import run_v5_repl
    try:
        asyncio.run(run_v5_repl(_setup_environment()))
    except KeyboardInterrupt:
        pass
    return 0


def _first_run_choice(console, panel, box) -> str:
    from rich.console import Group
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text

    choices = [
        ("setup", "Guided setup", "Configure identity, model, safety, and integrations.", "Opening setup wizard..."),
        ("quick", "Quick start", "Create defaults and tune settings later.", "Starting with defaults..."),
        ("start", "Start now", "Launch the TUI without changing configuration.", "Launching TUI..."),
    ]

    if not sys.stdin.isatty() or os.name != "nt":
        _print_banner(console)
        console.print(panel)
        console.print()
        raw = input("  Choice (setup/quick/enter): ").strip().lower()
        return raw if raw in {"setup", "quick"} else "start"

    import msvcrt

    selected = 0

    def render_menu():
        table = Table.grid(expand=True)
        table.add_column(width=5)
        table.add_column(width=20)
        table.add_column(ratio=1)

        for index, (_value, label, description, _next_action) in enumerate(choices):
            active = index == selected
            if active:
                table.add_row(
                    Text("  > ", style="bold black on cyan"),
                    Text(f"{index + 1}. {label}", style="bold black on cyan"),
                    Text(description, style="black on cyan"),
                )
            else:
                table.add_row(
                    Text("    "),
                    Text(f"{index + 1}. {label}", style="white"),
                    Text(description, style="dim"),
                )

        return Group(
            Text.from_markup(BANNER),
            Text(f"  v{__version__} - python {sys.version_info.major}.{sys.version_info.minor}", style="white"),
            "",
            Text("First run detected", style="bold yellow"),
            Text("Choose how NEXUS should start on this machine.", style="dim"),
            "",
            table,
            "",
            Text("Up/Down or PageUp/PageDown to move | Space/Enter to select | Esc to start now", style="dim"),
        )

    chosen = None
    with Live(render_menu(), console=console, auto_refresh=False, transient=False) as live:
        while chosen is None:
            key = msvcrt.getch()
            if key in (b"\r", b" "):
                chosen = choices[selected]
            elif key == b"\x1b":
                chosen = choices[2]
            elif key == b"\xe0":
                key2 = msvcrt.getch()
                if key2 in (b"H", b"I"):
                    selected = max(0, selected - 1)
                    live.update(render_menu(), refresh=True)
                elif key2 in (b"P", b"Q"):
                    selected = min(len(choices) - 1, selected + 1)
                    live.update(render_menu(), refresh=True)

    value, label, _description, next_action = chosen
    console.print()
    console.print(f"[green]Selected:[/green] [bold]{label}[/bold]")
    console.print(f"[dim]{next_action}[/dim]")
    console.print()
    return value


def boot():
    project_root = _setup_environment()
    sys.argv = _apply_command_alias(sys.argv)

    args = _make_parser().parse_args()

    # Dispatch `nexus auth <command>` to the auth CLI handlers.
    if getattr(args, "command", None) == "auth":
        from nexus.command_system.auth import (
            handle_auth_add_key,
            handle_auth_auto_detect,
            handle_auth_delete_profile,
            handle_auth_list,
            handle_auth_login,
            handle_auth_logout,
            handle_auth_set_default,
            handle_auth_strategy,
        )
        handler_map = {
            "login": handle_auth_login,
            "logout": handle_auth_logout,
            "add-key": handle_auth_add_key,
            "list": handle_auth_list,
            "set-default": handle_auth_set_default,
            "delete-profile": handle_auth_delete_profile,
            "auto-detect": handle_auth_auto_detect,
            "strategy": handle_auth_strategy,
        }
        sub = getattr(args, "auth_command", None)
        handler = handler_map.get(sub)
        if handler is None:
            print("auth: unknown subcommand. Try: login, logout, add-key, list, set-default, delete-profile, auto-detect, strategy")
            return
        result = handler(args)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        return

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    if args.version:
        _print_banner(console)
        return

    if args.observe is not None:
        from nexus.observer import run_observer
        return run_observer(
            project_root,
            args.observe,
            after_sequence=args.after_sequence,
            output=sys.stdout,
            format=args.observe_format,
            follow=not args.observe_once,
        )

    if args.reset:
        console.print("[yellow]Resetting configuration to factory defaults...[/yellow]")
        _reset_config(project_root)
        console.print("[green]Config reset.[/green] Launching setup wizard...")
        console.print()
        from apps.tui.setup_wizard import run
        run(project_root)
        return

    if args.export_full:
        console.print("[yellow]Exporting full system (config + memory + knowledge + workspace + logs + auth)...[/yellow]")
        _export_full_system(project_root, args.export_full)
        console.print(f"[green]Full system exported to [bold]{args.export_full}[/bold][/green]")
        return

    if args.import_full_path:
        console.print(f"[yellow]Importing full system from [bold]{args.import_full_path}[/bold]...[/yellow]")
        _import_full_system(project_root, args.import_full_path)
        console.print("[green]Import complete.[/green]")
        from apps.tui.setup_wizard import run
        run(project_root)
        return

    if args.export:
        _export_config(project_root, args.export)
        console.print(f"[green]Config exported to [bold]{args.export}[/bold][/green]")
        return

    if args.import_path:
        console.print(f"[yellow]Importing config from [bold]{args.import_path}[/bold]...[/yellow]")
        _import_config(project_root, args.import_path)
        return

    is_first = _check_first_run(project_root)

    if args.setup:
        from apps.tui.setup_wizard import run
        run(project_root)
        _mark_setup_complete(project_root, "setup")
        return

    if args.quick:
        _print_banner(console)
        _quick_configure(project_root)
        console.print("[yellow]Quick start — using default configuration[/yellow]")
        console.print("[dim]Saved. Next time, [bold]nexus[/bold] launches directly.[/dim]")
        console.print("[dim]Use [bold]nexus-setup[/bold] or [bold]nexus-configure[/bold] to configure later.[/dim]")
        console.print()
        return

    if is_first:
        first_run_panel = (
            "[yellow]First run detected![/yellow]\n\n"
            "Choose how NEXUS should start on this machine:\n\n"
            "  [cyan]1[/cyan]. [bold]Guided setup[/bold]  [dim]Configure model, safety, and integrations[/dim]\n"
            "  [cyan]2[/cyan]. [bold]Quick start[/bold]   [dim]Use defaults and tune later[/dim]\n"
            "  [cyan]3[/cyan]. [bold]Start now[/bold]     [dim]Launch the TUI without changes[/dim]\n\n"
            "[dim]Type setup, quick, or press Enter to start now.[/dim]"
        )
        choice = _first_run_choice(console, first_run_panel, box)
        if choice == "setup":
            from apps.tui.setup_wizard import run
            run(project_root)
            _mark_setup_complete(project_root, "setup")
            return
        elif choice == "quick":
            console.print("[yellow]Starting with defaults...[/yellow]")
            _quick_configure(project_root)
        console.print()

    if args.v5:
        _print_banner(console)
        console.print("[bold green]Starting NEXUS V5 engine...[/bold green]")
        console.print("[dim]V5 is the canonical NEXUS loop used by the API, Hive, and TUI.[/dim]")
        from nexus.main_agent.runner import run_v5_repl
        try:
            asyncio.run(run_v5_repl(project_root))
        except KeyboardInterrupt:
            pass
        return

    if args.gateway:
        _print_banner(console)
        console.print("[bold green]Starting Gateway...[/bold green]")
        from gateways.main import run as run_gateway
        run_gateway()
        return

    if args.shell:
        return_code = _run_rich_shell()
        raise SystemExit(return_code)

    if args.server:
        _print_banner(console)
        console.print("[bold green]Starting API Server on :8000...[/bold green]")
        import subprocess
        # Anonymous mode is an explicit local-development choice. Do not
        # silently weaken authentication from the launcher.
        server_env = os.environ.copy()
        server_env.setdefault("NEXUS_ALLOW_LOCAL_ANON", "false")
        proc = subprocess.Popen(
            [sys.executable, "-m", "server"],
            cwd=project_root,
            env=server_env,
            **_server_process_group_kwargs(),
        )
        try:
            asyncio.run(_wait_for_health("http://127.0.0.1:8000/api/health", label="API server"))
            proc.wait()
        except KeyboardInterrupt:
            _terminate_server_process(proc)
        finally:
            if proc.poll() is None:
                _terminate_server_process(proc)
        return

    if args.supervise:
        _print_banner(console)
        console.print("[bold green]Starting supervised Nexus API...[/bold green]")
        from nexus.supervisor import run_supervisor
        raise SystemExit(run_supervisor(project_root))

    if args.gui:
        _print_banner(console)
        console.print("[bold green]Starting GUI + Backend...[/bold green]")
        import subprocess

        # Reuse a current local GUI/backend instead of creating duplicate
        # servers. If the process is stale, replace only the known NEXUS
        # ports so the browser cannot remain connected to an old backend.
        if _api_is_ready() and _api_is_current() and _port_is_listening(5173):
            console.print("[yellow]NEXUS GUI is already running on :5173; reusing it.[/yellow]")
            return

        _kill_windows_port(8000)
        _kill_windows_port(5173)

        server_env = os.environ.copy()
        server_env.setdefault("NEXUS_ALLOW_LOCAL_ANON", "false")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "apps.api:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=project_root,
            env=server_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_server_process_group_kwargs(),
        )
        asyncio.run(_wait_for_health("http://127.0.0.1:8000/api/health", label="API server"))
        try:
            command = (["npm.cmd"] if os.name == "nt" else ["npm"])
            command.extend(["run", "dev", "--", "--host", "127.0.0.1"])
            _run_owned_foreground_process(command, os.path.join(project_root, "apps", "web"))
        finally:
            _terminate_server_process(proc)
        return

    if args.mission:
        _print_banner(console)
        console.print("[bold green]Starting 24/7 Mission...[/bold green]")
        console.print(f"[dim]Goal: {args.mission}[/dim]")
        console.print("[dim]Milestones run through the durable queue until the goal is complete, resuming after any restart.[/dim]")
        from queues.mission import MissionRunner
        from queues.driver import run_forever
        runner = MissionRunner(root=project_root)
        runner.create_mission(args.mission)
        try:
            asyncio.run(run_forever(workers=1, missions=True, root=project_root))
        except KeyboardInterrupt:
            pass
        return

    if args.autonomous:
        _print_banner(console)
        console.print("[bold green]Starting 24/7 Autonomous Queue Driver...[/bold green]")
        console.print("[dim]Tasks are pulled from the durable queue and executed forever.[/dim]")
        console.print("[dim]Enqueue with:  python -m queue.enqueue \"your task\"[/dim]")
        from queues.driver import run_forever
        try:
            asyncio.run(run_forever(workers=1, missions=True))
        except KeyboardInterrupt:
            pass
        return

    raise SystemExit(_run_ink_tui(project_root, console))


if __name__ == "__main__":
    boot()
