"""Qwen (Aliyun) OAuth was retired upstream (OpenClaw retired qwen-oauth,
qwen-portal, and qwen-cli). The provider stays registered so existing
credentials resolve, but login and refresh fail fast with guidance."""

import logging

from models.providers.auth.oauth.types import OAuthCredentials

logger = logging.getLogger("nexus.oauth.qwen")

_RETIRED_MESSAGE = (
    "Qwen OAuth login is retired; Alibaba no longer issues Qwen API keys through "
    "this flow. Use a DashScope API key instead: set DASHSCOPE_API_KEY."
)


async def login_qwen(
    on_auth,
    on_prompt,
    on_progress=None,
    on_manual_code_input=None,
    signal=None,
) -> OAuthCredentials:
    raise RuntimeError(_RETIRED_MESSAGE)


def refresh_qwen_token(credentials: OAuthCredentials) -> OAuthCredentials:
    raise RuntimeError(_RETIRED_MESSAGE)