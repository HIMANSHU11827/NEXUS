"""Streaming context scrubber — stateful scrubber for streaming text.

Inspired by Hermes Agent's ``StreamingContextScrubber``.

Handles chunk-boundary-safe removal of:
- ``<thinking>...</thinking>`` spans
- ``TASK_COMPLETE`` markers
- ``<memory-context>...</memory-context>`` spans (Hermes compat)
- Tool call JSON artifacts that leak into visible output
- Non-ASCII control/surrogate characters
- Truncation warnings
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

# ── Patterns ─────────────────────────────────────────────────────────

_RE_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_RE_SCRATCHPAD = re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL | re.IGNORECASE)
_RE_MEMORY_CTX = re.compile(r"<memory-context>.*?</memory-context>", re.DOTALL | re.IGNORECASE)
_RE_TASK_COMPLETE = re.compile(r"TASK_COMPLETE\s*", re.IGNORECASE)
_RE_TRUNCATION = re.compile(r"\[TRUNCATED[^\]]*\]", re.IGNORECASE)
_RE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_RE_SURROGATES = re.compile(r"[\ud800-\udfff]")
_RE_TOOL_CALL_LEAK = re.compile(
    r'\{\s*"action"\s*:\s*"[^"]*"\s*,\s*"params"\s*:\s*\{[^}]*\}\s*\}',
    re.DOTALL,
)


class StreamingContextScrubber:
    """Stateful scrubber that handles chunk-boundary-safe span removal.

    Usage::

        scrubber = StreamingContextScrubber()
        for delta in stream:
            visible = scrubber.feed(delta)
            if visible:
                emit(visible)
        trailing = scrubber.flush()
        if trailing:
            emit(trailing)
    """

    SPANS = {
        "thinking": ("<thinking>", "</thinking>"),
        "memory_context": ("<memory-context>", "</memory-context>"),
        "scratchpad": ("<scratchpad>", "</scratchpad>"),
    }

    def __init__(
        self,
        on_thinking_delta: Optional[Callable[[str], None]] = None,
        on_thinking_done: Optional[Callable[[], None]] = None,
    ) -> None:
        self._in_span: Optional[str] = None
        self._buf: str = ""
        self._on_thinking_delta = on_thinking_delta
        self._on_thinking_done = on_thinking_done

    def reset(self) -> None:
        self._in_span = None
        self._buf = ""

    def feed(self, text: str) -> str:
        """Return visible portion of *text* after scrubbing.

        Partial tags at chunk boundaries are held back and resolved
        on the next ``feed()`` call or by ``flush()``.
        """
        if not text:
            return ""

        buf = self._buf + text
        self._buf = ""
        out: List[str] = []

        while buf:
            if self._in_span is not None:
                close_tag = self.SPANS[self._in_span][1]
                idx = buf.lower().find(close_tag.lower())
                if idx == -1:
                    # Hold back potential partial close tag
                    held = self._max_partial(buf, close_tag)
                    self._buf = buf[-held:] if held else ""
                    return self._light_clean("".join(out))
                # Skip span content + close tag
                buf = buf[idx + len(close_tag):]
                if self._in_span == "thinking" and self._on_thinking_done:
                    self._on_thinking_done()
                self._in_span = None
            else:
                # Find earliest open tag
                earliest_pos = len(buf)
                earliest_tag = None
                for tag_name, (open_tag, _) in self.SPANS.items():
                    pos = buf.lower().find(open_tag.lower())
                    if pos != -1 and pos < earliest_pos:
                        earliest_pos = pos
                        earliest_tag = tag_name

                if earliest_tag is None:
                    # No open tag — hold back potential partial open tags
                    held = 0
                    for open_tag, _ in self.SPANS.values():
                        h = self._max_partial(buf, open_tag)
                        if h > held:
                            held = h
                    if held:
                        out.append(buf[:-held])
                        self._buf = buf[-held:]
                    else:
                        out.append(buf)
                    return self._light_clean("".join(out))

                # Emit text before the tag, enter span
                if earliest_pos > 0:
                    out.append(buf[:earliest_pos])
                buf = buf[earliest_pos + len(self.SPANS[earliest_tag][0]):]
                self._in_span = earliest_tag
                if earliest_tag == "thinking" and self._on_thinking_delta:
                    self._on_thinking_delta("")

        return self._light_clean("".join(out))

    def flush(self) -> str:
        """Return any buffered text at end of stream."""
        buf = self._buf
        self._buf = ""
        if self._in_span is not None:
            # Unclosed span — discard entirely
            if self._in_span == "thinking" and self._on_thinking_done:
                self._on_thinking_done()
            self._in_span = None
            return ""
        return self._clean(buf, strip=True)

    @staticmethod
    def _max_partial(text: str, tag: str) -> int:
        """Return length of longest suffix of *text* that matches a prefix of *tag*."""
        for i in range(len(tag) - 1, 0, -1):
            if text.endswith(tag[:i]):
                return i
        return 0

    @staticmethod
    def _clean(text: str, strip: bool = True) -> str:
        """Remove all known span content, markers, and control chars."""
        text = _RE_THINKING.sub("", text)
        text = _RE_SCRATCHPAD.sub("", text)
        text = _RE_MEMORY_CTX.sub("", text)
        text = _RE_TASK_COMPLETE.sub("", text)
        text = _RE_TRUNCATION.sub("", text)
        text = _RE_TOOL_CALL_LEAK.sub("", text)
        text = _RE_SURROGATES.sub("", text)
        text = _RE_CONTROL_CHARS.sub("", text)
        return text.strip() if strip else text

    @classmethod
    def clean_once(cls, text: str) -> str:
        """One-shot clean of a complete string (no state machine needed)."""
        return cls._clean(text, strip=True)

    @staticmethod
    def _light_clean(text: str) -> str:
        """Lighter clean for streaming chunks — no strip (preserves mid-stream whitespace)."""
        text = _RE_THINKING.sub("", text)
        text = _RE_SCRATCHPAD.sub("", text)
        text = _RE_MEMORY_CTX.sub("", text)
        text = _RE_SURROGATES.sub("", text)
        text = _RE_CONTROL_CHARS.sub("", text)
        return text


class MessageSanitizer:
    """Sanitize messages before sending to the model API.

    Strips images from non-vision models, normalizes line endings,
    and removes control characters.
    """

    @staticmethod
    def sanitize_message(msg: dict) -> dict:
        """Clean a single message dict."""
        result = dict(msg)
        content = result.get("content", "")
        if isinstance(content, str):
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = _RE_CONTROL_CHARS.sub("", content)
            content = _RE_SURROGATES.sub("", content)
            result["content"] = content
        elif isinstance(content, list):
            sanitized = []
            for part in content:
                if isinstance(part, dict):
                    part = dict(part)
                    if part.get("type") == "image_url" and not part.get("vision_enabled", True):
                        continue
                sanitized.append(part)
            result["content"] = sanitized
        return result

    @staticmethod
    def sanitize_messages(messages: list) -> list:
        """Clean all messages in a conversation."""
        return [MessageSanitizer.sanitize_message(m) for m in messages]
