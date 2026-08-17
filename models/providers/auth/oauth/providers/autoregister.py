"""Auto-register all built-in OAuth providers into the global registry."""

import inspect

from models.providers.auth.oauth.providers.chutes import login_chutes, refresh_chutes_token
from models.providers.auth.oauth.providers.claude import login_anthropic, refresh_anthropic_token
from models.providers.auth.oauth.providers.codex import login_codex, refresh_codex_token
from models.providers.auth.oauth.providers.copilot import (
    login_github_copilot,
    refresh_github_copilot_token,
)
from models.providers.auth.oauth.providers.gemini import login_gemini, refresh_gemini_token
from models.providers.auth.oauth.providers.grok import login_grok, refresh_grok_token
from models.providers.auth.oauth.providers.minimax import login_minimax, refresh_minimax_token
from models.providers.auth.oauth.providers.openrouter import (
    login_openrouter,
    refresh_openrouter_token,
)
from models.providers.auth.oauth.providers.qwen import login_qwen, refresh_qwen_token
from models.providers.auth.oauth.registry import register_oauth_provider
from models.providers.auth.oauth.types import (
    OAuthCredentials,
    OAuthLoginCallbacks,
    OAuthProviderInterface,
)


def _make_oauth_provider(
    provider_id: str,
    name: str,
    login_fn,
    refresh_fn,
) -> OAuthProviderInterface:
    class _Provider:
        @property
        def id(self) -> str:
            return provider_id

        @property
        def name(self) -> str:
            return name

        async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
            # Only pass optional kwargs the target login() actually accepts.
            # minimax/copilot do NOT define on_manual_code_input, so passing it
            # unconditionally made `auth login <provider>` crash with a TypeError.
            kwargs = {
                "on_auth": callbacks.on_auth,
                "on_prompt": callbacks.on_prompt,
            }
            target_params = inspect.signature(login_fn).parameters
            if "on_progress" in target_params:
                kwargs["on_progress"] = getattr(callbacks, "on_progress", None)
            if "on_manual_code_input" in target_params:
                kwargs["on_manual_code_input"] = getattr(callbacks, "on_manual_code_input", None)
            if "signal" in target_params:
                kwargs["signal"] = getattr(callbacks, "signal", None)
            return await login_fn(**kwargs)

        async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
            result = refresh_fn(credentials.refresh)
            if inspect.isawaitable(result):
                return await result
            return result

        def get_api_key(self, credentials: OAuthCredentials) -> str:
            return credentials.access

    return _Provider()


def register_all_oauth_providers() -> None:
    providers = [
        ("codex", "ChatGPT Plus/Pro", login_codex, refresh_codex_token),
        ("claude", "Anthropic (Claude Pro/Max)", login_anthropic, refresh_anthropic_token),
        ("github-copilot", "GitHub Copilot", login_github_copilot, refresh_github_copilot_token),
        ("grok", "xAI Grok", login_grok, refresh_grok_token),
        ("gemini", "Google Gemini", login_gemini, refresh_gemini_token),
        ("openrouter", "OpenRouter", login_openrouter, refresh_openrouter_token),
        ("minimax", "MiniMax", login_minimax, refresh_minimax_token),
        ("chutes", "Chutes", login_chutes, refresh_chutes_token),
        ("qwen", "Qwen (Aliyun)", login_qwen, refresh_qwen_token),
    ]

    for provider_id, name, login_fn, refresh_fn in providers:
        provider_obj = _make_oauth_provider(provider_id, name, login_fn, refresh_fn)
        register_oauth_provider(provider_obj)
