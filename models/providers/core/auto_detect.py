import logging
import os
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

_PROVIDER_ENV_KEYS = [
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("cohere", "COHERE_API_KEY"),
    ("fireworks", "FIREWORKS_API_KEY"),
    ("together", "TOGETHER_API_KEY"),
    ("perplexity", "PERPLEXITY_API_KEY"),
    ("sambanova", "SAMBANOVA_API_KEY"),
    ("qwen", "QWEN_API_KEY"),
    ("xai", "XAI_API_KEY"),
    ("huggingface", "HUGGINGFACE_API_KEY"),
    ("replicate", "REPLICATE_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("nvidia", "NVIDIA_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("deepinfra", "DEEPINFRA_API_KEY"),
    ("moonshot", "MOONSHOT_API_KEY"),
    ("commandcode", "COMMANDCODE_API_KEY"),
    ("flux", "FLUX_API_KEY"),
]

_LOCAL_PROVIDERS = {
    "lm_studio": int(os.environ.get("NEXUS_PORT_LM_STUDIO", "1234")),
    "ollama": int(os.environ.get("NEXUS_PORT_OLLAMA", "11434")),
    "llama_cpp": int(os.environ.get("NEXUS_PORT_LLAMA_CPP", "8080")),
    "vlm": int(os.environ.get("NEXUS_PORT_VLM", "8080")),
}


def _check_local_running(provider: str, port: int) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models", method="GET")
        urllib.request.urlopen(req, timeout=1)
        return True
    except Exception:
        return False


def _get_saved_providers() -> Dict[str, str]:
    providers = {}
    profile_path = Path.home() / ".nexus" / "auth" / "profiles.json"
    if profile_path.exists():
        try:
            import json
            data = json.loads(profile_path.read_text())
            profiles = data.get("profiles", data)
            if isinstance(profiles, dict):
                for prof in profiles.values():
                    if isinstance(prof, dict):
                        pname = prof.get("provider")
                        if pname:
                            providers.setdefault(pname, prof.get("api_key", ""))
        except Exception:
            logger.warning("providers/auto_detect.py:60 _get_saved_providers: suppressed error", exc_info=True)
            pass
    return providers


def _get_oauth_providers() -> List[str]:
    oauth_path = Path.home() / ".nexus" / "auth" / "oauth_store.json"
    if oauth_path.exists():
        try:
            import json
            data = json.loads(oauth_path.read_text())
            if isinstance(data, dict):
                return [k for k, v in data.items() if isinstance(v, dict) and v.get("access_token")]
        except Exception:
            logger.warning("providers/auto_detect.py:73 _get_oauth_providers: suppressed error", exc_info=True)
            pass
    return []


def detect_available_providers() -> Dict[str, str]:
    available = {}
    for name, env_var in _PROVIDER_ENV_KEYS:
        val = os.environ.get(env_var, "")
        if val and len(val) > 4:
            available[name] = val

    for pname, key in _get_saved_providers().items():
        if pname not in available and key:
            available[pname] = key

    for pname, port in _LOCAL_PROVIDERS.items():
        if _check_local_running(pname, port):
            available[pname] = "__local__"

    for pid in _get_oauth_providers():
        available.setdefault(pid, "__oauth__")

    return available


_AUTO_HEADER = "# AUTO-GENERATED — edit config/provider.yml to configure task routing\n"


def save_detected_providers(available: Dict[str, str]):
    config_dir = Path(__file__).resolve().parent.parent / "configure"
    auto_path = config_dir / "task_routing_auto.yml"

    lines = [_AUTO_HEADER]
    for name in sorted(available.keys()):
        ptype = "env" if available[name] and available[name] not in ("__local__", "__oauth__") else available[name].strip("_")
        lines.append(f"#   - {name:20s} ({ptype})\n")

    auto_path.write_text("".join(lines))
    logger.info(f"[AUTO-DETECT] Saved detected providers to {auto_path}")


def ensure_auto_routing():
    config_dir = Path(__file__).resolve().parent.parent / "configure"
    auto_path = config_dir / "task_routing_auto.yml"
    if auto_path.exists():
        logger.info("[AUTO-DETECT] Already exists — run 'nexus auth auto-detect' to regenerate")
        return
    available = detect_available_providers()
    logger.info(f"[AUTO-DETECT] Found: {sorted(available.keys())}")
    save_detected_providers(available)


def run_auto_detect(force: bool = False):
    config_dir = Path(__file__).resolve().parent.parent / "configure"
    auto_path = config_dir / "task_routing_auto.yml"
    if auto_path.exists() and not force:
        print("task_routing_auto.yml already exists. Use --force to regenerate.")
        return
    available = detect_available_providers()
    if not available:
        print("No API keys, OAuth tokens, or local providers detected.")
        print("Add keys via: nexus auth add-key --provider <name> --key <key>")
        print("Or set environment variables like DEEPSEEK_API_KEY, OPENAI_API_KEY, etc.")
        return
    print(f"Detected {len(available)} provider(s): {', '.join(sorted(available.keys()))}")
    save_detected_providers(available)
    print(f"Saved to {auto_path}")
    print("Edit config/provider.yml to set up task routing.")
