from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional


def safe_session_id(session_id: Any) -> str:
    """Return a filesystem-safe session id shared by all runtime adapters."""
    raw = os.path.basename(str(session_id or "default")).replace(".json", "")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return cleaned or "default"


def safe_turn_id(turn_id: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(turn_id or "").strip())[:120]


def session_file_path(sessions_dir: str, session_id: Any, suffix: str = ".json") -> str:
    os.makedirs(sessions_dir, exist_ok=True)
    safe_id = safe_session_id(session_id)
    path = os.path.abspath(os.path.join(sessions_dir, f"{safe_id}{suffix}"))
    root = os.path.abspath(sessions_dir)
    if os.path.commonpath([root, path]) != root:
        raise ValueError("Invalid session id")
    return path


def normalize_provider(provider: Any) -> str:
    return str(provider or "").lower().replace(" ", "_")


def parse_max_tokens(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_tokens must be an integer") from exc


@dataclass(frozen=True)
class ChatRunRequest:
    session_id: str
    prompt: str
    provider: str
    model: str
    max_tokens: Optional[int]
    turn_id: str
    profile: str = ""
    source: str = ""
    messages: Optional[list] = None


def build_chat_request(
    data: Mapping[str, Any],
    *,
    default_provider: str = "",
    default_model: str = "",
    default_source: str = "",
) -> ChatRunRequest:
    prompt = str(data.get("prompt", "")).strip()[:50000]
    if not prompt:
        raise ValueError("prompt is required and cannot be empty")
    raw_max_tokens = data.get("max_tokens", data.get("max_completion_tokens", None))
    return ChatRunRequest(
        session_id=safe_session_id(data.get("session_id", "default")),
        prompt=prompt,
        provider=normalize_provider(data.get("provider") or default_provider),
        profile=str(data.get("profile", "") or "").strip(),
        model=str(data.get("model", "") or default_model or "").strip(),
        max_tokens=parse_max_tokens(raw_max_tokens),
        turn_id=safe_turn_id(data.get("turn_id", "")),
        source=str(data.get("source", default_source) or default_source),
        messages=data.get("messages"),
    )
