"""Comprehensive /provider command for Nexus.

Supports three provider categories:
  - local:  Ollama, LM Studio, llama.cpp (on-device)
  - api:    OpenAI, Anthropic, DeepSeek, Groq, etc. (cloud API keys)
  - auth:   Copilot, Claude, Codex, Gemini, etc. (OAuth tokens)

Usage:
  /provider              — Show current provider + mode
  /provider list         — List all providers by category
  /provider local        — List local providers
  /provider api          — List API providers
  /provider auth         — List auth providers
  /provider <name>       — Switch to provider
  /provider test [name]  — Test connection
  /provider profiles [name] — Show profiles
  /provider mode <mode>  — Set brain mode (LOCAL/CLOUD/HYBRID/AUTO)
  /provider health       — Show health stats
  /provider fallback     — Show/set fallback chain
  /provider reset        — Reset to default
  /provider setup <name> — Interactive setup wizard
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from nexus.commands import CommandResult


# ── Category Definitions ────────────────────────────────────────────────

LOCAL_PROVIDERS = {
    "ollama": {"name": "Ollama", "endpoint": "http://127.0.0.1:11434", "desc": "Local models via Ollama"},
    "lm_studio": {"name": "LM Studio", "endpoint": "http://127.0.0.1:1234", "desc": "Local models via LM Studio"},
    "llama_cpp": {"name": "llama.cpp", "endpoint": "http://127.0.0.1:8080", "desc": "Local models via llama.cpp"},
}

API_PROVIDERS = {
    "openai": {"name": "OpenAI", "env": "OPENAI_API_KEY", "desc": "GPT-4o, GPT-4, o1"},
    "anthropic": {"name": "Anthropic", "env": "ANTHROPIC_API_KEY", "desc": "Claude 3.5, Claude 4"},
    "deepseek": {"name": "DeepSeek", "env": "DEEPSEEK_API_KEY", "desc": "DeepSeek Chat/Reasoner"},
    "openrouter": {"name": "OpenRouter", "env": "OPENROUTER_API_KEY", "desc": "Multi-model gateway"},
    "groq": {"name": "Groq", "env": "GROQ_API_KEY", "desc": "Fast inference (Llama, Mixtral)"},
    "mistral": {"name": "Mistral", "env": "MISTRAL_API_KEY", "desc": "Mistral Large/Medium"},
    "qwen": {"name": "Qwen", "env": "QWEN_API_KEY", "desc": "Alibaba Qwen models"},
    "xai": {"name": "xAI", "env": "XAI_API_KEY", "desc": "Grok models"},
    "cohere": {"name": "Cohere", "env": "COHERE_API_KEY", "desc": "Command R+"},
    "google_gemini": {"name": "Google Gemini", "env": "GOOGLE_API_KEY", "desc": "Gemini 1.5/2.0"},
    "fireworks": {"name": "Fireworks", "env": "FIREWORKS_API_KEY", "desc": "Fast hosted models"},
    "together": {"name": "Together", "env": "TOGETHER_API_KEY", "desc": "Together AI"},
    "huggingface": {"name": "HuggingFace", "env": "HF_API_KEY", "desc": "HF Inference API"},
    "sambanova": {"name": "SambaNova", "env": "SAMBANOVA_API_KEY", "desc": "SambaNova fast inference"},
    "nvidia": {"name": "NVIDIA", "env": "NVIDIA_API_KEY", "desc": "NVIDIA NIM"},
    "perplexity": {"name": "Perplexity", "env": "PERPLEXITY_API_KEY", "desc": "Perplexity AI"},
    "replicate": {"name": "Replicate", "env": "REPLICATE_API_TOKEN", "desc": "Replicate models"},
    "azure_openai": {"name": "Azure OpenAI", "env": "AZURE_OPENAI_API_KEY", "desc": "Azure-hosted OpenAI"},
    "deepinfra": {"name": "DeepInfra", "env": "DEEPINFRA_API_KEY", "desc": "DeepInfra hosting"},
    "zupra": {"name": "Zupra", "env": "ZUPRA_API_KEY", "desc": "Zupra API"},
}

AUTH_PROVIDERS = {
    "codex": {"name": "ChatGPT Plus/Pro", "desc": "OAuth via ChatGPT subscription"},
    "claude": {"name": "Claude Pro/Max", "desc": "OAuth via Claude subscription"},
    "github_copilot": {"name": "GitHub Copilot", "desc": "OAuth via GitHub Copilot"},
    "gemini": {"name": "Google Gemini", "desc": "OAuth via Google account"},
    "grok": {"name": "xAI Grok", "desc": "OAuth via xAI"},
    "openrouter": {"name": "OpenRouter", "desc": "OAuth via OpenRouter"},
    "minimax": {"name": "MiniMax", "desc": "OAuth via MiniMax"},
    "chutes": {"name": "Chutes", "desc": "OAuth via Chutes.ai"},
    "qwen": {"name": "Qwen", "desc": "OAuth via Alibaba"},
}

ALL_CATEGORIES = {
    "local": LOCAL_PROVIDERS,
    "api": API_PROVIDERS,
    "auth": AUTH_PROVIDERS,
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _get_provider_factory():
    """Get the provider factory (safe for test environments)."""
    try:
        from models.providers.core.factory import NexusProviderFactory
        return NexusProviderFactory()
    except Exception:
        return None


def _get_config_loader():
    """Get the config loader."""
    try:
        from configure.config_loader import NexusConfigLoader
        return NexusConfigLoader()
    except Exception:
        return None


def _get_router():
    """Get the model router (safe)."""
    try:
        from models.providers.core.router import ModelRouter
        return ModelRouter()
    except Exception:
        return None


def _check_api_key(provider_id: str) -> bool:
    """Check if an API key is configured for a provider."""
    env_name = ""
    info = API_PROVIDERS.get(provider_id, {})
    env_name = info.get("env", "")
    if not env_name:
        env_name = f"{provider_id.upper()}_API_KEY"
    val = os.environ.get(env_name, "").strip()
    if val and "YOUR_" not in val:
        return True
    # Check config file
    loader = _get_config_loader()
    if loader:
        try:
            pcfg = loader.get_provider_config(provider_id)
            key = pcfg.get("api_key", "")
            if key and "YOUR_" not in key and not key.startswith("${"):
                return True
            if key.startswith("${") and key.endswith("}"):
                env_var = key[2:-1]
                if os.environ.get(env_var, "").strip():
                    return True
        except Exception:
            pass
    return False


def _check_oauth_token(provider_id: str) -> bool:
    """Check if an OAuth token exists for an auth provider."""
    try:
        from models.providers.auth.oauth.storage import load_oauth_token_store
        from models.providers.auth.oauth.providers.autoregister import register_all_oauth_providers
        register_all_oauth_providers()
        store = load_oauth_token_store()
        creds = store.get(provider_id)
        if creds is None:
            return False
        import time
        return time.time() * 1000 < creds.expires
    except Exception:
        return False


def _check_local_server(provider_id: str) -> bool:
    """Check if a local server is running (fast, 0.5s timeout)."""
    info = LOCAL_PROVIDERS.get(provider_id, {})
    endpoint = info.get("endpoint", "")
    if not endpoint:
        return False
    import socket
    try:
        # Quick TCP connect check (much faster than HTTP)
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _provider_status(provider_id: str, category: str) -> str:
    """Get human-readable status for a provider."""
    if category == "local":
        return "online" if _check_local_server(provider_id) else "offline"
    elif category == "api":
        return "configured" if _check_api_key(provider_id) else "no key"
    elif category == "auth":
        return "authenticated" if _check_oauth_token(provider_id) else "not logged in"
    return "unknown"


def _format_status(status: str) -> str:
    """Colorize status string."""
    if status in ("online", "configured", "authenticated"):
        return f"[green]{status}[/green]"
    elif status in ("offline", "no key", "not logged in"):
        return f"[red]{status}[/red]"
    return f"[yellow]{status}[/yellow]"


# ── Subcommand Implementations ──────────────────────────────────────────

def _show_current(ctx) -> CommandResult:
    """Show current provider status."""
    factory = _get_provider_factory()
    current = ctx.provider or "auto"
    group = "unknown"
    model = "unknown"
    mode = "AUTO"

    if factory:
        group = getattr(factory, "group", "cloud")
        name = getattr(factory, "name", current)
        if name:
            current = name

    # Get model from provider instance
    try:
        if factory:
            provider = factory.get_provider()
            model = getattr(provider, "model", "unknown")
    except Exception:
        pass

    # Get brain mode
    mode = os.environ.get("NEXUS_BRAIN_MODE", "AUTO").upper()

    # Get fallback chain
    loader = _get_config_loader()
    fallback = []
    if loader:
        try:
            pcfg = loader.get("provider", {})
            if isinstance(pcfg, dict):
                fallback = pcfg.get("fallback_chain", [])
        except Exception:
            pass

    lines = [
        f"  Provider:   {current}",
        f"  Group:      {group} (local/api/auth)",
        f"  Model:      {model}",
        f"  Brain Mode: {mode}",
        f"  Fallback:   {' -> '.join(fallback) if fallback else 'none'}",
    ]

    # Check if current provider is alive
    cat = "unknown"
    for c, providers in ALL_CATEGORIES.items():
        if current in providers:
            cat = c
            break
    if cat != "unknown":
        status = _provider_status(current, cat)
        lines.append(f'  Status:     {_format_status(status)}')

    return CommandResult(
        output=f"Provider: {current} ({group}, {mode})\n" + "\n".join(lines),
        formatted="[bold]Provider Status[/bold]\n" + "\n".join(lines),
        data={"provider": current, "group": group, "model": model, "mode": mode},
    )


def _list_all() -> CommandResult:
    """List all providers by category."""
    sections = []
    total = 0
    for cat_name, cat_providers in ALL_CATEGORIES.items():
        lines = []
        for pid, info in cat_providers.items():
            status = _provider_status(pid, cat_name)
            status_fmt = _format_status(status)
            name = info.get("name", pid)
            desc = info.get("desc", "")
            lines.append(f"  {pid:<20} {status_fmt:<25} {desc}")
            total += 1
        header = cat_name.upper()
        sections.append(f"[bold]{header}[/bold] ({len(cat_providers)})")
        sections.extend(lines)

    # Also list discovered providers from factory
    factory = _get_provider_factory()
    if factory:
        try:
            from models.providers.core.factory import MAPPINGS
            extra = [p for p in MAPPINGS if p not in LOCAL_PROVIDERS and p not in API_PROVIDERS and p not in AUTH_PROVIDERS]
            if extra:
                sections.append(f"\n[bold]UNIVERSAL[/bold] ({len(extra)}) — OpenAI-compatible, routed through UniversalProvider")
                for pid in sorted(extra)[:15]:
                    sections.append(f"  {pid:<20} [dim]universal[/dim]")
                if len(extra) > 15:
                    sections.append(f"  ... and {len(extra) - 15} more")
                total += len(extra)
        except Exception:
            pass

    return CommandResult(
        output=f"Providers ({total} total):\n" + "\n".join(sections),
        formatted=f"[bold]All Providers[/bold] ({total} total)\n" + "\n".join(sections),
        data={"total": total},
    )


def _list_category(category: str) -> CommandResult:
    """List providers in a specific category."""
    cat_providers = ALL_CATEGORIES.get(category)
    if not cat_providers:
        return CommandResult(
            output=f"Unknown category: {category}. Use: local, api, auth",
            success=False,
        )

    lines = []
    for pid, info in cat_providers.items():
        status = _provider_status(pid, category)
        status_fmt = _format_status(status)
        name = info.get("name", pid)
        desc = info.get("desc", "")
        endpoint = info.get("endpoint", "")
        env = info.get("env", "")
        extra = endpoint or env or ""
        lines.append(f"  {pid:<20} {status_fmt:<25} {desc}")
        if extra:
            lines.append(f"  {'':20} [dim]{extra}[/dim]")

    header = category.upper()
    return CommandResult(
        output=f"{header} Providers ({len(cat_providers)}):\n" + "\n".join(lines),
        formatted=f"[bold]{header} Providers[/bold] ({len(cat_providers)})\n" + "\n".join(lines),
        data={"category": category, "providers": list(cat_providers.keys())},
    )


def _switch_provider(name: str, ctx) -> CommandResult:
    """Switch to a different provider."""
    name = name.lower().replace("-", "_").strip()
    if not name:
        return CommandResult(output="Usage: /provider <name>", success=False)

    # Find which category it belongs to
    category = None
    for cat, providers in ALL_CATEGORIES.items():
        if name in providers:
            category = cat
            break

    # Also check universal mappings
    if not category:
        try:
            from models.providers.core.factory import MAPPINGS
            if name in MAPPINGS:
                category = "universal"
        except Exception:
            pass

    if not category:
        return CommandResult(
            output=f"Unknown provider: {name}\nUse /provider list to see available providers",
            success=False,
        )

    # Check if it's available
    if category == "local":
        if not _check_local_server(name):
            info = LOCAL_PROVIDERS[name]
            return CommandResult(
                output=f"⚠ {info['name']} is not running at {info['endpoint']}\nStart the server first, then switch.",
                formatted=f"[yellow]⚠ {info['name']} is not running[/yellow] at {info['endpoint']}\n[dim]Start the server first, then /provider {name}[/dim]",
                success=False,
            )
    elif category == "api":
        if not _check_api_key(name):
            info = API_PROVIDERS[name]
            env = info.get("env", f"{name.upper()}_API_KEY")
            return CommandResult(
                output=f"⚠ No API key for {info['name']}\nSet {env} or run /provider setup {name}",
                formatted=f"[yellow]⚠ No API key for {info['name']}[/yellow]\n[dim]Set {env} or /provider setup {name}[/dim]",
                success=False,
            )
    elif category == "auth":
        if not _check_oauth_token(name):
            info = AUTH_PROVIDERS[name]
            return CommandResult(
                output=f"⚠ Not logged in to {info['name']}\nRun /login {name} to authenticate",
                formatted=f"[yellow]⚠ Not logged in to {info['name']}[/yellow]\n[dim]Run /login {name} to authenticate[/dim]",
                success=False,
            )

    # Update runtime settings (legacy bridge path)
    if hasattr(ctx, 'extra') and isinstance(ctx.extra, dict):
        runtime = ctx.extra.get("runtime_settings")
        if isinstance(runtime, dict):
            runtime["provider"] = name
        ctx.extra["provider"] = name

    # Also try to set via factory
    factory = _get_provider_factory()
    if factory:
        try:
            factory.name = name
            factory.group = category if category != "universal" else "cloud"
        except Exception:
            pass

    # Try to set via shell
    if hasattr(ctx, 'shell') and ctx.shell:
        try:
            ctx.shell.provider = name
        except Exception:
            pass

    provider_info = (ALL_CATEGORIES.get(category) or {}).get(name, {})
    display_name = provider_info.get("name", name)

    return CommandResult(
        output=f"Switched to {display_name} ({category})",
        formatted=f"[green]✓ Switched to {display_name}[/green] [dim]({category})[/dim]",
        data={"provider": name, "category": category},
    )


def _test_provider(name: str) -> CommandResult:
    """Test connection to a provider."""
    name = name.lower().replace("-", "_").strip()
    if not name:
        return CommandResult(output="Usage: /provider test <name>", success=False)

    category = None
    for cat, providers in ALL_CATEGORIES.items():
        if name in providers:
            category = cat
            break

    if not category:
        return CommandResult(output=f"Unknown provider: {name}", success=False)

    results = []
    if category == "local":
        info = LOCAL_PROVIDERS[name]
        endpoint = info["endpoint"]
        online = _check_local_server(name)
        results.append(f"  Server:   {endpoint}")
        results.append(f"  Status:   {'✓ online' if online else '✗ offline'}")
        if online:
            # Try to list models
            try:
                import urllib.request
                for path in ("/v1/models", "/api/tags"):
                    try:
                        req = urllib.request.Request(f"{endpoint}{path}", method="GET")
                        resp = urllib.request.urlopen(req, timeout=3)
                        import json
                        data = json.loads(resp.read())
                        models = data.get("data", data.get("models", []))
                        if models:
                            model_names = [m.get("id", m.get("name", "?")) for m in models[:5]]
                            results.append(f"  Models:   {', '.join(model_names)}")
                            if len(models) > 5:
                                results.append(f"            ... and {len(models) - 5} more")
                        break
                    except Exception:
                        continue
            except Exception:
                pass

    elif category == "api":
        info = API_PROVIDERS[name]
        has_key = _check_api_key(name)
        results.append(f"  API Key:  {'✓ configured' if has_key else '✗ missing'}")
        if has_key:
            results.append(f"  Endpoint: {info.get('env', f'{name.upper()}_API_KEY')}")
            # Try a lightweight API call
            try:
                factory = _get_provider_factory()
                if factory:
                    provider = factory.get_provider_by_name("cloud", name)
                    if provider:
                        results.append(f"  Provider: ✓ loaded")
                        model = getattr(provider, "model", "default")
                        results.append(f"  Model:    {model}")
            except Exception as e:
                results.append(f"  Provider: ✗ {e}")

    elif category == "auth":
        info = AUTH_PROVIDERS[name]
        has_token = _check_oauth_token(name)
        results.append(f"  Token:    {'✓ valid' if has_token else '✗ not authenticated'}")
        if has_token:
            results.append(f"  Provider: {info['name']}")
        else:
            results.append(f"  Login:    /login {name}")

    return CommandResult(
        output=f"Test {name} ({category}):\n" + "\n".join(results),
        formatted=f"[bold]Test {name}[/bold] ({category})\n" + "\n".join(results),
        data={"provider": name, "category": category, "results": results},
    )


def _show_profiles(name: str) -> CommandResult:
    """Show profiles for a provider."""
    name = name.lower().replace("-", "_").strip() if name else ""
    try:
        from models.providers.core.profiles import load_profile_store
        store = load_profile_store()
        if name:
            profiles = store.list_profiles(name)
            if not profiles:
                return CommandResult(
                    output=f"No profiles for {name}",
                    formatted=f"[dim]No profiles configured for {name}[/dim]",
                )
            lines = []
            for p in profiles:
                pid = getattr(p, "name", getattr(p, "id", "?"))
                model = getattr(p, "model_id", getattr(p, "model", ""))
                endpoint = getattr(p, "endpoint", "")
                lines.append(f"  {pid:<20} model={model or 'default'}")
                if endpoint:
                    lines.append(f"  {'':20} endpoint={endpoint}")
            return CommandResult(
                output=f"Profiles for {name} ({len(profiles)}):\n" + "\n".join(lines),
                formatted=f"[bold]Profiles for {name}[/bold] ({len(profiles)})\n" + "\n".join(lines),
            )
        else:
            # List all profiles
            all_profiles = store.list_profiles()
            if not all_profiles:
                return CommandResult(output="No profiles configured", formatted="[dim]No profiles configured[/dim]")
            by_provider = {}
            for p in all_profiles:
                prov = getattr(p, "provider", "?")
                by_provider.setdefault(prov, []).append(p)
            sections = []
            for prov, profiles in sorted(by_provider.items()):
                sections.append(f"[bold]{prov}[/bold] ({len(profiles)})")
                for p in profiles:
                    pid = getattr(p, "name", getattr(p, "id", "?"))
                    model = getattr(p, "model_id", getattr(p, "model", ""))
                    sections.append(f"  {pid:<20} model={model or 'default'}")
            return CommandResult(
                output=f"All Profiles ({len(all_profiles)}):\n" + "\n".join(sections),
                formatted=f"[bold]All Profiles[/bold] ({len(all_profiles)})\n" + "\n".join(sections),
            )
    except Exception as e:
        return CommandResult(output=f"Profiles unavailable: {e}", success=False)


def _set_mode(mode: str) -> CommandResult:
    """Set the brain intelligence mode."""
    mode = mode.upper().strip()
    valid = {"LOCAL", "CLOUD", "HYBRID", "AUTO"}
    if mode not in valid:
        return CommandResult(
            output=f"Invalid mode: {mode}. Use: {', '.join(sorted(valid))}",
            success=False,
        )
    os.environ["NEXUS_BRAIN_MODE"] = mode

    # Also try to set on router
    router = _get_router()
    if router:
        try:
            router.set_mode(mode)
        except Exception:
            pass

    descriptions = {
        "LOCAL": "Prefer local models (Ollama, LM Studio)",
        "CLOUD": "Prefer cloud APIs (OpenAI, Anthropic, etc.)",
        "HYBRID": "Use local for simple tasks, cloud for complex",
        "AUTO": "Automatically select best provider per task",
    }

    return CommandResult(
        output=f"Brain Mode: {mode}\n  {descriptions[mode]}",
        formatted=f"[green]Brain Mode: {mode}[/green]\n  [dim]{descriptions[mode]}[/dim]",
        data={"mode": mode},
    )


def _show_health() -> CommandResult:
    """Show provider health statistics."""
    lines = []
    try:
        from models.providers.core.health import ProviderHealthRegistry
        from nexus.runtime.kernel import get_nexus_kernel
        kernel = get_nexus_kernel()
        root = getattr(kernel, "root", None) or os.getcwd()
        health_path = os.path.join(str(root), ".nexus", "provider_health.sqlite3")
        health = ProviderHealthRegistry(store_path=health_path)
        # Try to get stats
        if hasattr(health, "get_stats"):
            stats = health.get_stats()
            for k, v in (stats or {}).items():
                lines.append(f"  {k:<25} {v}")
    except Exception:
        pass

    if not lines:
        # Fallback: show basic info
        lines = [
            f"  Brain Mode:     {os.environ.get('NEXUS_BRAIN_MODE', 'AUTO')}",
            f"  Offline Mode:   {os.environ.get('NEXUS_OFFLINE_MODE', 'false')}",
        ]

        # Check each provider category
        for cat_name, cat_providers in ALL_CATEGORIES.items():
            online = sum(1 for pid in cat_providers if _provider_status(pid, cat_name) in ("online", "configured", "authenticated"))
            lines.append(f"  {cat_name.upper():<16} {online}/{len(cat_providers)} available")

    return CommandResult(
        output="Provider Health:\n" + "\n".join(lines),
        formatted="[bold]Provider Health[/bold]\n" + "\n".join(lines),
    )


def _show_fallback() -> CommandResult:
    """Show the fallback chain."""
    loader = _get_config_loader()
    fallback = []
    current = "unknown"
    if loader:
        try:
            pcfg = loader.get("provider", {})
            if isinstance(pcfg, dict):
                fallback = pcfg.get("fallback_chain", [])
                current = pcfg.get("default_provider", "unknown")
        except Exception:
            pass

    if not fallback:
        return CommandResult(
            output=f"Current: {current}\nFallback chain: not configured\nSet in configure/provider.yml under fallback_chain:",
            formatted=f"[bold]Fallback Chain[/bold]\n  Current: {current}\n  [dim]Not configured. Set in configure/provider.yml:[/dim]\n  [dim]fallback_chain:[/dim]\n  [dim]  - openai[/dim]\n  [dim]  - anthropic[/dim]\n  [dim]  - ollama[/dim]",
        )

    chain_display = " -> ".join(fallback)
    lines = [f"  Current:  {current}", f"  Chain:    {chain_display}"]
    for i, name in enumerate(fallback):
        cat = "unknown"
        for c, providers in ALL_CATEGORIES.items():
            if name in providers:
                cat = c
                break
        status = _provider_status(name, cat) if cat != "unknown" else "unknown"
        lines.append(f"  [{i+1}] {name:<20} {_format_status(status)}")

    return CommandResult(
        output=f"Fallback Chain:\n" + "\n".join(lines),
        formatted="[bold]Fallback Chain[/bold]\n" + "\n".join(lines),
        data={"fallback_chain": fallback},
    )


def _reset_provider() -> CommandResult:
    """Reset to default provider."""
    loader = _get_config_loader()
    default = "openrouter"
    if loader:
        try:
            pcfg = loader.get("provider", {})
            if isinstance(pcfg, dict):
                default = pcfg.get("default_provider", "openrouter")
        except Exception:
            pass

    factory = _get_provider_factory()
    if factory:
        try:
            factory.name = default
            group = "cloud"
            for cat, providers in ALL_CATEGORIES.items():
                if default in providers:
                    group = cat
                    break
            factory.group = group
        except Exception:
            pass

    return CommandResult(
        output=f"Reset to default: {default}",
        formatted=f"[green]Reset to default: {default}[/green]",
        data={"provider": default},
    )


def _setup_wizard(name: str) -> CommandResult:
    """Show setup instructions for a provider."""
    name = name.lower().replace("-", "_").strip()
    if not name:
        return CommandResult(output="Usage: /provider setup <name>", success=False)

    category = None
    info = {}
    for cat, providers in ALL_CATEGORIES.items():
        if name in providers:
            category = cat
            info = providers[name]
            break

    if not category:
        return CommandResult(output=f"Unknown provider: {name}", success=False)

    display_name = info.get("name", name)
    lines = [f"Setup {display_name} ({category}):"]

    if category == "local":
        lines.extend([
            f"  1. Install the server software",
            f"  2. Start it on {info.get('endpoint', 'localhost')}",
            f"  3. Run: /provider {name}",
            "",
            f"  Quick start:",
            f"    Ollama:    curl -fsSL https://ollama.com/install.sh | sh && ollama serve",
            f"    LM Studio: Download from lmstudio.ai, start the server",
            f"    llama.cpp: llama-server -m model.gguf",
        ])
    elif category == "api":
        env = info.get("env", f"{name.upper()}_API_KEY")
        lines.extend([
            f"  1. Get an API key from the provider",
            f"  2. Set environment variable:",
            f"     export {env}=your_key_here",
            f"  3. Run: /provider {name}",
            "",
            f"  Or add to configure/provider.yml:",
            f"  providers:",
            f"    {name}:",
            f"      api_key: your_key_here",
        ])
    elif category == "auth":
        lines.extend([
            f"  1. Run: /login {name}",
            f"  2. Follow the OAuth flow in your browser",
            f"  3. Token will be saved automatically",
            "",
            f"  Then: /provider {name}",
        ])

    return CommandResult(
        output="\n".join(lines),
        formatted="[bold]" + "\n".join(lines) + "[/bold]",
    )


# ── Main Entry Point ────────────────────────────────────────────────────

async def provider_command(ctx) -> CommandResult:
    """Main /provider command dispatcher."""
    args = ctx.extra.get("args", "") if hasattr(ctx, 'extra') else ""
    if isinstance(args, str):
        parts = args.split()
    else:
        parts = list(args or [])

    # Strip the command name itself
    subcmd = parts[1].lower() if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    if not subcmd or subcmd in ("status", "show", "current"):
        return _show_current(ctx)
    elif subcmd == "list":
        return _list_all()
    elif subcmd in ("local", "api", "auth"):
        return _list_category(subcmd)
    elif subcmd == "test":
        return _test_provider(rest)
    elif subcmd in ("profiles", "profile"):
        return _show_profiles(rest)
    elif subcmd == "mode":
        return _set_mode(rest)
    elif subcmd == "health":
        return _show_health()
    elif subcmd in ("fallback", "chain"):
        return _show_fallback()
    elif subcmd == "reset":
        return _reset_provider()
    elif subcmd == "setup":
        return _setup_wizard(rest)
    else:
        # Try to switch to the named provider
        return _switch_provider(subcmd, ctx)
