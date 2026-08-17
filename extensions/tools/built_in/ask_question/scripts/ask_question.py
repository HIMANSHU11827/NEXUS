from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult


class AskQuestionTool(BaseTool):
    """Create a user-facing question for interactive Nexus surfaces.

    The marker is intentionally compatible with the TUI question parser. The
    metadata carries the same payload for API, GUI, and plugin consumers that
    prefer structured tool results.
    """

    name = "ask_question"
    description = "Ask the user a multiple-choice question and optionally allow a custom answer"

    def is_read_only(self, params=None) -> bool:
        # Asking changes the conversation state and must not be retried as a
        # supposedly harmless read operation.
        return False

    async def execute(
        self,
        prompt: str,
        options: Iterable[Any] | None = None,
        allow_custom: bool = True,
        **kwargs,
    ) -> ToolResult:
        question = str(prompt or "").strip()
        if not question:
            return ToolResult(success=False, error="prompt is required")

        if isinstance(options, str):
            values = [options]
        elif options is None:
            values = []
        else:
            try:
                values = list(options)
            except TypeError:
                return ToolResult(success=False, error="options must be a list of strings")

        normalized = []
        for option in values:
            text = str(option or "").strip()
            if text and text not in normalized:
                normalized.append(text)
            if len(normalized) >= 8:
                break
        if not normalized:
            return ToolResult(success=False, error="at least one non-empty option is required")

        payload = {
            "id": f"question-{uuid.uuid4().hex[:12]}",
            "prompt": question,
            "options": normalized,
            "allowCustom": bool(allow_custom),
        }
        marker = f"[QUESTION:{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}]"
        return ToolResult(
            success=True,
            output=marker,
            metadata={"question": payload},
        )
