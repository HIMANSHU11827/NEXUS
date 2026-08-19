"""Comprehensive /models command for Nexus.

Lists available models per provider with context window, cost, and benchmarks.

Usage:
  /models                — Show current model
  /models list           — List all models by provider
  /models <provider>     — List models for a specific provider
  /models search <query> — Search models by name
  /models compare <m1> <m2> — Compare two models
  /models set <provider:model> — Switch model
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from nexus.commands import CommandResult


# ── Helpers ─────────────────────────────────────────────────────────────

def _get_config_loader():
    try:
        from configure.config_loader import NexusConfigLoader
        return NexusConfigLoader()
    except Exception:
        return None


def _get_model_caps():
    try:
        from models.providers.core.model_capabilities import ModelCapabilityRegistry
        loader = _get_config_loader()
        return ModelCapabilityRegistry.from_loader(loader)
    except Exception:
        return None


def _get_factory():
    try:
        from models.providers.core.factory import NexusProviderFactory
        return NexusProviderFactory()
    except Exception:
        return None


def _format_ctx_window(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens // 1_000}K"
    return str(tokens)


def _format_cost(cost: Optional[float]) -> str:
    if cost is None:
        return ""
    if cost == 0:
        return "free"
    return f"${cost:.2f}/1M"


# ── Subcommands ─────────────────────────────────────────────────────────

def _show_current(ctx) -> CommandResult:
    """Show current model and provider."""
    factory = _get_factory()
    current_provider = ctx.provider or "auto"
    current_model = "unknown"

    if factory:
        current_provider = getattr(factory, "name", current_provider)
        try:
            provider = factory.get_provider()
            current_model = getattr(provider, "model", "unknown")
        except Exception:
            pass

    mode = os.environ.get("NEXUS_BRAIN_MODE", "AUTO").upper()

    return CommandResult(
        output=f"Provider: {current_provider}\nModel:    {current_model}\nMode:     {mode}",
        formatted=f"[bold]Current Model[/bold]\n  Provider: [cyan]{current_provider}[/cyan]\n  Model:    [green]{current_model}[/green]\n  Mode:     [dim]{mode}[/dim]",
        data={"provider": current_provider, "model": current_model, "mode": mode},
    )


def _list_all_models() -> CommandResult:
    """List all models organized by provider."""
    loader = _get_config_loader()
    if not loader:
        return CommandResult(output="Config loader unavailable", success=False)

    provider_cfg = loader.get("provider", {})
    if not isinstance(provider_cfg, dict):
        return CommandResult(output="No provider config found", success=False)

    providers = provider_cfg.get("providers", {})
    caps = provider_cfg.get("model_capabilities", {})
    provider_caps = caps.get("providers", {})
    model_caps = caps.get("models", {})

    sections = []
    total = 0

    for prov_name, prov_data in sorted(providers.items()):
        if not isinstance(prov_data, dict):
            continue

        model = prov_data.get("model", "default")
        endpoint = prov_data.get("endpoint", "")
        ctx = prov_data.get("context_window") or provider_caps.get(prov_name, {}).get("context_window", "")
        cost = prov_data.get("cost_per_1m") or provider_caps.get(prov_name, {}).get("cost_per_1m")
        tools = provider_caps.get(prov_name, {}).get("tools", False)
        vision = provider_caps.get(prov_name, {}).get("vision", False)
        benchmarks = provider_caps.get(prov_name, {}).get("benchmarks", {})

        # Check if model-specific caps exist
        if model in model_caps:
            mc = model_caps[model]
            ctx = mc.get("context_window", ctx)
            tools = mc.get("tools", tools)
            vision = mc.get("vision", vision)

        ctx_str = _format_ctx_window(ctx) if ctx else ""
        cost_str = _format_cost(cost)
        features = []
        if tools:
            features.append("tools")
        if vision:
            features.append("vision")
        feature_str = ", ".join(features)

        lines = []
        lines.append(f"  {prov_name:<18} {model:<35} {ctx_str:<8} {cost_str:<12} {feature_str}")

        if endpoint:
            lines.append(f"  {'':18} [dim]{endpoint}[/dim]")

        if benchmarks:
            bench_str = " | ".join(f"{k}: {v}" for k, v in benchmarks.items())
            lines.append(f"  {'':18} [dim]{bench_str}[/dim]")

        sections.extend(lines)
        total += 1

    return CommandResult(
        output=f"Models ({total} providers):\n" + "\n".join(sections),
        formatted=f"[bold]All Models[/bold] ({total} providers)\n" + "\n".join(sections),
        data={"providers": total},
    )


def _list_provider_models(provider: str) -> CommandResult:
    """List models for a specific provider."""
    loader = _get_config_loader()
    if not loader:
        return CommandResult(output="Config loader unavailable", success=False)

    provider_cfg = loader.get("provider", {})
    providers = provider_cfg.get("providers", {})
    caps = provider_cfg.get("model_capabilities", {})
    provider_caps = caps.get("providers", {})
    model_caps = caps.get("models", {})

    if provider not in providers:
        return CommandResult(
            output=f"Unknown provider: {provider}\nUse /models list to see available providers",
            success=False,
        )

    prov_data = providers[provider]
    if not isinstance(prov_data, dict):
        return CommandResult(output=f"Invalid config for {provider}", success=False)

    model = prov_data.get("model", "default")
    endpoint = prov_data.get("endpoint", "")
    ctx = prov_data.get("context_window") or provider_caps.get(provider, {}).get("context_window", "")
    cost = prov_data.get("cost_per_1m") or provider_caps.get(provider, {}).get("cost_per_1m")
    tools = provider_caps.get(provider, {}).get("tools", False)
    vision = provider_caps.get(provider, {}).get("vision", False)
    streaming = provider_caps.get(provider, {}).get("streaming", True)
    structured = provider_caps.get(provider, {}).get("structured_output", False)
    benchmarks = provider_caps.get(provider, {}).get("benchmarks", {})

    if model in model_caps:
        mc = model_caps[model]
        ctx = mc.get("context_window", ctx)
        tools = mc.get("tools", tools)
        vision = mc.get("vision", vision)
        streaming = mc.get("streaming", streaming)
        structured = mc.get("structured_output", structured)

    lines = [
        f"  Provider:   {provider}",
        f"  Model:      {model}",
        f"  Endpoint:   {endpoint or 'default'}",
        f"  Context:    {_format_ctx_window(ctx) if ctx else 'unknown'}",
        f"  Cost:       {_format_cost(cost) or 'unknown'}",
        f"  Features:   {', '.join(f for f, v in [('tools', tools), ('vision', vision), ('streaming', streaming), ('structured', structured)] if v)}",
    ]

    if benchmarks:
        lines.append(f"  Benchmarks:")
        for k, v in benchmarks.items():
            bar_len = int(float(v) * 10)
            bar = "=" * bar_len + "-" * (10 - bar_len)
            lines.append(f"    {k:<15} [{bar}] {v}")

    return CommandResult(
        output=f"Model Details ({provider}):\n" + "\n".join(lines),
        formatted=f"[bold]Model Details[/bold] ({provider})\n" + "\n".join(lines),
        data={"provider": provider, "model": model},
    )


def _search_models(query: str) -> CommandResult:
    """Search models by name."""
    loader = _get_config_loader()
    if not loader:
        return CommandResult(output="Config loader unavailable", success=False)

    provider_cfg = loader.get("provider", {})
    providers = provider_cfg.get("providers", {})
    caps = provider_cfg.get("model_capabilities", {})
    provider_caps = caps.get("providers", {})

    query = query.lower()
    matches = []

    for prov_name, prov_data in providers.items():
        if not isinstance(prov_data, dict):
            continue
        model = prov_data.get("model", "")
        if query in prov_name.lower() or query in model.lower():
            ctx = provider_caps.get(prov_name, {}).get("context_window", "")
            ctx_str = _format_ctx_window(ctx) if ctx else ""
            matches.append(f"  {prov_name:<18} {model:<35} {ctx_str}")

    if not matches:
        return CommandResult(
            output=f"No models matching '{query}'",
            formatted=f"[dim]No models matching '{query}'[/dim]",
        )

    return CommandResult(
        output=f"Models matching '{query}' ({len(matches)}):\n" + "\n".join(matches),
        formatted=f"[bold]Search Results[/bold] ({len(matches)})\n" + "\n".join(matches),
    )


def _compare_models(m1: str, m2: str) -> CommandResult:
    """Compare two models."""
    loader = _get_config_loader()
    if not loader:
        return CommandResult(output="Config loader unavailable", success=False)

    provider_cfg = loader.get("provider", {})
    providers = provider_cfg.get("providers", {})
    caps = provider_cfg.get("model_capabilities", {})
    provider_caps = caps.get("providers", {})

    def get_model_info(name: str):
        for prov, data in providers.items():
            if not isinstance(data, dict):
                continue
            if prov == name or data.get("model", "") == name:
                return {
                    "provider": prov,
                    "model": data.get("model", ""),
                    "ctx": provider_caps.get(prov, {}).get("context_window", 0),
                    "cost": provider_caps.get(prov, {}).get("cost_per_1m"),
                    "tools": provider_caps.get(prov, {}).get("tools", False),
                    "benchmarks": provider_caps.get(prov, {}).get("benchmarks", {}),
                }
        return None

    info1 = get_model_info(m1)
    info2 = get_model_info(m2)

    if not info1:
        return CommandResult(output=f"Model not found: {m1}", success=False)
    if not info2:
        return CommandResult(output=f"Model not found: {m2}", success=False)

    lines = [
        f"  {'':20} {info1['provider']:<20} {info2['provider']:<20}",
        f"  {'Model':<20} {info1['model']:<20} {info2['model']:<20}",
        f"  {'Context':<20} {_format_ctx_window(info1['ctx']):<20} {_format_ctx_window(info2['ctx']):<20}",
        f"  {'Cost/1M':<20} {_format_cost(info1['cost']):<20} {_format_cost(info2['cost']):<20}",
        f"  {'Tools':<20} {str(info1['tools']):<20} {str(info2['tools']):<20}",
    ]

    if info1["benchmarks"] or info2["benchmarks"]:
        lines.append(f"\n  Benchmarks:")
        all_bench = set(info1["benchmarks"].keys()) | set(info2["benchmarks"].keys())
        for b in sorted(all_bench):
            v1 = info1["benchmarks"].get(b, "-")
            v2 = info2["benchmarks"].get(b, "-")
            lines.append(f"    {b:<15} {str(v1):<20} {str(v2):<20}")

    return CommandResult(
        output=f"Compare {m1} vs {m2}:\n" + "\n".join(lines),
        formatted=f"[bold]Compare[/bold] {m1} vs {m2}\n" + "\n".join(lines),
    )


def _set_model(spec: str, ctx) -> CommandResult:
    """Set model via provider:model format."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
    else:
        provider = spec
        model = ""

    provider = provider.lower().strip()
    model = model.strip()

    # Try to switch provider
    from nexus.commands_provider import _switch_provider
    result = _switch_provider(provider, ctx)
    if not result.success:
        return result

    # If model specified, try to set it
    if model:
        try:
            factory = _get_factory()
            if factory:
                provider_inst = factory.get_provider_by_name("cloud", provider)
                if provider_inst:
                    provider_inst.model = model
                    return CommandResult(
                        output=f"Model set to {provider}:{model}",
                        formatted=f"[green]Model set to {provider}:{model}[/green]",
                        data={"provider": provider, "model": model},
                    )
        except Exception as e:
            return CommandResult(
                output=f"Failed to set model: {e}",
                success=False,
            )

    return CommandResult(
        output=f"Provider set to {provider}",
        formatted=f"[green]Provider set to {provider}[/green]",
        data={"provider": provider},
    )


# ── Main Entry Point ────────────────────────────────────────────────────

async def models_command(ctx) -> CommandResult:
    """Main /models command dispatcher."""
    args = ctx.extra.get("args", "") if hasattr(ctx, 'extra') else ""
    if isinstance(args, str):
        parts = args.split()
    else:
        parts = list(args or [])

    subcmd = parts[1].lower() if len(parts) > 1 else ""
    rest = parts[2:] if len(parts) > 2 else []

    if not subcmd or subcmd in ("status", "show", "current"):
        return _show_current(ctx)
    elif subcmd == "list":
        return _list_all_models()
    elif subcmd == "search" and rest:
        return _search_models(" ".join(rest))
    elif subcmd == "compare" and len(rest) >= 2:
        return _compare_models(rest[0], rest[1])
    elif subcmd == "set" and rest:
        return _set_model(rest[0], ctx)
    else:
        # Try to list models for a specific provider
        return _list_provider_models(subcmd)
