"""Unified context package — file-centric persistence for agent state.

Also exposes the pure diagnostics/compaction helpers used by ``/context``:

- :func:`inspect` — token/char breakdown of a message list.
- :func:`compact_messages` — budget-safe compaction that merges the oldest
  turns into ONE summary message and never splits a tool_call from its
  tool result.
"""

from __future__ import annotations

import json
import copy
from typing import Any, Dict, List

from context.persistence import NexusFilePersistence

__all__ = ["NexusFilePersistence", "compact_messages", "inspect"]


def _estimate_tokens(text: Any) -> int:
    """Rough token estimate — ~4 chars per token (``chars // 4``)."""
    return len(str(text)) // 4


def _msg_text(message: Any) -> str:
    """Flatten one message to its textual weight (content + tool_calls)."""
    if not isinstance(message, dict):
        return str(message)
    parts: List[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    text = message.get("text")
    if isinstance(text, str):
        parts.append(text)
    tool_calls = message.get("tool_calls")
    if tool_calls:
        try:
            parts.append(json.dumps(tool_calls))
        except Exception:
            pass
    return "".join(parts)


def inspect(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Pure diagnostic breakdown of a message list for ``/context``.

    Returns ``{total_chars, est_tokens, system_chars, user_chars,
    assistant_chars, tool_chars, count}`` where ``est_tokens`` is the rough
    ``total_chars // 4`` approximation.  Never mutates *messages*.
    """
    sums = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
    total_chars = 0
    count = 0
    for m in messages:
        text = _msg_text(m)
        total_chars += len(text)
        count += 1
        role = m.get("role") if isinstance(m, dict) else "unknown"
        if role in sums:
            sums[role] += len(text)
    return {
        "total_chars": total_chars,
        "est_tokens": total_chars // 4,
        "system_chars": sums["system"],
        "user_chars": sums["user"],
        "assistant_chars": sums["assistant"],
        "tool_chars": sums["tool"],
        "count": count,
    }


def _is_tool_call(message: Any) -> bool:
    return isinstance(message, dict) and message.get("role") == "assistant" and bool(
        message.get("tool_calls")
    )


def _is_tool_result(message: Any) -> bool:
    return isinstance(message, dict) and message.get("role") == "tool"


def _tool_windows(messages: List[Dict[str, Any]]) -> List[List[int]]:
    """Indices (inclusive) of contiguous tool_call → tool_result windows.

    A window starts at an assistant ``tool_calls`` message and extends
    forward over every immediately-following ``role == "tool"`` result.  A
    tool_call with no following result is an *orphan* and is not a window.
    """
    windows: List[List[int]] = []
    i = 0
    n = len(messages)
    while i < n:
        if _is_tool_call(messages[i]):
            j = i
            has_result = False
            while j + 1 < n and _is_tool_result(messages[j + 1]):
                j += 1
                has_result = True
            if has_result:
                windows.append([i, j])
                i = j + 1
            else:
                i += 1  # orphan tool_call — no tool_result follows
        else:
            i += 1
    return windows


_CRITICAL_CONTEXT_TERMS = (
    "objective", "constraint", "decision", "changed file", "modified file",
    "error", "failed", "failure", "unresolved", "remaining", "todo", "test",
)


def _critical_excerpts(messages: List[Dict[str, Any]], limit: int = 12) -> List[str]:
    """Keep small, deterministic excerpts for facts likely needed after compaction."""
    excerpts: List[str] = []
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") in {"tool", "system"}:
            continue
        text = str(message.get("content") or message.get("text") or "")
        for line in text.splitlines():
            clean = " ".join(line.split()).strip()
            lowered = clean.lower()
            if len(clean) < 8 or not any(term in lowered for term in _CRITICAL_CONTEXT_TERMS):
                continue
            if len(clean) > 320:
                marker_positions = [clean.lower().find(term) for term in _CRITICAL_CONTEXT_TERMS if clean.lower().find(term) >= 0]
                marker = min(marker_positions) if marker_positions else 0
                start = max(0, min(marker - 100, len(clean) - 320))
                clean = ("..." if start else "") + clean[start:start + 320]
            if clean.lower() in seen:
                continue
            seen.add(clean.lower())
            excerpts.append(clean)
            if len(excerpts) >= max(1, int(limit)):
                return excerpts
    return excerpts


def compact_messages(
    messages: List[Dict[str, Any]],
    budget_tokens: int,
    keep_recent: int = 6,
) -> Any:
    """Budget-safe compaction: merge the oldest turns into ONE summary.

    - Oldest non-system turns (beyond the ``keep_recent`` tail) are merged
      into a single ``system`` summary message; real system messages are
      never merged.
    - A tool_call is NEVER split from its tool result.  The compaction cutoff
      is pushed back past any window that would straddle it, and inside the
      compacted region the newest contiguous ``tool_call → tool_result``
      window is preserved verbatim; an orphan tool_call (whose result was
      compacted away) is elided instead of half-kept.

    Returns ``(messages, dropped_entries)`` where ``dropped_entries`` counts
    original messages that were merged into the summary or removed.
    """
    if not messages:
        return [], 0
    msgs = list(messages)
    system = [m for m in msgs if isinstance(m, dict) and m.get("role") == "system"]
    non_system = [
        m for m in msgs if not (isinstance(m, dict) and m.get("role") == "system")
    ]

    # ``est_tokens`` is intentionally a rough, floored diagnostic value.  It
    # cannot be used as a hard admission check: e.g. five characters estimate
    # to one token while the one-token character envelope is only four
    # characters.  Use the same hard envelope as ``_fit_budget`` so the fast
    # path cannot return an oversized recent-only transcript.
    hard_limit = max(0, int(budget_tokens)) * 4
    if len(non_system) <= keep_recent and inspect(msgs)["total_chars"] <= hard_limit:
        return msgs, 0

    cutoff = max(0, len(non_system) - keep_recent)
    # Never cut through a tool window — push the cutoff before any window that
    # straddles it so the call and its result always stay together.
    for start, end in _tool_windows(non_system):
        if start < cutoff <= end:
            cutoff = start

    head = non_system[:cutoff]
    if not head:
        # Even when every non-system message is recent, the combined system
        # prompt and recent tail may exceed the hard budget. The old early
        # return bypassed _fit_budget entirely and sent oversized requests.
        fitted = _fit_budget(msgs, budget_tokens)
        return fitted, max(0, len(msgs) - len(fitted))
    tail = non_system[cutoff:]

    head_windows = _tool_windows(head)
    kept_window = head_windows[-1] if head_windows else None  # newest window

    summary_parts: List[str] = []
    kept_head: List[Dict[str, Any]] = []
    i = 0
    n = len(head)
    while i < n:
        if kept_window is not None and kept_window[0] == i:
            end = kept_window[1]
            kept_head.extend(head[i:end + 1])
            i = end + 1
            continue
        message = head[i]
        if _is_tool_call(message) or _is_tool_result(message):
            i += 1  # orphan tool_call / stripped tool_result — elide as a unit
            continue
        role = message.get("role", "unknown")
        text = message.get("content") or message.get("text") or ""
        summary_parts.append(f"{role}: {str(text)[:200]}")
        i += 1

    critical = _critical_excerpts(head)
    if critical:
        summary_parts.insert(0, "[PRESERVED CRITICAL CONTEXT]")
        summary_parts[1:1] = [f"- {excerpt}" for excerpt in critical]
    summary_text = "[SUMMARY OF EARLIER CONTEXT]\n" + "\n".join(summary_parts)
    max_summary_chars = max(1, budget_tokens * 4)
    if len(summary_text) > max_summary_chars:
        summary_text = summary_text[:max_summary_chars] + "[truncated]"

    dropped = len(head) - len(kept_head)
    result: List[Dict[str, Any]] = list(system)
    result.append({"role": "system", "content": summary_text})
    result.extend(kept_head)
    result.extend(tail)
    fitted = _fit_budget(result, budget_tokens)
    return fitted, max(dropped, len(result) - len(fitted))


def _fit_budget(messages: List[Dict[str, Any]], budget_tokens: int) -> List[Dict[str, Any]]:
    """Enforce the total budget after summary and recent tail are assembled."""
    # Compaction must be observationally pure. In particular, the final
    # system-content trim below must not mutate the caller's live transcript.
    result = copy.deepcopy(list(messages))
    limit = max(0, int(budget_tokens)) * 4
    while result and inspect(result)["total_chars"] > limit:
        indices = [i for i, message in enumerate(result)
                   if not (isinstance(message, dict) and message.get("role") == "system")]
        if not indices:
            break
        index = indices[0]
        remove = {index}
        if _is_tool_call(result[index]):
            j = index + 1
            while j < len(result) and _is_tool_result(result[j]):
                remove.add(j)
                j += 1
        elif index > 0 and _is_tool_result(result[index]) and _is_tool_call(result[index - 1]):
            remove.add(index - 1)
        result = [message for i, message in enumerate(result) if i not in remove]
    if inspect(result)["total_chars"] > limit:
        remaining = limit - sum(len(_msg_text(message)) for message in result
                                if not (isinstance(message, dict) and message.get("role") == "system"))
        for message in result:
            if isinstance(message, dict) and message.get("role") == "system":
                content = str(message.get("content") or "")
                keep = max(0, min(len(content), remaining))
                suffix = "\n[system context truncated to fit budget]"
                if keep >= len(suffix):
                    message["content"] = content[:keep - len(suffix)] + suffix
                else:
                    message["content"] = content[:keep]
                remaining -= keep
    return result
