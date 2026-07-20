"""NEXUS Setup Wizard — first-run experience.

Usage:
    python -m nexus --setup
    python -m nexus --quick   (skip wizard, auto-configure)

Sets up: environment, provider credentials, gateway tokens,
profiles, and connection verification.
"""

from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

logger = logging.getLogger("nexus.setup")
console = Console()

NEXUS_LOGO = """
[bold cyan]
    ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
    ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
    ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
    ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
    ██║ ╚████║██████╗██╔╝ ██╗╚██████╔╝███████║
    ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
[/bold cyan]"""

PROVIDER_DEFS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "name": "DeepSeek",
        "docs": "https://platform.deepseek.com/api_keys",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-v3"],
        "endpoint": "https://api.deepseek.com/chat/completions",
        "tier": "cloud",
        "tag": "Recommended",
    },
    "openai": {
        "name": "OpenAI",
        "docs": "https://platform.openai.com/api-keys",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "anthropic": {
        "name": "Anthropic",
        "docs": "https://console.anthropic.com/keys",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20240620", "claude-3-5-haiku-20241022"],
        "endpoint": "https://api.anthropic.com/v1/messages",
        "tier": "cloud",
        "tag": "",
    },
    "openrouter": {
        "name": "OpenRouter",
        "docs": "https://openrouter.ai/keys",
        "env_key": "OPENROUTER_API_KEY",
        "models": ["auto"],
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "tier": "cloud",
        "tag": "Aggregator",
    },
    "gemini": {
        "name": "Google Gemini",
        "docs": "https://aistudio.google.com/app/apikey",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro"],
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "tier": "cloud",
        "tag": "",
    },
    "groq": {
        "name": "Groq",
        "docs": "https://console.groq.com/keys",
        "env_key": "GROQ_API_KEY",
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "tier": "cloud",
        "tag": "Fast",
    },
    "mistral": {
        "name": "Mistral",
        "docs": "https://console.mistral.ai/api-keys",
        "env_key": "MISTRAL_API_KEY",
        "models": ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"],
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "cohere": {
        "name": "Cohere",
        "docs": "https://dashboard.cohere.com/api-keys",
        "env_key": "COHERE_API_KEY",
        "models": ["command-r-plus", "command-r", "command-light"],
        "endpoint": "https://api.cohere.ai/v1/chat",
        "tier": "cloud",
        "tag": "",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "docs": "https://fireworks.ai/account/api-keys",
        "env_key": "FIREWORKS_API_KEY",
        "models": ["accounts/fireworks/models/llama-v3p1-70b-instruct", "accounts/fireworks/models/mixtral-8x22b-instruct"],
        "endpoint": "https://api.fireworks.ai/inference/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "huggingface": {
        "name": "HuggingFace",
        "docs": "https://huggingface.co/settings/tokens",
        "env_key": "HUGGINGFACE_API_KEY",
        "models": ["google/gemma-2-9b-it", "meta-llama/Llama-3.2-3B-Instruct", "microsoft/Phi-3-mini-4k-instruct"],
        "endpoint": "https://api-inference.huggingface.co/models",
        "tier": "cloud",
        "tag": "",
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "docs": "https://build.nvidia.com/",
        "env_key": "NVIDIA_API_KEY",
        "models": ["meta/llama-3.1-405b-instruct", "mistralai/mistral-7b-instruct-v0.3"],
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "perplexity": {
        "name": "Perplexity",
        "docs": "https://www.perplexity.ai/settings/api",
        "env_key": "PERPLEXITY_API_KEY",
        "models": ["llama-3.1-sonar-large-128k-online", "llama-3.1-sonar-small-128k-online"],
        "endpoint": "https://api.perplexity.ai/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "qwen": {
        "name": "Qwen (DashScope)",
        "docs": "https://dashscope.aliyun.com/",
        "env_key": "QWEN_API_KEY",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "replicate": {
        "name": "Replicate",
        "docs": "https://replicate.com/account/api-tokens",
        "env_key": "REPLICATE_API_KEY",
        "models": ["meta/meta-llama-3.1-405b-instruct", "meta/meta-llama-3.1-70b-instruct"],
        "endpoint": "https://api.replicate.com/v1/predictions",
        "tier": "cloud",
        "tag": "",
    },
    "sambanova": {
        "name": "SambaNova",
        "docs": "https://cloud.sambanova.com/",
        "env_key": "SAMBANOVA_API_KEY",
        "models": ["Meta-Llama-3.1-70B-Instruct", "Meta-Llama-3.1-8B-Instruct"],
        "endpoint": "https://api.sambanova.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "together": {
        "name": "Together AI",
        "docs": "https://api.together.xyz/settings/api-keys",
        "env_key": "TOGETHER_API_KEY",
        "models": ["meta-llama/Llama-3-70b-chat-hf", "mistralai/Mixtral-8x22B-Instruct-v0.1", "Qwen/Qwen2-72B-Instruct"],
        "endpoint": "https://api.together.xyz/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "xai": {
        "name": "xAI (Grok)",
        "docs": "https://x.ai/api",
        "env_key": "XAI_API_KEY",
        "models": ["grok-beta", "grok-2", "grok-2-mini"],
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "commandcode": {
        "name": "CommandCode",
        "docs": "https://commandcode.ai",
        "env_key": "COMMANDCODE_API_KEY",
        "models": ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v3", "auto"],
        "endpoint": "https://api.commandcode.ai/provider/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "azure_openai": {
        "name": "Azure OpenAI",
        "docs": "https://portal.azure.com/#view/Microsoft_Azure_Marketplace/MarketplaceOffersBlade",
        "env_key": "AZURE_OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4-turbo", "gpt-35-turbo"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "Enterprise",
    },
    "ollama": {
        "name": "Ollama",
        "docs": "https://ollama.ai",
        "env_key": "",
        "models": ["llama3", "mistral", "codellama", "phi"],
        "endpoint": "http://127.0.0.1:11434/api/chat",
        "tier": "local",
        "tag": "Local",
    },
    "lm_studio": {
        "name": "LM Studio",
        "docs": "https://lmstudio.ai",
        "env_key": "",
        "models": ["auto-detect"],
        "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
        "tier": "local",
        "tag": "Local",
    },
    "llama_cpp": {
        "name": "LlamaCPP",
        "docs": "https://github.com/ggerganov/llama.cpp",
        "env_key": "",
        "models": ["local .gguf"],
        "endpoint": "",
        "tier": "local",
        "tag": "Local",
    },
    "zupra": {
        "name": "Zupra (Local HF)",
        "docs": "https://huggingface.co/MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp",
        "env_key": "",
        "models": ["MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp"],
        "endpoint": "local",
        "tier": "local",
        "tag": "Local",
    },
    "universal": {
        "name": "OpenAI-Compatible",
        "docs": "",
        "env_key": "",
        "models": ["auto"],
        "endpoint": "http://localhost:8000/v1/chat/completions",
        "tier": "cloud",
        "tag": "Custom",
    },
    # ── OAuth Providers ──────────────────────────────────────
    "codex": {
        "name": "Codex (ChatGPT)",
        "docs": "https://chat.openai.com",
        "env_key": "",
        "models": ["chatgpt-4o", "chatgpt-4", "chatgpt-3.5"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "claude": {
        "name": "Claude Code (Anthropic)",
        "docs": "https://claude.ai",
        "env_key": "",
        "models": ["claude-sonnet-4", "claude-3-5-sonnet", "claude-3-5-haiku"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "github_copilot": {
        "name": "GitHub Copilot",
        "docs": "https://github.com/login/device",
        "env_key": "",
        "models": ["gpt-4o-copilot", "claude-3.5-copilot"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "grok_oauth": {
        "name": "Grok (xAI OAuth)",
        "docs": "https://x.ai",
        "env_key": "",
        "models": ["grok-2", "grok-2-mini"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "gemini_oauth": {
        "name": "Gemini (Google OAuth)",
        "docs": "https://gemini.google.com",
        "env_key": "",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "minimax": {
        "name": "MiniMax",
        "docs": "https://minimax.io",
        "env_key": "",
        "models": ["auto"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    "chutes": {
        "name": "Chutes",
        "docs": "https://chutes.ai",
        "env_key": "",
        "models": ["auto"],
        "endpoint": "",
        "tier": "cloud",
        "tag": "OAuth",
    },
    # ── Universal-Mapped Providers ──────────────────────────
    "deepinfra": {
        "name": "DeepInfra",
        "docs": "https://deepinfra.com",
        "env_key": "DEEPINFRA_API_KEY",
        "models": ["meta-llama/Llama-3.3-70B-Instruct", "mistralai/Mixtral-8x22B-Instruct"],
        "endpoint": "https://api.deepinfra.com/v1/openai/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "cerebras": {
        "name": "Cerebras",
        "docs": "https://cerebras.ai",
        "env_key": "CEREBRAS_API_KEY",
        "models": ["llama3.1-70b", "llama3.1-8b"],
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "moonshot": {
        "name": "Moonshot AI",
        "docs": "https://moonshot.cn",
        "env_key": "MOONSHOT_API_KEY",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "endpoint": "https://api.moonshot.cn/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "kimi": {
        "name": "Kimi",
        "docs": "https://kimi.moonshot.cn",
        "env_key": "KIMI_API_KEY",
        "models": ["kimi-v1", "kimi-v1.5"],
        "endpoint": "https://api.kimi.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "stepfun": {
        "name": "StepFun",
        "docs": "https://stepfun.com",
        "env_key": "STEPFUN_API_KEY",
        "models": ["step-1", "step-1-8k", "step-1-32k"],
        "endpoint": "https://api.stepfun.com/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "zai": {
        "name": "Z.AI",
        "docs": "https://z.ai",
        "env_key": "ZAI_API_KEY",
        "models": ["auto"],
        "endpoint": "https://api.z.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "venice": {
        "name": "Venice",
        "docs": "https://venice.ai",
        "env_key": "VENICE_API_KEY",
        "models": ["auto"],
        "endpoint": "https://api.venice.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "novita": {
        "name": "Novita AI",
        "docs": "https://novita.ai",
        "env_key": "NOVITA_API_KEY",
        "models": ["auto"],
        "endpoint": "https://api.novita.ai/v1/chat/completions",
        "tier": "cloud",
        "tag": "",
    },
    "vllm": {
        "name": "vLLM",
        "docs": "https://github.com/vllm-project/vllm",
        "env_key": "",
        "models": ["auto"],
        "endpoint": "http://localhost:8000/v1/chat/completions",
        "tier": "local",
        "tag": "Local",
    },
    "sglang": {
        "name": "SGLang",
        "docs": "https://github.com/sgl-project/sglang",
        "env_key": "",
        "models": ["auto"],
        "endpoint": "http://localhost:30000/v1/chat/completions",
        "tier": "local",
        "tag": "Local",
    },
}

GATEWAY_DEFS: Dict[str, Dict[str, str]] = {
    "telegram": {"env_key": "TELEGRAM_BOT_TOKEN", "docs": "https://t.me/botfather", "icon": "✈️"},
    "discord": {"env_key": "DISCORD_BOT_TOKEN", "docs": "https://discord.com/developers/applications", "icon": "🎮"},
    "slack": {"env_key": "SLACK_BOT_TOKEN", "docs": "https://api.slack.com/apps", "icon": "💬"},
    "whatsapp": {"env_key": "WHATSAPP_TOKEN", "docs": "https://developers.facebook.com/docs/whatsapp", "icon": "📱"},
}

OAUTH_PROVIDER_ALIASES: Dict[str, str] = {
    "github_copilot": "github-copilot",
    "grok_oauth": "grok",
    "gemini_oauth": "gemini",
}

VERSION = "2.0.0"
SETUP_LOG = Path.home() / ".nexus" / "setup.log"
SETUP_COMPLETE_FILE = ".setup_complete"
FIRST_RUN_FILE = ".first_run"


def mark_setup_complete(root_dir: str, mode: str = "setup") -> None:
    import json

    config_dir = Path(root_dir) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    complete_path = config_dir / SETUP_COMPLETE_FILE
    first_run_path = config_dir / FIRST_RUN_FILE
    complete_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "version": VERSION,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        first_run_path.unlink(missing_ok=True)
    except Exception:
        logger.warning("Failed to remove first-run marker", exc_info=True)


# ── Arrow-key navigable menu ────────────────────────────────

def select(title: str, options: List[str], console=console, page_size: int = 16) -> int:
    if not sys.stdin.isatty():
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]\n")
        for i, opt in enumerate(options):
            console.print(f"  [cyan]{i+1}[/cyan]. {opt}")
        raw = Prompt.ask("\n  Choice", default="1")
        if raw.isdigit():
            return max(0, min(int(raw) - 1, len(options) - 1))
        return 0

    try:
        import msvcrt
    except ImportError:
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]\n")
        for i, opt in enumerate(options):
            console.print(f"  [cyan]{i+1}[/cyan]. {opt}")
        raw = Prompt.ask("\n  Choice", default="1")
        if raw.isdigit():
            return max(0, min(int(raw) - 1, len(options) - 1))
        return 0

    sel = 0
    scroll = 0
    total = len(options)
    try:
        page_size = min(max(8, console.size.height - 8), page_size, max(1, total))
    except Exception:
        page_size = min(page_size, max(1, total))
    first_render = True
    while True:
        if not first_render:
            console.clear()
        first_render = False
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]\n")
        visible = options[scroll:scroll + page_size]
        for i, opt in enumerate(visible):
            idx = scroll + i
            prefix = "  [cyan]▸[/cyan]" if idx == sel else "   "
            style = "[bold white]" if idx == sel else "[dim]"
            console.print(f"{prefix} {style}{opt}[/]")
        console.print("\n[dim]↑↓ navigate | Space/Enter select[/dim]")

        key = msvcrt.getch()
        if key == b'\xe0':
            key2 = msvcrt.getch()
            scroll_max = max(0, total - page_size)
            if key2 == b'H':
                sel = max(0, sel - 1)
                if sel < scroll:
                    scroll = max(0, scroll - 1)
            elif key2 == b'P':
                sel = min(total - 1, sel + 1)
                if sel >= scroll + page_size:
                    scroll = min(scroll_max, scroll + 1)
            elif key2 == b'I':
                sel = max(0, sel - page_size)
                scroll = max(0, scroll - page_size)
            elif key2 == b'Q':
                sel = min(total - 1, sel + page_size)
                scroll = min(scroll_max, scroll + page_size)
        elif key == b' ' or key == b'\r':
            return sel


def _parse_multi_choice(raw: str, total: int, default_selected: set[int]) -> set[int]:
    value = raw.strip().lower()
    if not value:
        return set(default_selected)
    if value in {"all", "a", "*"}:
        return set(range(total))
    if value in {"none", "n", "0"}:
        return set()

    picked: set[int] = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            if start_raw.strip().isdigit() and end_raw.strip().isdigit():
                start = max(1, int(start_raw))
                end = min(total, int(end_raw))
                if start <= end:
                    picked.update(range(start - 1, end))
            continue
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < total:
                picked.add(idx)
    return picked


def multi_select(
    title: str,
    options: List[str],
    console=console,
    page_size: int = 18,
    default_selected: Optional[List[int]] = None,
) -> Optional[List[int]]:
    """Checklist selector.

    Space toggles the focused row, Enter accepts, Esc cancels/backtracks.
    PageUp/PageDown jump by a visible page.
    """
    total = len(options)
    if total == 0:
        return []

    selected = set(default_selected if default_selected is not None else range(total))

    if not sys.stdin.isatty():
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]\n")
        for i, opt in enumerate(options):
            mark = "x" if i in selected else " "
            console.print(f"  [cyan]{i+1}[/cyan]. [{mark}] {opt}")
        status_dim("  Non-interactive terminal — using default selection")
        return sorted(selected)

    try:
        import msvcrt
    except ImportError:
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]\n")
        for i, opt in enumerate(options):
            mark = "x" if i in selected else " "
            console.print(f"  [cyan]{i+1}[/cyan]. [{mark}] {opt}")
        raw = Prompt.ask(
            "\n  Select numbers/ranges, 'all', or 'none'",
            default="all" if len(selected) == total else "",
        )
        return sorted(_parse_multi_choice(raw, total, selected))

    sel = 0
    scroll = 0
    try:
        page_size = min(max(8, console.size.height - 9), page_size, max(1, total))
    except Exception:
        page_size = min(page_size, max(1, total))

    first_render = True
    while True:
        if not first_render:
            console.clear()
        first_render = False
        console.print(f"\n[bold cyan]▸ {title}[/bold cyan]")
        console.print(f"[dim]Selected {len(selected)}/{total}[/dim]\n")
        visible = options[scroll:scroll + page_size]
        for i, opt in enumerate(visible):
            idx = scroll + i
            focus = idx == sel
            pointer = "  [cyan]▸[/cyan]" if focus else "   "
            mark = "[green]x[/green]" if idx in selected else " "
            style = "[bold white]" if focus else "[dim]"
            console.print(f"{pointer} [{mark}] {style}{opt}[/]")
        console.print("\n[dim]↑↓ navigate | PgUp/PgDn page | Space toggle | A all/none | Enter save | Esc back[/dim]")

        key = msvcrt.getch()
        if key == b'\xe0':
            key2 = msvcrt.getch()
            scroll_max = max(0, total - page_size)
            if key2 == b'H':
                sel = max(0, sel - 1)
                if sel < scroll:
                    scroll = max(0, scroll - 1)
            elif key2 == b'P':
                sel = min(total - 1, sel + 1)
                if sel >= scroll + page_size:
                    scroll = min(scroll_max, scroll + 1)
            elif key2 == b'I':
                sel = max(0, sel - page_size)
                if sel < scroll:
                    scroll = max(0, sel)
            elif key2 == b'Q':
                sel = min(total - 1, sel + page_size)
                if sel >= scroll + page_size:
                    scroll = min(scroll_max, max(0, sel - page_size + 1))
        elif key == b' ':
            if sel in selected:
                selected.remove(sel)
            else:
                selected.add(sel)
        elif key in (b'a', b'A'):
            selected = set() if len(selected) == total else set(range(total))
        elif key == b'\r':
            return sorted(selected)
        elif key == b'\x1b':
            return None


# ── I/O helpers ──────────────────────────────────────────────

def secret_input(prompt_text: str) -> str:
    console.print("[dim]  Paste your key/token, then press Enter. Input is hidden.[/dim]")
    value = ""
    try:
        value = Prompt.ask(f"  {prompt_text}", password=True).strip()
    except Exception:
        try:
            value = getpass.getpass(f"  {prompt_text}: ").strip()
        except Exception:
            value = ""

    if value or not sys.stdin.isatty():
        return value

    console.print("[yellow]  Nothing was entered. Some Windows terminals block paste in hidden prompts.[/yellow]")
    if Confirm.ask("  Use visible paste mode for this one secret?", default=True):
        console.print("[dim]  The next line will show what you paste. It is not logged by NEXUS.[/dim]")
        return Prompt.ask(f"  {prompt_text}").strip()

    return ""


def masked_input(prompt_text: str) -> str:
    """Compatibility wrapper used by setup tests and older callers."""
    return secret_input(prompt_text)


def is_configured_secret(value: object) -> bool:
    """Return True only for values that look like an actual user secret.

    Setup templates often contain values like ``your_token_here``. Treating
    those as configured makes the wizard claim integrations are ready when
    they cannot work.
    """
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        return False
    lowered = text.lower()
    exact_placeholders = {
        "none",
        "null",
        "changeme",
        "change_me",
        "replace_me",
        "your_token",
        "your_token_here",
        "your_api_key",
        "your_api_key_here",
        "token_here",
        "api_key_here",
        "paste_token_here",
        "paste_api_key_here",
    }
    if lowered in exact_placeholders:
        return False
    placeholder_bits = (
        "your_",
        "_here",
        "token_here",
        "api_key_here",
        "paste_",
        "replace_me",
        "changeme",
        "<",
        ">",
    )
    return not any(bit in lowered for bit in placeholder_bits)


def ask_yes_no(prompt_text: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer without requiring Rich.

    The wizard itself uses Rich's Confirm component, but tests and older
    scripts import this small stdlib helper directly.
    """
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{prompt_text} [{suffix}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def ask_float(prompt_text: str, default: str, min_value: float, max_value: float) -> float:
    raw = Prompt.ask(prompt_text, default=default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        status_info(f"Invalid number, using default {default}.")
        value = float(default)
    return max(min_value, min(max_value, value))


def ask_int(prompt_text: str, default: str, min_value: int, max_value: int) -> int:
    raw = Prompt.ask(prompt_text, default=default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        status_info(f"Invalid number, using default {default}.")
        value = int(default)
    return max(min_value, min(max_value, value))


def status_ok(msg: str):
    console.print(f"  [bold green]✓[/bold green] {msg}")


def status_fail(msg: str):
    console.print(f"  [bold red]✗[/bold red] {msg}")


def status_info(msg: str):
    console.print(f"  [cyan]ℹ[/cyan] {msg}")


def status_dim(msg: str):
    console.print(f"  [dim]{msg}[/dim]")


# ── File operations ──────────────────────────────────────────

def load_env(root_dir: str) -> Dict[str, str]:
    path = Path(root_dir) / "config" / ".env"
    env: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def save_env(root_dir: str, env: Dict[str, str]):
    path = Path(root_dir) / "config" / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(env.items()) if v]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    status_ok(f"Saved [bold]{path.name}[/bold]")


def load_provider_yml(root_dir: str) -> Dict[str, Any]:
    path = Path(root_dir) / "config" / "provider.yml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_provider_yml(root_dir: str, config: Dict[str, Any]):
    path = Path(root_dir) / "config" / "provider.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    status_ok(f"Saved [bold]{path.name}[/bold]")


# ── Connection testing ───────────────────────────────────────

def test_provider(provider: str, api_key: str, endpoint: str, model: str) -> Tuple[bool, str, float]:
    import httpx
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with only: OK"}],
        "max_tokens": 10,
    }
    for attempt in range(3):
        try:
            start = time.monotonic()
            with httpx.Client(timeout=20) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
            elapsed = time.monotonic() - start
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return True, text.strip(), elapsed
            msg = f"HTTP {resp.status_code}"
            try:
                err = resp.json()
                msg += f": {err.get('error', {}).get('message', '')}"
            except Exception:
                msg += f": {resp.text[:120]}"
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            return False, msg, elapsed
        except Exception as e:
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            return False, str(e), 0.0


def test_connection(provider: str, api_key: str, endpoint: str, model: str) -> Tuple[bool, str]:
    """Backwards-compatible two-value connection test helper."""
    success, message, _elapsed = test_provider(provider, api_key, endpoint, model)
    return success, message


# ── System checks ────────────────────────────────────────────

def _run_cmd(cmd: List[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def check_python() -> Tuple[bool, str]:
    v = sys.version_info
    ok = v.major >= 3 and v.minor >= 10
    return ok, f"{v.major}.{v.minor}.{v.micro}"


def check_node() -> Tuple[bool, str]:
    out = _run_cmd(["node", "--version"])
    if out:
        return True, out
    return False, "not installed"


def check_git() -> Tuple[bool, str]:
    out = _run_cmd(["git", "--version"])
    if out:
        return True, out
    return False, "not installed"


def check_nexus_installed() -> Tuple[bool, str]:
    out = _run_cmd([sys.executable, "-m", "pip", "show", "nexus-ai"])
    if out:
        for line in out.splitlines():
            if line.startswith("Version:"):
                return True, line.split(":")[1].strip()
    return False, "not installed"


def check_nexus_update(current_version: str) -> Tuple[bool, str]:
    try:
        import httpx
        r = httpx.get("https://pypi.org/pypi/nexus-ai/json", timeout=5)
        if r.status_code == 200:
            latest = r.json()["info"]["version"]
            if latest != current_version:
                return True, latest
            return False, ""
        return False, ""
    except Exception:
        return False, ""


def check_ram() -> Tuple[bool, str]:
    try:
        import psutil
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024**3)
        avail_gb = mem.available / (1024**3)
        return True, f"{avail_gb:.1f}GB / {total_gb:.1f}GB free"
    except ImportError:
        if os.name == "nt":
            out = _run_cmd(["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/Value"])
            if out:
                free = 0
                for line in out.splitlines():
                    if "FreePhysicalMemory" in line:
                        free = int(line.split("=")[1]) / 1024 / 1024
                    if "TotalVisibleMemorySize" in line:
                        total = int(line.split("=")[1]) / 1024 / 1024
                if free and total:
                    return True, f"{free:.1f}GB / {total:.1f}GB free"
        import shutil
        total, used, free = shutil.disk_usage("/")
        return True, f"{free / (1024**3):.1f}GB / {total / (1024**3):.1f}GB"
    except Exception:
        return True, "unknown"


def check_storage() -> Tuple[bool, str]:
    try:
        import shutil
        total, used, free = shutil.disk_usage(os.path.dirname(root_dir))
        return True, f"{free // (1024**3)}GB free of {total // (1024**3)}GB"
    except Exception:
        return True, "unknown"


def check_cpu() -> Tuple[bool, str]:
    try:
        import psutil
        cores = psutil.cpu_count(logical=True)
        phys = psutil.cpu_count(logical=False)
        freq = psutil.cpu_freq()
        freq_str = f" @ {freq.current:.0f}MHz" if freq else ""
        return True, f"{phys} cores / {cores} threads{freq_str}"
    except ImportError:
        out = _run_cmd(["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors", "/Format:csv"])
        if out:
            parts = out.splitlines()
            if len(parts) > 1:
                cols = parts[1].split(",")
                name = cols[-3] if len(cols) > 3 else "CPU"
                return True, name
        import os
        return True, os.environ.get("PROCESSOR_IDENTIFIER", "unknown").split()[0] if os.name == "nt" else "unknown"
    except Exception:
        return True, "unknown"


def check_os() -> Tuple[bool, str]:
    try:
        if os.name == "nt":
            out = _run_cmd(["cmd", "/c", "ver"])
            if out:
                return True, out.strip()
            out = _run_cmd(["powershell", "-Command", "(Get-CimInstance Win32_OperatingSystem).Caption"])
            if out:
                return True, out.strip()
            return True, f"Windows {sys.getwindowsversion().major}.{sys.getwindowsversion().minor}"
        out = _run_cmd(["uname", "-a"])
        return True, out.split()[0] if out else "unknown"
    except Exception:
        return True, "unknown"


def check_powershell() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["powershell", "-Command", "$PSVersionTable.PSVersion.ToString()"])
        if out:
            return True, out.strip()
        return False, "not found"
    except Exception:
        return False, "not available"


def check_docker() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["docker", "--version"])
        if out:
            return True, out.strip()
        return False, "not installed"
    except Exception:
        return False, "not installed"


def check_internet() -> Tuple[bool, str]:
    try:
        import httpx
        r = httpx.get("https://clients3.google.com/generate_204", timeout=5)
        return True, f"{r.elapsed.total_seconds()*1000:.0f}ms"
    except Exception:
        return False, "offline"


def check_wsl() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["wsl", "--status"])
        if out:
            first = out.splitlines()[0] if out.splitlines() else ""
            clean = first.strip().replace("\x00", "")
            if "Default" in clean:
                clean = clean.split(":")[-1].strip()
            return True, clean if clean else "installed"
        return False, "not installed"
    except FileNotFoundError:
        return False, "not installed"
    except Exception:
        return False, "not available"


def check_winget() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["winget", "--version"])
        if out:
            return True, out.strip()
        return False, "not installed"
    except FileNotFoundError:
        return False, "not installed"
    except Exception:
        return False, "not available"


def check_cuda() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
        if out:
            return True, out.strip().split(",")[0].strip()
        return False, "no NVIDIA GPU"
    except FileNotFoundError:
        return False, "no NVIDIA GPU"
    except Exception:
        return False, "not available"


def check_uv() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["uv", "--version"])
        if out:
            ver = out.strip().split()[1] if len(out.split()) > 1 else out.split()[0]
            return True, ver
        return False, "not installed"
    except FileNotFoundError:
        return False, "not installed"
    except Exception:
        return False, "not available"


def check_conda() -> Tuple[bool, str]:
    try:
        out = _run_cmd(["conda", "--version"])
        if out:
            return True, out.strip().replace("conda ", "")
        return False, "not installed"
    except FileNotFoundError:
        return False, "not installed"
    except Exception:
        return False, "not available"


def check_ollama() -> Tuple[bool, str]:
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = r.json().get("models", [])
            return True, f"running ({len(models)} models)"
        return False, "not available"
    except Exception:
        return False, "not running"


def check_lm_studio() -> Tuple[bool, str]:
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:1234/v1/models", timeout=3)
        if r.status_code == 200:
            return True, "running"
        return False, "not available"
    except Exception:
        return False, "not running"


root_dir = ""


# ── Step counter (updated as wizard progresses) ──────────────
_STEP = 0
_TOTAL = 14
_SETUP_MODE = ""

_STEPS: List[Dict[str, str]] = []
_STEP_ICONS: List[str] = []
_STEP_TITLES: List[str] = []
_STEP_SUBS: List[str] = []


def register_steps():
    global _STEP_ICONS, _STEP_TITLES, _STEP_SUBS
    _STEP_ICONS = ["👤","📁","⚙️","🛡️","🤖","📡","👤","🧩","🔄","📚","💰","🔌","🌐","🎉"]
    _STEP_TITLES = ["Agent Identity","Workspace Setup","System Settings","Sandbox","Choose Provider","Gateways","Profile","Extensions","Fallback Chain","Knowledge Base","Cost Controls","Test Connection","Host Settings","Finish"]
    _STEP_SUBS  = ["Name, personality, style","Project directories","Theme, model, behavior","Execution isolation","AI provider selection","Messaging integrations","Personalization","Skills, tools, plugins","Model fallback chain","RAG document indexing","Spending limits","Connection verification","Remote access","Complete!"]


def _s():
    global _STEP
    _STEP += 1


def show_steps():
    for i in range(_TOTAL):
        step_num = i + 1
        icon = _STEP_ICONS[i]
        title = _STEP_TITLES[i]
        sub = _STEP_SUBS[i]
        if step_num < _STEP:
            line = f"[dim]  {step_num:2d}. ✓ {icon}  {title}[/dim]"
        elif step_num == _STEP:
            line = f"[bold cyan]  {step_num:2d}. → {icon}  {title}[/bold cyan] [dim]— {sub}[/dim]"
        else:
            line = f"[dim white]  {step_num:2d}. ○ {icon}  {title}[/dim white]"
        console.print(line)


def wizard_header():
    console.clear()
    console.print(NEXUS_LOGO)
    console.print()
    if _SETUP_MODE:
        mode_labels = {"local": "🖥️ Local", "host": "🌐 Host", "quick": "⚡ Quick"}
        label = mode_labels.get(_SETUP_MODE, _SETUP_MODE)
        console.print(f"  [bold green]Setup mode: {label}[/bold green]")
        console.print()
    show_steps()
    console.print()


MINIMUM_REQUIRED = ["Python", "Git", "Node.js"]

INSTALL_CMDS: Dict[str, List[str]] = {
    "Python":  ["winget", "install", "--id", "Python.Python.3.14", "--accept-source-agreements", "--accept-package-agreements"],
    "Git":     ["winget", "install", "--id", "Git.Git", "--accept-source-agreements", "--accept-package-agreements"],
    "Node.js": ["winget", "install", "--id", "OpenJS.NodeJS.LTS", "--accept-source-agreements", "--accept-package-agreements"],
}

CHECK_FUNCS: Dict[str, object] = {
    "Python":  check_python,
    "Git":     check_git,
    "Node.js": check_node,
}


def _run_checks() -> List[Tuple[str, str, Tuple[bool, str]]]:
    return [
        ("OS",         "system", check_os()),
        ("Python",     "≥3.10",  check_python()),
        ("Node.js",    "GUI",    check_node()),
        ("Git",        "tools",  check_git()),
        ("PowerShell", "opt",    check_powershell()),
        ("WSL",        "opt",    check_wsl()),
        ("winget",     "mgr",    check_winget()),
        ("Docker",     "sandbox", check_docker()),
        ("CUDA",       "GPU",    check_cuda()),
        ("uv",         "pip",    check_uv()),
        ("Conda",      "env",    check_conda()),
        ("Internet",   "net",    check_internet()),
        ("NEXUS",      "pkg",    check_nexus_installed()),
        ("RAM",        "sys",    check_ram()),
        ("Storage",    "disk",   check_storage()),
        ("CPU",        "proc",   check_cpu()),
    ]


def _render_checks(checks: List[Tuple[str, str, Tuple[bool, str]]]) -> Dict[str, bool]:
    table = Table(box=box.SIMPLE, border_style="cyan", padding=(0, 2))
    table.add_column("Check", style="bold white", width=10, no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", style="dim", width=10, no_wrap=True)

    result = {}
    for name, desc, (ok, detail) in checks:
        icon = "[bold green]✓[/bold green]" if ok else "[yellow]○[/yellow]"
        table.add_row(name, f"{icon}  {detail}", desc)
        result[name] = ok

    console.print(table)
    console.print()
    return result


def _auto_install(missing: List[str]) -> None:
    has_winget = check_winget()[0]
    if not has_winget:
        console.print("  [yellow]winget not available, can't auto-install[/yellow]")
        return

    for name in missing:
        cmd = INSTALL_CMDS.get(name)
        if not cmd:
            console.print(f"  [yellow]No install command for {name}[/yellow]")
            continue
        console.print(f"\n  Installing [bold cyan]{name}[/]...")
        try:
            subprocess.run(cmd, capture_output=True, timeout=180)
            console.print(f"  [bold green]✓[/] {name} installed")
        except subprocess.TimeoutExpired:
            console.print(f"  [yellow]⚠ {name} install timed out[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]⚠ {name} install failed: {e}[/yellow]")


def system_check(project_root: str) -> bool:
    global root_dir
    root_dir = project_root

    console.clear()
    console.print(NEXUS_LOGO)
    console.print()

    checks = _run_checks()
    result = _render_checks(checks)

    missing_min = [n for n in MINIMUM_REQUIRED if n in result and not result[n]]

    if missing_min:
        need = ", ".join(f"[bold cyan]{n}[/]" for n in missing_min)
        console.print(Panel(
            f"[yellow]⚠  Need these minimum requirements:[/yellow] {need}\n\n"
            f"  I can auto-install [bold]only[/bold] what's missing — no extra trash.\n"
            f"  Uses [bold]winget[/bold] (Windows Package Manager).\n",
            box=box.ROUNDED,
            border_style="yellow",
            padding=(1, 2),
        ))
        console.print()
        if Confirm.ask("  Auto-install missing requirements?", default=True):
            _auto_install(missing_min)

        # Re-check after install attempt
        console.clear()
        console.print(NEXUS_LOGO)
        console.print()

        rechecks = _run_checks()
        result2 = _render_checks(rechecks)

        still_missing = [n for n in MINIMUM_REQUIRED if n in result2 and not result2[n]]
        if still_missing:
            need = ", ".join(f"[bold cyan]{n}[/]" for n in still_missing)
            console.print(Panel(
                f"[bold red]✗  Still missing:[/bold red] {need}\n\n"
                f"  Please install manually:\n"
                f"  [cyan]Python:[/cyan] python.org/downloads\n"
                f"  [cyan]Git:[/cyan]   git-scm.com\n"
                f"  [cyan]Node.js:[/cyan] nodejs.org\n",
                box=box.ROUNDED,
                border_style="red",
                padding=(1, 2),
            ))
            console.print()
            return False

    # Check NEXUS update if installed
    nexus_ok, nexus_ver = check_nexus_installed()
    if nexus_ok:
        update_avail, latest_ver = check_nexus_update(nexus_ver)
        if update_avail:
            console.print(Panel(
                f"[bold cyan]⬆  NEXUS update available![/bold cyan]\n\n"
                f"  Installed: [bold]{nexus_ver}[/bold]\n"
                f"  Latest:    [bold green]{latest_ver}[/bold green]\n\n"
                f"  Run [bold]pip install --upgrade nexus-ai[/bold] to update.",
                box=box.ROUNDED,
                border_style="cyan",
                padding=(1, 2),
            ))
            console.print()
            if Confirm.ask("  Upgrade now?", default=True):
                console.print("\n  Upgrading NEXUS...")
                try:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--upgrade", "nexus-ai"],
                        capture_output=True, timeout=120,
                    )
                    console.print("  [bold green]✓[/] Upgrade complete!")
                except Exception as e:
                    console.print(f"  [yellow]⚠ Upgrade failed: {e}[/yellow]")
                console.print()

    status_ok("All checks passed!")
    console.print()
    return True


# ── Welcome ──────────────────────────────────────────────────

def welcome(root_dir: str) -> str:
    console.clear()
    console.print(NEXUS_LOGO)
    console.print()
    console.print(Panel(
        "[bold cyan]Welcome to NEXUS AI[/bold cyan]\n\n"
        "[white]Local-first autonomous AI agent framework[/white]\n\n"
        "Use [bold]↑↓[/bold] to navigate, [bold]Space[/bold] to select, [bold]Enter[/bold] to confirm.\n"
        "Each step is optional — you can skip anything and configure later.",
        box=box.ROUNDED,
        border_style="cyan",
        padding=(2, 3),
    ))
    console.print()

    existing_env = load_env(root_dir)
    provider_env_keys = [
        info.get("env_key", "")
        for info in PROVIDER_DEFS.values()
        if info.get("env_key")
    ]
    has_config = any(is_configured_secret(existing_env.get(key, "")) for key in provider_env_keys)

    if has_config:
        console.print(Panel(
            "[yellow]⚡ Existing configuration detected[/yellow]\n\n"
            f"Found [bold]{len(existing_env)}[/bold] environment variable(s).\n"
            "Run the wizard again to update your settings.",
            box=box.ROUNDED,
            border_style="yellow",
            padding=(1, 2),
        ))
        console.print()
        choice = select("Reconfigure?", ["Yes, run setup", "No, skip"])
        console.print()
        if choice == 1:
            status_dim("Setup skipped. Type [bold]python -m nexus[/bold] to start.")
            console.print()
            return "skip"

    choice = select("How would you like to set up?", [
        "🖥️  Local — personal use on this machine only",
        "🌐  Host — install as a server (others can connect)",
        "⚡  Quick start with defaults",
    ])
    console.print()
    return ["local", "host", "quick"][choice]


# ── Provider setup ───────────────────────────────────────────

def _detect_local_providers() -> Dict[str, str]:
    results = {}
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if r.status_code == 200:
            models = r.json().get("models", [])
            results["ollama"] = f"running ({len(models)} models)"
    except Exception:
        pass
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:1234/v1/models", timeout=2)
        if r.status_code == 200:
            results["lm_studio"] = "running"
    except Exception:
        pass
    return results


def _open_docs(url: str):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def _oauth_provider_id(provider_key: str) -> str:
    return OAUTH_PROVIDER_ALIASES.get(provider_key, provider_key)


async def _login_oauth_provider(provider_key: str, provider_name: str):
    from providers.oauth.providers.autoregister import register_all_oauth_providers
    from providers.oauth.registry import get_oauth_provider, get_oauth_providers
    from providers.oauth.storage import load_oauth_token_store
    from providers.oauth.types import OAuthAuthInfo, OAuthPrompt
    from providers.profiles import ProviderProfile, load_profile_store

    register_all_oauth_providers()
    oauth_id = _oauth_provider_id(provider_key)
    provider = get_oauth_provider(oauth_id)
    if provider is None:
        available = ", ".join(p.id for p in get_oauth_providers())
        raise RuntimeError(f"OAuth provider '{oauth_id}' is not registered. Available: {available}")

    class WizardCallbacks:
        def on_auth(self, *args):
            if len(args) == 1 and isinstance(args[0], OAuthAuthInfo):
                url = args[0].url
                instructions = args[0].instructions or ""
            else:
                url = str(args[0]) if args else ""
                instructions = str(args[1]) if len(args) > 1 else ""

            console.print()
            status_info(f"Open this login page: [bold cyan]{url}[/bold cyan]")
            if instructions:
                console.print(f"  [bold yellow]{instructions}[/bold yellow]")
            _open_docs(url)
            status_dim("Waiting for browser login to complete...")

        async def on_prompt(self, prompt) -> str:
            if isinstance(prompt, OAuthPrompt):
                message = prompt.message
                default = prompt.placeholder or ""
                allow_empty = prompt.allow_empty
            else:
                message = str(prompt)
                default = ""
                allow_empty = True

            if allow_empty or default:
                return Prompt.ask(f"  {message}", default=default).strip()
            return Prompt.ask(f"  {message}").strip()

        def on_progress(self, message: str) -> None:
            if message:
                status_dim(message)

        async def on_manual_code_input(self) -> Optional[str]:
            value = Prompt.ask("  Paste redirect URL/code if browser did not finish automatically", default="")
            return value.strip() or None

        async def on_select(self, prompt) -> Optional[str]:
            options = [opt.label for opt in prompt.options]
            sel = select(prompt.message, options)
            return prompt.options[sel].id

        @property
        def signal(self):
            return None

    credentials = await provider.login(WizardCallbacks())
    load_oauth_token_store().set(oauth_id, credentials)

    profile_store = load_profile_store()
    profile_store.add_profile(ProviderProfile(
        name="default",
        provider=provider_key,
        type="oauth",
        access=credentials.access,
        refresh=credentials.refresh,
        expires=credentials.expires,
        email=getattr(credentials, "email", None),
    ))

    if oauth_id != provider_key:
        profile_store.add_profile(ProviderProfile(
            name="default",
            provider=oauth_id,
            type="oauth",
            access=credentials.access,
            refresh=credentials.refresh,
            expires=credentials.expires,
            email=getattr(credentials, "email", None),
        ))

    return credentials, oauth_id


def login_oauth_provider(provider_key: str, provider_name: str):
    import asyncio

    try:
        return asyncio.run(_login_oauth_provider(provider_key, provider_name))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" not in str(exc):
            raise
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_login_oauth_provider(provider_key, provider_name))
        finally:
            loop.close()


def pick_provider(tier_choice: str = "") -> str:
    _s()
    wizard_header()

    if not tier_choice:
        tier_choice = select("Provider type", ["☁️  Cloud API", "🖥️  Local (Ollama, LM Studio, etc.)"])
        tier_choice = ["cloud", "local"][tier_choice]
        console.print()

    local = _detect_local_providers()
    if local:
        console.print("[dim]Auto-detected running locally:[/dim]")
        for name, status in local.items():
            info = PROVIDER_DEFS.get(name, {})
            console.print(f"  [green]●[/green] {info.get('name', name)} — [dim]{status}[/dim]")
        console.print()

    cloud_groups = {
        "API": "☁️  Cloud API",
        "OAuth": "🔑  OAuth / Browser Login",
        "Custom": "🔧  Custom / Universal",
    }

    rows = []
    for key, info in PROVIDER_DEFS.items():
        if info["tier"] != tier_choice:
            continue
        tag = info.get("tag", "")
        g = tag if tag in cloud_groups else ("API" if tier_choice == "cloud" else "Local")
        running = " ●" if key in local else ""
        rows.append((key, f"{info['name']}{running}", g))

    if tier_choice == "cloud" and any(r[2] != "API" for r in rows):
        rows.sort(key=lambda r: {
            "API": 0, "OAuth": 1, "Custom": 2, "Aggregator": 0, "Enterprise": 0,
            "Fast": 0, "Recommended": 0,
        }.get(r[2], 0))

    if not rows:
        status_info(f"No {tier_choice} providers configured.")
        return pick_provider()

    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for key, label, group in rows:
        grouped.setdefault(group, []).append((key, label))
    for g in grouped:
        grouped[g].sort(key=lambda x: x[1])

    provider_menu = []
    for g, items in grouped.items():
        gname = {"API": "☁️  Cloud API", "OAuth": "🔑  OAuth / Browser", "Custom": "🔧  Custom / Universal", "Local": "🖥️  Local Engines"}.get(g, g)
        for key, label in items:
            provider_menu.append((key, f"{gname} · {label}"))

    options = [label for _, label in provider_menu]
    sel = select("Pick a provider", options)
    console.print()
    chosen_key = provider_menu[sel][0]
    return chosen_key


def configure_provider(chosen: str, root_dir: str, env: Dict[str, str], provider_cfg: Dict[str, Any]) -> Tuple[str, str]:
    info = PROVIDER_DEFS[chosen]
    is_oauth = info.get("tag") == "OAuth"

    api_key = ""
    token_name = ""
    providers_config = provider_cfg.setdefault("providers", {})
    existing_provider = providers_config.get(chosen, {})
    if not isinstance(existing_provider, dict):
        existing_provider = {}

    if is_oauth:
        oauth_id = _oauth_provider_id(chosen)
        token_name = f"{chosen.upper()}_OAUTH_TOKEN"
        existing = env.get(token_name, "")
        if not is_configured_secret(existing):
            existing = ""
        console.print(f"\n  [yellow]🔑[/yellow] {info['name']} uses [bold]OAuth / browser login[/bold]")
        console.print("  NEXUS will open the browser, wait for login, and save the session automatically.")
        try:
            credentials, oauth_id = login_oauth_provider(chosen, info["name"])
            api_key = credentials.access
            status_ok(f"Logged in to [bold]{info['name']}[/bold] via OAuth.")
        except Exception as e:
            status_fail(f"OAuth login failed: {e}")
            status_dim("Fallback: paste an access/session token manually.")
            if existing:
                masked = f"{existing[:12]}...{existing[-4:]}"
                status_info(f"Existing token: [bold]{masked}[/bold]")
                if Confirm.ask("  Reuse existing token?", default=True):
                    api_key = existing
            if not api_key:
                api_key = secret_input(f"  Paste {info['name']} token / session key")
                env[token_name] = api_key
    elif info["env_key"]:
        existing = str(existing_provider.get("api_key", "") or "").strip()
        if existing.startswith("${") and existing.endswith("}"):
            existing = env.get(existing[2:-1], "")
        if not existing:
            existing = env.get(info["env_key"], "")
        if not is_configured_secret(existing):
            existing = ""
        if existing:
            masked = f"{existing[:8]}...{existing[-4:]}"
            status_info(f"Existing key: [bold]{masked}[/bold]")
            if not Confirm.ask("  Change it?", default=False):
                api_key = existing
        if not api_key:
            console.print(f"\n  [yellow]📋[/yellow] Get your key: [cyan]{info['docs']}[/cyan]")
            if Confirm.ask("  Open docs page in browser?", default=True):
                _open_docs(info["docs"])
            console.print()
            api_key = secret_input(f"Enter {info['name']} API key")

    model = info["models"][0]
    if len(info["models"]) > 1 and info["models"][0] not in ("auto-detect", "auto"):
        console.print("\n[dim]Models:[/dim]")
        for i, m in enumerate(info["models"], 1):
            marker = " [default]" if i == 1 else ""
            console.print(f"  [cyan]{i}[/cyan]. {m}{marker}")
        raw = Prompt.ask("  Pick model", default="1")
        if raw.isdigit():
            idx = int(raw) - 1
            model = info["models"][max(0, min(idx, len(info["models"]) - 1))]
        elif raw in info["models"]:
            model = raw
    elif info["models"][0] in ("auto-detect", "auto"):
        d = info["models"][0]
        model = Prompt.ask("  Model name", default=d) or d

    endpoint = info["endpoint"]
    if not is_oauth and endpoint:
        if not Confirm.ask("  Use default endpoint?", default=True):
            endpoint = Prompt.ask("  Endpoint URL", default=endpoint)

    entry: Dict[str, Any] = {
        "model": model,
        "temperature": 0.7,
        "max_tokens": 8192 if chosen == "deepseek" else 4096,
    }
    if endpoint:
        entry["endpoint"] = endpoint
    if not is_oauth and api_key:
        env_key = str(info.get("env_key") or "").strip()
        if env_key:
            env[env_key] = api_key
            entry["api_key"] = f"${{{env_key}}}"
        else:
            entry["api_key"] = api_key
    if is_oauth and token_name:
        entry["auth_type"] = "oauth"
        entry["oauth_provider"] = _oauth_provider_id(chosen)
        entry["token_env"] = token_name
    providers_config[chosen] = entry
    provider_cfg["version"] = "1.1.0"
    provider_cfg["default_provider"] = chosen
    fallback = provider_cfg.setdefault("fallback_chain", [])
    if chosen not in fallback:
        fallback.insert(0, chosen)

    console.print()
    status_ok(f"[bold]{info['name']}[/bold] is your primary provider.")
    return model, api_key


# ── Gateway setup ────────────────────────────────────────────

def configure_gateways(root_dir: str, env: Dict[str, str]):
    _s()
    wizard_header()

    sel = select("Set up messaging gateways?", ["Yes", "No (skip)"])
    console.print()
    if sel == 1:
        status_dim("Skipped. Configure later with [bold]python -m nexus --gateway[/bold]")
        console.print()
        return

    for gw_name, gw_info in GATEWAY_DEFS.items():
        icon = gw_info.get("icon", "•")
        console.print()
        sel = select(f"{icon} Configure {gw_name}?", ["Yes", "No (skip)"])
        if sel == 1:
            continue
        console.print(f"  [yellow]📋[/yellow] Docs: [cyan]{gw_info['docs']}[/cyan]")
        sel = select("Open docs page in browser?", ["Yes", "No"])
        if sel == 0:
            _open_docs(gw_info["docs"])
        console.print()
        existing = env.get(gw_info["env_key"], "")
        if not is_configured_secret(existing):
            existing = ""
        token = ""
        if existing:
            masked = f"{existing[:8]}...{existing[-4:]}"
            status_info(f"Existing token: [bold]{masked}[/bold]")
            sel = select("Change token?", ["Yes", "No"])
            if sel == 0:
                token = secret_input(f"  Enter {gw_name} bot token")
                env[gw_info["env_key"]] = token
            else:
                token = existing
        if not token:
            token = secret_input(f"  Enter {gw_name} bot token")
            env[gw_info["env_key"]] = token

        ids = Prompt.ask("  Allowed user IDs", default="*")
        if ids:
            env[f"ALLOWED_{gw_name.upper()}_IDS"] = ids

    save_env(root_dir, env)
    status_ok("Gateways configured!")


# ── Sandbox setup ────────────────────────────────────────────

SANDBOX_TIERS = [
    ("no_sandbox", "🟢 No sandbox", "Direct execution, fast — no isolation"),
    ("normal",     "🟡 Simple sandbox", "Restricted shell, stripped env, 5-min timeout"),
    ("docker",     "🔴 Docker sandbox", "Full container isolation via Docker (advanced)"),
]


def configure_sandbox(root_dir: str):
    _s()
    wizard_header()

    options = [f"{label} — {desc}" for key, label, desc in SANDBOX_TIERS]
    sel = select("Pick sandbox level", options)
    chosen = SANDBOX_TIERS[sel][0]

    env_path = Path(root_dir) / "config" / ".env"
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for line in env_lines:
        if line.startswith("NEXUS_SANDBOX_TIER="):
            new_lines.append(f"NEXUS_SANDBOX_TIER={chosen}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"NEXUS_SANDBOX_TIER={chosen}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    settings_path = Path(root_dir) / "config" / "settings.yml"
    if settings_path.exists():
        import yaml
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        safety = settings.setdefault("safety", {})
        safety["sandbox_enabled"] = chosen != "no_sandbox"
        safety["sandbox_tier"] = chosen
        settings_path.write_text(yaml.dump(settings, default_flow_style=False, sort_keys=False), encoding="utf-8")

    tier_name = dict((t[0], t[1]) for t in SANDBOX_TIERS)[chosen]
    console.print()
    status_ok(f"Sandbox set to [bold]{tier_name}[/bold]")
    console.print()


# ── Profile setup ────────────────────────────────────────────

def configure_profile(root_dir: str):
    _s()
    wizard_header()

    try:
        from config.profiles import create_profile, list_profiles, switch_profile
    except ImportError:
        status_info("Profile system not available — skipping.")
        console.print()
        return

    profiles = list_profiles()
    if profiles:
        names = ", ".join(p["name"] for p in profiles)
        status_info(f"Existing profiles: [bold]{names}[/bold]")
        if not Confirm.ask("  Create another?", default=False):
            console.print()
            return

    if Confirm.ask("  Create a profile?", default=True):
        name = Prompt.ask("  Profile name", default="default")
        desc = Prompt.ask("  Description", default="My NEXUS profile")
        try:
            create_profile(name, description=desc)
            switch_profile(name)
            status_ok(f"Profile [bold]'{name}'[/bold] created and activated!")
        except Exception as e:
            status_fail(f"Failed: {e}")

    console.print()


# ── Skills, Tools, Plugins, MCP, Hive ────────────────────────

def _prompt_enable(name: str, desc: str, default: bool = True) -> bool:
    console.print(f"  [cyan]{name}[/cyan] — [dim]{desc}[/dim]")
    return Confirm.ask(f"    Enable [bold]{name}[/bold]?", default=default)


def _preview_names(items: List[str], limit: int = 8) -> str:
    if not items:
        return ""
    shown = ", ".join(items[:limit])
    extra = len(items) - limit
    if extra > 0:
        shown += f", +{extra} more"
    return shown


def _bulk_enable(
    section: str,
    items: List[Tuple[str, str]],
    default: bool = True,
    current: Optional[List[str]] = None,
) -> Optional[List[str]]:
    if not items:
        status_info(f"  No {section.lower()} found")
        return []

    console.print(f"  Found [bold]{len(items)}[/bold] {section.lower()}: [dim]{_preview_names([name for name, _ in items])}[/dim]")
    item_names = [name for name, _ in items]
    if current is not None:
        default_indexes = [idx for idx, name in enumerate(item_names) if name in set(current)]
    else:
        default_indexes = list(range(len(items))) if default else []

    options = [f"{name} — {desc}" if desc else name for name, desc in items]
    picked = multi_select(
        f"{section}: Space toggles, Enter saves",
        options,
        default_selected=default_indexes,
    )
    if picked is None:
        status_dim(f"  Back — kept existing {section.lower()} selection")
        return None

    enabled = [item_names[idx] for idx in picked]
    if enabled:
        status_ok(f"  Enabled {len(enabled)} {section.lower()}")
    else:
        status_dim(f"  No {section.lower()} enabled")
    return enabled


def configure_extensions(root_dir: str):
    _s()
    wizard_header()

    settings_path = Path(root_dir) / "config" / "settings.yml"
    settings: Dict[str, Any] = {}
    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}
    extensions = settings.setdefault("extensions", {})

    # ── Skills ──
    console.print("[bold]📐 Skills[/bold]")
    try:
        from skills.registry import SkillRegistry
        skills = SkillRegistry(root_dir).discover()
    except ImportError:
        skills = []
    skill_items = [(s.id, f"{s.name} — {s.description}") for s in skills]
    selected = _bulk_enable("Skills", skill_items, default=True, current=extensions.get("skills"))
    if selected is not None:
        extensions["skills"] = selected
    console.print()

    # ── Tools ──
    console.print("[bold]🔧 Tools[/bold]")
    try:
        from tools.nexus_tools.registry import ToolRegistry
        tools_reg = ToolRegistry(root_dir)
        all_tools = tools_reg.list_tools(include_unavailable=True)
    except ImportError:
        all_tools = {}
    tool_items = [(name, meta.get("description", "")) for name, meta in all_tools.items()]
    selected = _bulk_enable("Tools", tool_items, default=True, current=extensions.get("tools"))
    if selected is not None:
        extensions["tools"] = selected
    console.print()

    # ── Plugins ──
    console.print("[bold]🔌 Plugins[/bold]")
    try:
        from plugins.manager import PluginManager
        pm = PluginManager(root_dir)
        plugins = pm.list_plugins() if hasattr(pm, 'list_plugins') else pm.discover_plugins()
    except (ImportError, Exception):
        plugins = []
    plugin_items = [
        (p.get("name", p.get("id", "?")), p.get("description", ""))
        for p in plugins
    ]
    selected = _bulk_enable("Plugins", plugin_items, default=True, current=extensions.get("plugins"))
    if selected is not None:
        extensions["plugins"] = selected
    console.print()

    # ── MCP Servers ──
    console.print("[bold]🔗 MCP Servers[/bold]")
    try:
        from mcp.catalog.scripts.catalog import MCPServerCatalog
        catalog = MCPServerCatalog(root_dir)
        servers = catalog.list_servers()
    except (ImportError, Exception):
        servers = []
    mcp_items = []
    for s in servers:
        name = s.get("name", s.get("id", "?"))
        desc = s.get("description", "")
        mcp_items.append((name, desc))
    if not servers:
        try:
            catalog_dir = Path(root_dir) / "mcp" / "catalog"
            if catalog_dir.exists():
                builtin = catalog.builtin_servers() if hasattr(catalog, 'builtin_servers') else []
                for s in builtin:
                    mcp_items.append((s.name, "Built-in MCP server"))
        except Exception:
            pass
    selected = _bulk_enable("MCP servers", mcp_items, default=True, current=extensions.get("mcp_servers"))
    if selected is not None:
        extensions["mcp_servers"] = selected
    console.print()

    # ── Hive ──
    console.print("[bold]🐝 Hive (Sub-Agents)[/bold]")
    console.print()
    hive_current = ["hive"] if extensions.get("hive", True) else []
    hive_selected = _bulk_enable(
        "Hive",
        [("hive", "Sub-agent engine for spawn_agent, spawn_hive, and consolidation")],
        default=True,
        current=hive_current,
    )
    hive_enabled = extensions.get("hive", True) if hive_selected is None else "hive" in hive_selected
    extensions["hive"] = hive_enabled
    if hive_enabled:
        status_ok("  Hive engine enabled")
    else:
        status_dim("  Hive engine disabled")
    console.print()

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(yaml.dump(settings, default_flow_style=False, sort_keys=False), encoding="utf-8")
    status_ok("Extensions configured")
    status_dim(f"Saved extension choices to [bold]{settings_path}[/bold]")
    console.print()


# ── Fallback chain ───────────────────────────────────────────

def configure_fallback(root_dir: str, provider_cfg: Dict[str, Any], current: str):
    _s()
    wizard_header()

    cloud = [k for k, v in PROVIDER_DEFS.items() if v["tier"] == "cloud" and k != current]
    local = [k for k, v in PROVIDER_DEFS.items() if v["tier"] == "local"]

    console.print(f"[dim]Primary: [bold]{PROVIDER_DEFS[current]['name']}[/bold][/dim]")
    console.print("[dim]If the primary provider fails, NEXUS will try these in order:[/dim]")
    console.print()

    if not Confirm.ask("  Configure fallback chain?", default=False):
        status_dim("Using default fallback chain")
        console.print()
        return

    picked = []
    for pool_name, pool in [("Cloud", cloud), ("Local", local)]:
        if not pool:
            continue
        sel = select(f"Add {pool_name} fallbacks?", ["Yes, pick some", "No"])
        console.print()
        if sel == 0:
            [f"{PROVIDER_DEFS[k]['name']}" for k in pool]
            selections = []
            for i, key in enumerate(pool):
                if Confirm.ask(f"  Add {PROVIDER_DEFS[key]['name']}?", default=False):
                    selections.append(key)
                console.print()
            picked.extend(selections)

    if picked:
        provider_cfg.setdefault("fallback_chain", [current] + picked)
        status_ok(f"Fallback chain: {' → '.join(PROVIDER_DEFS[k]['name'] for k in [current] + picked)}")
    else:
        provider_cfg.setdefault("fallback_chain", [current])
        status_dim("No fallbacks configured")
    console.print()


THEME_PRESETS = {
    "dark": {
        "name": "🌙  Dark (default)",
        "primary": "bold magenta",
        "accent": "bold cyan",
        "success": "bold green",
        "panel_border": "cyan",
    },
    "light": {
        "name": "☀️  Light",
        "primary": "bold blue",
        "accent": "bold cyan",
        "success": "green",
        "panel_border": "blue",
    },
    "neon": {
        "name": "💚  Neon",
        "primary": "bold green",
        "accent": "bold yellow",
        "success": "bold green",
        "panel_border": "green",
    },
    "ocean": {
        "name": "🌊  Ocean",
        "primary": "bold blue",
        "accent": "cyan",
        "success": "green",
        "panel_border": "blue",
    },
    "sunset": {
        "name": "🌅  Sunset",
        "primary": "bold red",
        "accent": "bold yellow",
        "success": "bold green",
        "panel_border": "red",
    },
}


def configure_system(root_dir: str):
    _s()
    wizard_header()

    settings_path = Path(root_dir) / "config" / "settings.yml"
    settings: Dict[str, Any] = {}
    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}

    # ── Theme ──
    console.print("[bold]🎨 Theme[/bold]")
    sel = select("Pick a color theme", [v["name"] for k, v in THEME_PRESETS.items()])
    console.print()
    chosen_theme = list(THEME_PRESETS.keys())[sel]
    theme = THEME_PRESETS[chosen_theme]
    settings.setdefault("theme", {})
    settings["theme"]["name"] = chosen_theme
    for k in ("primary", "accent", "success", "panel_border"):
        settings["theme"][k] = theme[k]

    # ── Model defaults ──
    console.print("[bold]🤖 Model Defaults[/bold]")
    settings["temperature"] = ask_float("  Temperature (0.0 = precise, 2.0 = creative)", "0.7", 0.0, 2.0)
    settings["max_tokens"] = ask_int("  Max tokens per response", "4096", 256, 128000)
    settings["max_turns"] = ask_int("  Max turns per task (1-50)", "10", 1, 50)
    console.print()

    # ── Behavior ──
    console.print("[bold]🧠 Behavior[/bold]")
    thinking_on = Confirm.ask("  Enable thinking mode? (shows AI reasoning)", default=True)
    settings["thinking_mode"] = thinking_on

    perm_options = [
        ("auto", "🤖  Auto — AI decides when to ask"),
        ("approve", "✅  Approve — always ask before actions"),
        ("dontAsk", "🚀  Don't ask — fully autonomous"),
    ]
    sel = select("Permission mode", [label for _, label in perm_options])
    console.print()
    settings["permission_mode"] = perm_options[sel][0]

    auto_save = Confirm.ask("  Auto-save conversations?", default=True)
    settings["auto_save"] = auto_save
    console.print()

    # ── Privacy ──
    console.print("[bold]🛡️  Privacy[/bold]")
    check_updates = Confirm.ask("  Check for updates on startup?", default=True)
    settings["check_updates"] = check_updates

    telemetry = select("Send anonymous usage data?", ["No thanks", "Yes, help improve NEXUS"])
    console.print()
    settings["telemetry"] = telemetry == 1

    log_options = [
        ("INFO", "📝  Info — normal logging"),
        ("DEBUG", "🔍  Debug — verbose (for troubleshooting)"),
        ("WARNING", "⚠️  Warnings only"),
        ("ERROR", "❌  Errors only"),
    ]
    sel = select("Log level", [label for _, label in log_options])
    console.print()
    settings["log_level"] = log_options[sel][0]

    lang = Prompt.ask("  Language (en, ja, zh, es, fr, de, etc.)", default="en")
    settings["language"] = lang if lang else "en"
    console.print()

    # ── Advanced ──
    console.print("[bold]⚡ Advanced[/bold]")
    if Confirm.ask("  Configure advanced settings?", default=False):
        sandbox_default = select("Default sandbox tier", [
            "🟢  None — no restrictions",
            "🟡  Normal — restricted shell, timeout",
            "🔴  Docker — full container isolation",
        ])
        console.print()
        settings["sandbox_tier"] = ["none", "normal", "docker"][sandbox_default]

        settings["gateway_port"] = ask_int("  Gateway port", "18789", 1024, 65535)

        settings["memory_retention_days"] = ask_int("  Memory retention (days)", "90", 1, 365)

        if Confirm.ask("  Auto-approve read-only commands? (ls, cat, grep, etc.)", default=True):
            settings["auto_approve_readonly"] = True

        console.print()
        compact = Confirm.ask("  Compact UI mode? (less spacing)", default=False)
        settings["compact_ui"] = compact

        show_tokens = Confirm.ask("  Show token usage per response?", default=False)
        settings["show_token_usage"] = show_tokens

        console.print()
        if Confirm.ask("  Schedule daily backup of config?", default=False):
            settings["backup_enabled"] = True
            settings["backup_keep_count"] = ask_int("  Keep how many backups?", "7", 1, 90)

    # ── Save ──
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, default_flow_style=False, sort_keys=False)

    status_ok(f"System configured — {theme['name']} | temp {settings['temperature']} | {settings['permission_mode']} mode")
    console.print()


# ── Knowledge init ───────────────────────────────────────────

def init_knowledge(root_dir: str):
    _s()
    wizard_header()

    if not Confirm.ask("  Index project files for RAG search?", default=False):
        status_dim("Skipped — run [bold]python scripts/rag_wrapper.py index[/bold] later")
        console.print()
        return

    try:
        from rag.engine import NexusAtlasRAG
        rag = NexusAtlasRAG(root_dir)
        indexed = rag.index_workspace()
        status_ok(f"Indexed {indexed} files into knowledge base")
    except Exception as e:
        status_fail(f"Indexing failed: {e}")
        status_dim("You can manually index via [bold]python scripts/rag_wrapper.py index[/bold]")
    console.print()


# ── Cost controls ────────────────────────────────────────────

def configure_costs(root_dir: str):
    _s()
    wizard_header()

    if not Confirm.ask("  Set a monthly spend limit?", default=False):
        status_dim("No limits — monitor usage via /status in the TUI")
        console.print()
        return

    limit = Prompt.ask("  Monthly budget (USD)", default="50")
    alert = Prompt.ask("  Alert at (%)", default="80")

    env_path = Path(root_dir) / "config" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\nNEXUS_MONTHLY_BUDGET={limit}\n")
        f.write(f"NEXUS_BUDGET_ALERT_PCT={alert}\n")

    status_ok(f"Monthly budget set to ${limit} (alert at {alert}%)")
    console.print()

def verify_connection(root_dir: str, provider_info: Dict[str, Any]) -> bool:
    _s()
    wizard_header()

    if not Confirm.ask("  Run a connection test?", default=True):
        status_dim("Skipped. Test anytime by running a chat.")
        console.print()
        return True

    provider = provider_info.get("provider", "")
    api_key = provider_info.get("api_key", "")
    cfg = load_provider_yml(root_dir)
    prov_config = cfg.get("providers", {}).get(provider, {})
    model = prov_config.get("model", "auto")
    endpoint = prov_config.get("endpoint", "")
    info = PROVIDER_DEFS.get(provider, {})

    t = Table(box=box.SIMPLE, border_style="cyan", padding=(0, 1))
    t.add_column("Property", style="bold white", width=12)
    t.add_column("Value", style="dim")
    t.add_row("Provider", info.get("name", provider))
    t.add_row("Model", model)
    t.add_row("Endpoint", endpoint)
    console.print(t)
    console.print()

    progress = Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )
    with progress:
        progress.add_task("[cyan]Contacting provider...", total=None)
        success, message, elapsed = test_provider(provider, api_key, endpoint, model)

    if success:
        console.print()
        status_ok("Connection successful!")
        status_dim(f"Response: \"{message}\"")
        status_dim(f"Latency: [bold]{elapsed*1000:.0f}ms[/bold]")
        console.print()
        return True

    console.print()
    status_fail(f"Connection failed: {message}")
    if "HTTP 401" in message or "invalid" in message.lower() or "unauthorized" in message.lower():
        status_dim("The provider rejected the credential. Re-paste a fresh key/token and make sure it is active.")
    if elapsed > 0:
        status_dim(f"Latency: {elapsed*1000:.0f}ms")
    console.print()

    if Confirm.ask("  Try a different provider?", default=True):
        chosen = pick_provider()
        env = load_env(root_dir)
        cfg = load_provider_yml(root_dir)
        model, new_key = configure_provider(chosen, root_dir, env, cfg)
        save_env(root_dir, env)
        save_provider_yml(root_dir, cfg)
        return verify_connection(root_dir, {"provider": chosen, "api_key": new_key})

    return Confirm.ask("  Continue anyway?", default=True)


# ── Completion ───────────────────────────────────────────────

def finish(root_dir: str):
    global _STEP
    _STEP = _TOTAL
    mark_setup_complete(root_dir)
    wizard_header()

    # ── Load all configs ──
    env = load_env(root_dir)
    provider_cfg = load_provider_yml(root_dir)
    settings = {}
    settings_path = Path(root_dir) / "config" / "settings.yml"
    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as f:
            settings = yaml.safe_load(f) or {}

    # ── User identity ──
    user_name = "User"
    nexus_dir = Path(root_dir) / ".nexus"
    user_md = nexus_dir / "USER.md"
    if user_md.exists():
        for line in user_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("Name:"):
                user_name = line.split(":", 1)[1].strip()

    soul = nexus_dir / "SOUL.md"
    personality = soul.read_text(encoding="utf-8").strip()[:60] + "..." if soul.exists() else "—"

    # ── Provider info ──
    default_prov = provider_cfg.get("default_provider", "—")
    prov_info = PROVIDER_DEFS.get(default_prov, {})
    prov_name = prov_info.get("name", default_prov)
    prov_model = provider_cfg.get("providers", {}).get(default_prov, {}).get("model", "—")

    # ── Gateway info ──
    gateways_on = []
    for gw_name in list(GATEWAY_DEFS.keys()):
        icon = GATEWAY_DEFS[gw_name].get("icon", "•")
        gw_env_key = GATEWAY_DEFS[gw_name].get("env_key", "")
        if gw_env_key and is_configured_secret(env.get(gw_env_key)):
            gateways_on.append(f"{icon} {gw_name}")

    # ── Build summary table ──
    summary = Table(box=box.SIMPLE, border_style="cyan", padding=(0, 2), width=80)
    summary.add_column("Setting", style="bold white", width=22)
    summary.add_column("Value", style="white")

    summary.add_row("[bold]👤 User[/bold]", user_name)
    summary.add_row("[bold]🧠 Personality[/bold]", personality)

    theme_name = settings.get("theme", {}).get("name", "dark")
    summary.add_row("[bold]🎨 Theme[/bold]", theme_name)
    summary.add_row("[bold]🌡️  Temperature[/bold]", str(settings.get("temperature", "0.7")))
    summary.add_row("[bold]📐 Max tokens[/bold]", str(settings.get("max_tokens", "4096")))
    summary.add_row("[bold]🔄 Max turns[/bold]", str(settings.get("max_turns", "10")))
    summary.add_row("[bold]🧠 Thinking[/bold]", "ON" if settings.get("thinking_mode", True) else "OFF")
    summary.add_row("[bold]🛡️  Permission[/bold]", settings.get("permission_mode", "auto"))
    summary.add_row("[bold]💾 Auto-save[/bold]", "ON" if settings.get("auto_save", True) else "OFF")
    summary.add_row("[bold]🌐 Language[/bold]", settings.get("language", "en"))
    summary.add_row("[bold]📝 Log level[/bold]", settings.get("log_level", "INFO"))

    sandbox_tier = settings.get("sandbox_tier", env.get("NEXUS_SANDBOX_TIER", "normal"))
    summary.add_row("[bold]🛡️  Sandbox[/bold]", sandbox_tier)

    summary.add_row("[bold]🤖 Provider[/bold]", f"{prov_name} ({prov_model})")
    fallback = provider_cfg.get("fallback_chain", [])
    if len(fallback) > 1:
        fb_names = " → ".join(PROVIDER_DEFS.get(f, {}).get("name", f) for f in fallback[1:])
        summary.add_row("[bold]🔄 Fallback[/bold]", fb_names)

    if gateways_on:
        summary.add_row("[bold]📡 Gateways[/bold]", ", ".join(gateways_on))
    else:
        summary.add_row("[bold]📡 Gateways[/bold]", "None configured")

    budget = env.get("NEXUS_MONTHLY_BUDGET", "")
    pct = env.get("NEXUS_BUDGET_ALERT_PCT", "")
    if is_configured_secret(budget):
        summary.add_row("[bold]💰 Budget[/bold]", f"${budget}/mo (alert at {pct}%)")

    host_port = env.get("NEXUS_SERVER_PORT", "")
    if is_configured_secret(host_port):
        summary.add_row("[bold]🌐 Host port[/bold]", host_port)

    # ── Print summary ──
    console.print(Panel(
        "[bold green]SETUP COMPLETE! 🚀[/bold green]",
        box=box.ROUNDED,
        border_style="green",
        padding=(0, 1),
    ))
    console.print()
    console.print(summary)
    console.print()

    # ── Actions ──
    if Confirm.ask("  Export config to share with another machine?", default=False):
        default_path = str(Path(root_dir) / "nexus-config.zip")
        export_path = Prompt.ask("  Export path", default=default_path)
        try:
            import zipfile
            config_dir = Path(root_dir) / "config"
            with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in config_dir.iterdir():
                    if f.is_file() and f.suffix not in (".lock", ".log"):
                        zf.write(f, f.name)
            status_ok(f"Config exported to [bold]{export_path}[/bold]")
            status_dim("Copy this file to another machine and run [bold]python -m nexus --import <file>[/bold]")
        except Exception as e:
            status_fail(f"Export failed: {e}")
        console.print()

    if Confirm.ask("  Add NEXUS to startup (auto-launch on boot)?", default=False):
        try:
            startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            if startup_dir.exists():
                vbs_content = f'''CreateObject("Wscript.Shell").Run "{sys.executable} -m nexus", 0, False'''
                (startup_dir / "NEXUS_AI.launch.vbs").write_text(vbs_content)
                status_ok("Startup shortcut created!")
                status_dim(f"Path: [bold]{startup_dir / 'NEXUS_AI.launch.vbs'}[/bold]")
            else:
                status_info("Startup folder not found — skipping.")
        except Exception as e:
            status_fail(f"Startup setup failed: {e}")
        console.print()

    # ── Quick commands ──
    commands = Table(box=box.SIMPLE, border_style="cyan", padding=(0, 2))
    commands.add_column("Command", style="bold cyan", width=32)
    commands.add_column("What it does", style="white")
    commands.add_row("[bold]python -m nexus[/bold]", "Launch the TUI")
    commands.add_row("[bold]python -m nexus --gui[/bold]", "Open the web GUI")
    commands.add_row("[bold]python -m nexus --help[/bold]", "See all options")
    console.print(commands)
    console.print()

    status_dim("Need help? Run [bold]python -m nexus --help[/bold]")
    console.print()


# ── Identity & Personality ────────────────────────────────────

PERSONALITY_PRESETS = {
    "assistant": {
        "name": "🧑‍💼  Assistant",
        "soul": "You are a helpful, friendly AI assistant. Be concise, clear, and proactive. Always ask clarifying questions when needed.",
        "agents": "## Role\nYou are NEXUS, a general-purpose AI assistant.\n\n## Behavior\n- Be helpful and concise\n- Ask questions when instructions are unclear\n- Proactively suggest improvements\n- Use tools when they speed things up\n\n## Communication\n- Prefer short, direct answers\n- Use bullet points for lists\n- Ask before taking destructive actions",
    },
    "developer": {
        "name": "👩‍💻  Developer",
        "soul": "You are an expert software engineer. Write clean, idiomatic, well-structured code. Always explain your reasoning and consider edge cases.",
        "agents": "## Role\nYou are NEXUS, an expert software engineering assistant.\n\n## Behavior\n- Write clean, production-quality code\n- Always handle errors and edge cases\n- Follow existing code style and conventions\n- Run tests and lint before considering work done\n- Suggest architecture improvements when relevant\n\n## Communication\n- Explain the approach before writing code\n- Show diffs for changes\n- Flag potential bugs or security issues",
    },
    "writer": {
        "name": "✍️  Writer",
        "soul": "You are a creative writing assistant. Help with content creation, editing, and storytelling. Polish language and maintain consistent voice.",
        "agents": "## Role\nYou are NEXUS, a creative writing assistant.\n\n## Behavior\n- Focus on clarity and flow\n- Maintain consistent tone and voice\n- Offer multiple options for phrasing\n- Respect the user's style\n\n## Communication\n- Write in a natural, engaging style\n- Provide options when suggesting rewrites\n- Ask about audience and purpose",
    },
    "researcher": {
        "name": "🔬  Researcher",
        "soul": "You are a thorough research analyst. Dig deep, cite sources, and present balanced findings. Always distinguish facts from assumptions.",
        "agents": "## Role\nYou are NEXUS, a research analyst.\n\n## Behavior\n- Be thorough and methodical\n- Cite sources when possible\n- Distinguish confirmed facts from speculation\n- Present balanced perspectives\n- Use deep research tools when appropriate\n\n## Communication\n- Structure findings with clear sections\n- Use data and evidence\n- Note confidence levels",
    },
    "custom": {
        "name": "✨  Custom",
        "soul": "",
        "agents": "",
    },
}


def configure_identity(root_dir: str):
    _s()
    wizard_header()

    user_name = Prompt.ask("  What should I call you?", default="User")
    console.print()

    sel = select("Pick an agent personality", [v["name"] for k, v in PERSONALITY_PRESETS.items()])
    console.print()
    chosen_key = list(PERSONALITY_PRESETS.keys())[sel]
    preset = PERSONALITY_PRESETS[chosen_key]

    soul_content = preset["soul"]
    agents_content = preset["agents"]

    if chosen_key == "custom":
        console.print("[dim]Write a short description of how your agent should behave:[/dim]")
        soul_content = Prompt.ask("  Agent personality (SOUL.md)", default="You are a helpful AI assistant.")
        console.print()
        console.print("[dim]Write operating instructions for your agent:[/dim]")
        agents_content = Prompt.ask("  Operating manual (AGENTS.md)", default="## Role\nYou are NEXUS, a helpful AI assistant.\n\n## Behavior\n- Be concise and helpful\n- Ask clarifying questions\n- Proactively solve problems")

    nexus_dir = Path(root_dir) / ".nexus"
    nexus_dir.mkdir(parents=True, exist_ok=True)

    user_md = nexus_dir / "USER.md"
    user_md.write_text(f"# User\n\nName: {user_name}\n\n", encoding="utf-8")

    soul_md = nexus_dir / "SOUL.md"
    soul_md.write_text(soul_content.strip() + "\n", encoding="utf-8")

    agents_md = nexus_dir / "AGENTS.md"
    agents_md.write_text(agents_content.strip() + "\n", encoding="utf-8")

    status_ok(f"Identity saved — [bold]{user_name}[/bold] ({PERSONALITY_PRESETS[chosen_key]['name']})")
    console.print()


def init_workspace(root_dir: str):
    _s()
    wizard_header()

    dirs = [
        "workspace",
        "memory",
        "knowledge",
        "logs",
    ]
    nexus_dir = Path(root_dir) / ".nexus"

    for d in dirs:
        path = nexus_dir / d
        path.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]✓[/green] [dim]{path}[/dim]")

    readme = nexus_dir / "workspace" / "README.md"
    if not readme.exists():
        readme.write_text("# Workspace\n\nYour agent's working directory for generated files and outputs.\n", encoding="utf-8")

    mem_init = nexus_dir / "memory" / "MEMORY.md"
    if not mem_init.exists():
        mem_init.write_text("# Memory\n\nKey information and context from past sessions.\n", encoding="utf-8")

    console.print()
    status_ok("Workspace initialized")
    console.print()


# ── Main ─────────────────────────────────────────────────────

def run(root_dir: Optional[str] = None):
    global _STEP, _SETUP_MODE
    _STEP = 0
    _SETUP_MODE = ""
    register_steps()
    if root_dir is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if not system_check(root_dir):
        return

    mode = welcome(root_dir)
    if mode == "skip":
        return

    _SETUP_MODE = mode

    if mode == "quick":
        console.clear()
        console.print(NEXUS_LOGO)
        console.print()
        mark_setup_complete(root_dir, "quick")
        console.print("[yellow]Quick start — using default configuration[/yellow]")
        console.print("[dim]Saved. Next time, [bold]nexus[/bold] launches directly.[/dim]")
        console.print("[dim]Use [bold]nexus-setup[/bold] or [bold]nexus-configure[/bold] to configure later.[/dim]")
        console.print()
        return

    configure_identity(root_dir)

    init_workspace(root_dir)

    configure_system(root_dir)

    if mode == "host":
        env = load_env(root_dir)
        cfg = load_provider_yml(root_dir)

        configure_sandbox(root_dir)

        chosen = pick_provider()
        model, api_key = configure_provider(chosen, root_dir, env, cfg)
        save_env(root_dir, env)
        save_provider_yml(root_dir, cfg)
        provider_info = {"provider": chosen, "api_key": api_key}

        configure_gateways(root_dir, env)

        configure_profile(root_dir)

        configure_extensions(root_dir)
        configure_fallback(root_dir, cfg, chosen)
        init_knowledge(root_dir)
        configure_costs(root_dir)
        save_env(root_dir, env)
        save_provider_yml(root_dir, cfg)

        verify_connection(root_dir, provider_info)

        _s()
        wizard_header()
        sel = select("Enable API server for remote connections?", ["Yes, enable server", "No"])
        console.print()
        if sel == 0:
            server_port = Prompt.ask("  Server port", default="8000")
            sel = select("Require authentication token?", ["Yes, set a token", "No (open access)"])
            if sel == 0:
                server_token = secret_input("  Enter server API token")
                env["NEXUS_SERVER_TOKEN"] = server_token
                with open(Path(root_dir) / "config" / ".env", "a") as f:
                    f.write(f"\nNEXUS_SERVER_TOKEN={server_token}\n")
            env["NEXUS_SERVER_PORT"] = server_port
            with open(Path(root_dir) / "config" / ".env", "a") as f:
                f.write(f"NEXUS_SERVER_PORT={server_port}\n")
            status_ok(f"Server configured on port {server_port}")
            status_dim("Start with: [bold]python -m nexus --server[/bold]")
        console.print()

        finish(root_dir)
        return

    env = load_env(root_dir)
    cfg = load_provider_yml(root_dir)

    configure_sandbox(root_dir)

    chosen = pick_provider()
    model, api_key = configure_provider(chosen, root_dir, env, cfg)
    save_env(root_dir, env)
    save_provider_yml(root_dir, cfg)
    provider_info = {"provider": chosen, "api_key": api_key}

    configure_gateways(root_dir, env)

    configure_profile(root_dir)

    configure_extensions(root_dir)
    configure_fallback(root_dir, cfg, chosen)
    init_knowledge(root_dir)
    configure_costs(root_dir)
    save_env(root_dir, env)
    save_provider_yml(root_dir, cfg)

    verify_connection(root_dir, provider_info)

    finish(root_dir)


if __name__ == "__main__":
    run()
