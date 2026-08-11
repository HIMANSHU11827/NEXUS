"""Conservative classification of terminal actions as verification evidence."""

from __future__ import annotations

import re
import shlex
from typing import Any, Iterable, Optional

from providers.reliability import redact_secrets

_BUILT_INS = (
    (re.compile(r"^(?:python(?:\.exe)?|python3)\s+-m\s+pytest(?:\s|$)", re.I), "pytest", "test"),
    (re.compile(r"^pytest(?:\.exe)?(?:\s|$)", re.I), "pytest", "test"),
    (re.compile(r"^(?:npm|pnpm)(?:\.cmd)?\s+(?:test|run\s+(?:test|lint|build|typecheck|format|check))(?:\s|$)", re.I), "package-script", "check"),
    (re.compile(r"^(?:cargo)\s+test(?:\s|$)", re.I), "cargo test", "test"),
    (re.compile(r"^(?:go)\s+test(?:\s|$)", re.I), "go test", "test"),
    (re.compile(r"^(?:ruff)\s+check(?:\s|$)", re.I), "ruff check", "lint"),
    (re.compile(r"^(?:mypy)\s+(?:[^;&|]+)$", re.I), "mypy", "typecheck"),
)


def _normalize_wrapper(command: str) -> str:
    """Remove harmless launcher wrappers before matching the executable."""
    text = command.strip()
    changed = True
    while changed:
        changed = False
        for prefix in ("time ", "command "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].lstrip()
                changed = True
        if text.lower().startswith("env "):
            parts = text.split()
            index = 1
            while index < len(parts) and "=" in parts[index] and not parts[index].startswith(("-", "/")):
                index += 1
            text = " ".join(parts[index:])
            changed = True
    return text


def _output_summary(value: Any) -> str:
    return redact_secrets(str(value or "")).strip()[:1500]


def classify_verification_command(
    command: Any,
    *,
    exit_code: Optional[int] = None,
    output: Any = "",
    configured_commands: Iterable[str] = (),
) -> Optional[dict[str, Any]]:
    """Return evidence only for configured or strongly recognizable commands."""
    if not isinstance(command, str) or not command.strip():
        return None
    text = command.strip()[:12000]
    match_text = _normalize_wrapper(text)
    if any(token in text for token in (";", "&&", "||", "|", "`", "$((", "$(", ">", "<")):
        return None
    if exit_code is None:
        return None
    configured = [str(item).strip()[:500] for item in configured_commands if str(item).strip()]
    canonical = ""
    kind = ""
    if configured:
        for candidate in configured:
            if match_text == candidate or match_text.startswith(candidate + " "):
                canonical, kind = candidate, "configured"
                break
    else:
        # Reject shell chains and command substitution; a verification record
        # must describe one explicit, recognizable command.
        if any(token in text for token in (";", "&&", "||", "`", "$((", "$(")):
            return None
        for pattern, candidate, candidate_kind in _BUILT_INS:
            match = pattern.search(match_text)
            if match:
                canonical, kind = candidate, candidate_kind
                if candidate == "package-script":
                    script = re.search(r"\b(?:run\s+)?(test|lint|build|typecheck|format|check)\b", match_text, re.I)
                    kind = (script.group(1).lower() if script else "check")
                break
    if not canonical:
        return None
    try:
        tokens = shlex.split(match_text, posix=False)
    except ValueError:
        tokens = text.split()
    target_markers = ("-k", "-m", "::", "--target", "--file")
    has_target_path = any(
        token.lower().endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"))
        or token.lower().startswith(("test_", "tests", "spec", "__tests__"))
        or any(marker in token for marker in target_markers)
        for token in tokens[1:]
    )
    scope = "targeted" if has_target_path else "full"
    status = "passed" if exit_code == 0 else "failed"
    return {
        "command": text[:500],
        "canonical_command": canonical[:500],
        "kind": kind[:40],
        "scope": scope,
        "status": status,
        "exit_code": int(exit_code),
        "output_summary": _output_summary(output),
    }


__all__ = ["classify_verification_command"]
