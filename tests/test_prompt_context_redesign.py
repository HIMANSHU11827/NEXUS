"""V5 prompt-making + unified compaction redesign tests.

Covers:
- ``NexusPromptEngine.build_live_system_prompt`` — compact, token-budgeted
  live prompt that stays safe when any segment raises.
- ``direct_loop._live_system_prompt`` — the live loop system prompt now comes
  from the engine (identity marker present) and soft-degrades to the exact
  legacy hardcoded text when the engine import fails.
- ``ContextManager.compact_context`` — delegates to ``context.compact_messages``
  so a tool_call is never split from its tool_result; sane token-limit default.

Run serially: ``.venv/Scripts/python.exe -m pytest tests/test_prompt_context_redesign.py -q``
"""

import asyncio
import builtins

from nexus.conversation.prompts import NexusPromptEngine
from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.context_manager import ContextConfig, ContextManager
from nexus.main_agent.direct_loop import _LEGACY_SYSTEM_PROMPT, _live_system_prompt, _live_system_prompt_cache


class TestLivePromptEngine:
    def test_build_live_system_prompt_nonempty_identity_role(self, tmp_path):
        prompt = NexusPromptEngine.build_live_system_prompt(str(tmp_path))
        assert prompt
        # Identity segment is present.
        assert "# NEXUS_ENGINEERING_CORE" in prompt
        # Role segment is present.
        assert "# ROLE: ARCHITECT" in prompt
        assert "ask_question" in prompt
        assert "Do not ask through ordinary prose" in prompt

    def test_build_live_system_prompt_respects_max_chars(self, tmp_path):
        focus_dir = tmp_path / "docs"
        focus_dir.mkdir(parents=True, exist_ok=True)
        (focus_dir / "SPECIAL_FOCUS.md").write_text("focus " * 3000, encoding="utf-8")
        prompt = NexusPromptEngine.build_live_system_prompt(str(tmp_path), max_chars=500)
        assert len(prompt) <= 500

    def test_build_live_system_prompt_skips_raising_segments(self, tmp_path, monkeypatch):
        # A raising segment (e.g., kernel/vault side effect) is skipped, never
        # allowed to crash prompt building.
        def boom(*_args, **_kwargs):
            raise RuntimeError("segment exploded")

        monkeypatch.setattr(NexusPromptEngine, "get_special_focus_segment", staticmethod(boom))
        monkeypatch.setattr(NexusPromptEngine, "get_rules_segment", staticmethod(boom))
        prompt = NexusPromptEngine.build_live_system_prompt(str(tmp_path))
        assert prompt  # did not raise
        assert "# NEXUS_ENGINEERING_CORE" in prompt


class TestDirectLoopSystemPrompt:
    def test_system_prompt_comes_from_engine(self, tmp_path):
        loop = NexusLoopV5(str(tmp_path), session_id="engine-prompt-test")
        _live_system_prompt_cache.clear()
        prompt = _live_system_prompt(str(loop.root_dir))
        assert "# NEXUS_ENGINEERING_CORE" in prompt
        # The raw legacy hardcoded string is no longer the live system prompt.
        assert "You are Nexus, a local autonomous agent" not in prompt

    def test_system_prompt_falls_back_to_legacy_on_engine_failure(self, tmp_path, monkeypatch):
        _live_system_prompt_cache.clear()
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "nexus.conversation.prompts":
                raise ImportError("prompt engine unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        prompt = _live_system_prompt(str(tmp_path))
        assert prompt == _LEGACY_SYSTEM_PROMPT
        assert "ask_question" in prompt

    def test_project_context_appended_when_files_loaded(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "Project guidance: keep changes verified.\n", encoding="utf-8"
        )
        loop = NexusLoopV5(str(tmp_path), session_id="project-context-test")
        result = asyncio.run(loop._append_project_context("base system"))
        assert "=== PROJECT CONTEXT ===" in result
        assert "keep changes verified" in result


class TestUnifiedCompaction:
    def test_context_manager_delegates_to_call_safe_compactor(self, tmp_path):
        # A tool_call -> tool_result pair straddling the compaction cutoff must
        # survive intact when compacted through ContextManager.compact_context.
        mgr = ContextManager(str(tmp_path))
        messages = [
            {"role": "user", "content": f"s{i}"} for i in range(3)
        ] + [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "content": "42"},
        ] + [
            {"role": "user", "content": f"t{i}"} for i in range(5)
        ]

        compacted = mgr.compact_context(messages)

        idx = next(i for i, m in enumerate(compacted)
                   if m.get("tool_calls") and m["tool_calls"][0].get("id") == "t1")
        assert compacted[idx]["role"] == "assistant"
        assert compacted[idx + 1]["role"] == "tool"
        assert compacted[idx + 1]["tool_call_id"] == "t1"

    def test_context_config_token_limit_default(self):
        assert ContextConfig().context_token_limit == 128000
        mgr = ContextManager(str("."))
        budget = mgr.config.budget_tokens or mgr.config.context_token_limit
        assert budget == 128000
