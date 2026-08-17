"""Backward-compatibility shim for the old top-level ``providers`` package.

The canonical provider implementations now live under
``models.providers.{local,api,auth,core}`` (architecture spec section 21).
This shim re-exports every provider module so legacy ``import providers.<name>``
and ``from providers.<name> import ...`` references keep resolving during the
transition. Do not add new providers here; add them under models/providers/.
"""

import importlib
import sys

from models.providers import core, local, api, auth  # noqa: F401

_MODULES = {
    'anthropic': 'api',
    'attempts': 'core',
    'auto_detect': 'core',
    'auto_heal': 'core',
    'azure_openai': 'api',
    'base': 'core',
    'cohere': 'api',
    'commandcode': 'api',
    'deepseek': 'api',
    'factory': 'core',
    'fireworks': 'api',
    'flux_image': 'core',
    'google_gemini': 'api',
    'groq': 'api',
    'heal_tools': 'core',
    'health': 'core',
    'huggingface': 'api',
    'langchain_provider': 'core',
    'langchain_tools': 'core',
    'llama_cpp': 'local',
    'lm_studio': 'local',
    'lm_studio_auto': 'local',
    'mistral': 'api',
    'model_bench': 'core',
    'model_capabilities': 'core',
    'nvidia': 'api',
    'ollama': 'local',
    'openai': 'api',
    'opencode_cli': 'auth',
    'openrouter': 'api',
    'perplexity': 'api',
    'profiles': 'core',
    'qwen': 'api',
    'reliability': 'core',
    'replicate': 'api',
    'router': 'core',
    'sambanova': 'api',
    'sandbox_interpreter': 'local',
    'search_serper': 'core',
    'together': 'api',
    'universal': 'core',
    'vlm': 'core',
    'xai': 'api',
    'zupra': 'api',
}

for _name, _cat in _MODULES.items():
    try:
        _mod = importlib.import_module(f"models.providers.{_cat}.{_name}")
    except Exception:
        # Optional/heavy providers (e.g. langchain) may lack deps in this env;
        # skip registration rather than break `import providers`.
        continue
    sys.modules.setdefault("providers." + _name, _mod)
    globals()[_name] = _mod

__all__ = ["core", "local", "api", "auth", "_MODULES"]
