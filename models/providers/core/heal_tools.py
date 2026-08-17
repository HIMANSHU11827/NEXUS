import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

_repair_tools: Dict[str, Callable] = {}


def register_repair_tool(name: str, fn: Callable, description: str = ""):
    _repair_tools[name] = fn
    logger.debug(f"[HEAL-TOOL] Registered: {name} — {description}")


def get_repair_tool(name: str) -> Optional[Callable]:
    return _repair_tools.get(name)


def list_repair_tools() -> List[str]:
    return list(_repair_tools.keys())


def call_repair_tool(name: str, **kwargs) -> Any:
    fn = _repair_tools.get(name)
    if not fn:
        logger.warning(f"[HEAL-TOOL] Unknown tool: {name}")
        return None
    try:
        return fn(**kwargs)
    except Exception as e:
        logger.error(f"[HEAL-TOOL] {name} failed: {e}")
        return None


def _heal_clear_cooldowns(**kwargs) -> str:
    from models.providers.core.profiles import load_profile_store
    store = load_profile_store()
    cleared = store.clear_expired_cooldowns()
    return f"cleared {cleared} expired cooldowns"


def _heal_refresh_oauth(provider_id: str = "", **kwargs) -> str:
    from providers.oauth.registry import get_oauth_provider
    from providers.oauth.storage import load_oauth_token_store
    store = load_oauth_token_store()
    if provider_id:
        targets = [provider_id]
    else:
        data = {}
        oauth_path = Path.home() / ".nexus" / "auth" / "oauth_store.json"
        if oauth_path.exists():
            import json
            data = json.loads(oauth_path.read_text())
        targets = list(data.keys()) if isinstance(data, dict) else []
    for pid in targets:
        creds = store.get(pid)
        if creds and creds.refresh:
            provider = get_oauth_provider(pid)
            if provider and creds.expires < time.time() * 1000 + 300000:
                class SilentCallbacks:
                    def on_auth(self, info): pass
                    async def on_prompt(self, prompt): return ""
                    def on_progress(self, msg): pass
                    async def on_manual_code_input(self): return None
                    async def on_select(self, prompt): return None
                    @property
                    def signal(self): return None
                import asyncio
                try:
                    new_creds = asyncio.run(provider.login(SilentCallbacks()))
                    store.set(pid, new_creds)
                except Exception:
                    logger.warning("providers/heal_tools.py:73 signal: suppressed error", exc_info=True)
                    pass
    return f"refreshed {len(targets)} OAuth provider(s)"


def _heal_check_local(provider: str = "", **kwargs) -> str:
    local_ports = {"lm_studio": 1234, "ollama": 11434}
    results = []
    for name, port in local_ports.items():
        if provider and name != provider:
            continue
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models", method="GET")
            urllib.request.urlopen(req, timeout=1)
            results.append(f"{name} running")
        except Exception:
            results.append(f"{name} down")
    return ", ".join(results)


def _heal_reset_profile(provider: str, name: str = "", **kwargs) -> str:
    from models.providers.core.profiles import load_profile_store
    store = load_profile_store()
    if name:
        store.record_success(provider, name)
        return f"reset {provider}/{name}"
    for p in store.list_profiles(provider):
        store.record_success(provider, p.name)
    return f"reset all profiles for {provider}"


def _heal_auto_detect(**kwargs) -> str:
    try:
        from models.providers.core.auto_detect import run_auto_detect
        run_auto_detect(force=True)
        return "auto-detect completed"
    except Exception as e:
        return f"auto-detect failed: {e}"


def init_heal_tools():
    register_repair_tool("clear_cooldowns", _heal_clear_cooldowns, "Clear all expired profile cooldowns")
    register_repair_tool("refresh_oauth", _heal_refresh_oauth, "Refresh expiring OAuth tokens")
    register_repair_tool("check_local", _heal_check_local, "Check if local providers are running")
    register_repair_tool("reset_profile", _heal_reset_profile, "Reset a profile's error state")
    register_repair_tool("auto_detect", _heal_auto_detect, "Re-scan available providers")
