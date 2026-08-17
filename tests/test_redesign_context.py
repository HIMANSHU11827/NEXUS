"""Redesign tests: token budgeting, tool-output pruning, context compaction,
growth caps/expiry, and the context inspector.

Covers:
- ``memory.estimate_tokens`` + ``memory.MemoryBudget`` (per-write truncation
  with explicit elision marker, store-growth cap).
- ``tools.memory`` / ``tools.knowledge`` store paths pruning oversized values.
- ``context.compact_messages`` — never splits tool_call from tool result.
- ``memory.expire`` — evicts oldest unverified first, keeps verified.
- ``context.inspect`` — correct char/token breakdown.
"""

import asyncio
import datetime
import json

from nexus.context import compact_messages, inspect
from memory import MemoryBudget, estimate_tokens, expire
from extensions.tools.built_in.knowledge.scripts.knowledge import KnowledgeTool
from extensions.tools.built_in.memory.scripts.memory import MemoryTool


class TestTokenBudget:
    def test_estimate_tokens_chars_div_four(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcdefg") == 1
        assert estimate_tokens("abcdefgh") == 2
        assert estimate_tokens(None) == 0
        assert estimate_tokens(1234) == 1

    def test_budget_caps_overflow_with_truncation_marker(self):
        budget = MemoryBudget(max_fact_tokens=10)  # 10 tokens -> 40 chars
        big = "x" * 500
        fitted = budget.fit_value(big)
        assert fitted.startswith("x" * 40)
        assert "[truncated " in fitted
        assert "460 chars]" in fitted
        # Explicit marker — nothing is silently discarded
        assert len(big) > len(fitted)
        assert fitted != big

    def test_fit_value_noop_within_budget(self):
        budget = MemoryBudget(max_fact_tokens=2000)
        assert budget.fit_value("hello world") == "hello world"

    def test_budget_token_estimate(self):
        budget = MemoryBudget()
        assert budget.estimate_tokens("abcdefgh") == 2

    def test_memory_tool_store_truncates_oversized_value(self, tmp_path):
        tool = MemoryTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute("store", key="big", content="y" * 100000))
        assert result.success
        store = json.loads(
            (tmp_path / ".nexus" / "memory" / "store.json").read_text(encoding="utf-8")
        )
        assert "[truncated " in store["big"]["content"]
        assert " chars]" in store["big"]["content"]
        assert result.metadata.get("truncated") is True

    def test_knowledge_tool_store_truncates_oversized_value(self, tmp_path):
        tool = KnowledgeTool(root_dir=str(tmp_path))
        result = asyncio.run(tool.execute("store", title="T", content="z" * 100000))
        assert result.success
        store = json.loads(
            (tmp_path / "knowledge" / "store.json").read_text(encoding="utf-8")
        )
        assert store[0]["title"] == "T"
        assert "[truncated " in store[0]["content"]
        assert result.metadata.get("truncated") is True


class TestStoreGrowthCap:
    def _entry(self, days_ago, verified=False):
        return {
            "content": "c",
            "verified": verified,
            "timestamp": (
                datetime.datetime.now() - datetime.timedelta(days=days_ago)
            ).isoformat(),
        }

    def test_growth_cap_trims_old_low_value(self):
        budget = MemoryBudget(max_entries=3)
        store = {
            "old_30": self._entry(30, verified=False),
            "old_31": self._entry(31, verified=False),
            "old_32": self._entry(32, verified=False),
            "v_recent": self._entry(0, verified=True),
            "v_older": self._entry(1, verified=True),
        }
        evicted = budget.trim_store(store, max_entries=3)
        assert evicted == 2
        # Verified facts survive; only oldest unverified were evicted
        assert "v_recent" in store and "v_older" in store
        assert "old_32" not in store and "old_31" not in store

    def test_memory_store_growth_cap_keeps_recent_verified(self, tmp_path):
        budget = MemoryBudget(max_entries=2)
        tool = MemoryTool(root_dir=str(tmp_path), budget=budget)
        asyncio.run(tool.execute(
            "store", key="old1", content="stale",
            verified_result_id="r-1", source="verified_result",
        ))
        # Overwrite with a fresh set of entries so oldest verified gets trimmed
        for i in range(3):
            asyncio.run(tool.execute(
                "store", key=f"k{i}", content=f"v{i}",
                verified_result_id=f"r-{i}", source="verified_result",
            ))
        store = json.loads(
            (tmp_path / ".nexus" / "memory" / "store.json").read_text(encoding="utf-8")
        )
        assert len(store) <= 2
        assert "k2" in store  # newest verified fact kept


class TestExpiry:
    @staticmethod
    def _ts(days_ago, now=None):
        base = now or datetime.datetime.now()
        return (base - datetime.timedelta(days=days_ago)).isoformat()

    def test_expiry_evicts_oldest_unverified_first_keeps_verified(self):
        now = datetime.datetime.now()
        store = {
            "u30": {"content": "recentish", "verified": False, "timestamp": self._ts(30, now)},
            "u120": {"content": "old unverified", "verified": False, "timestamp": self._ts(120, now)},
            "u200": {"content": "very old unverified", "verified": False, "timestamp": self._ts(200, now)},
            "v120": {"content": "old verified", "verified": True, "timestamp": self._ts(120, now)},
            "fresh": {"content": "new unverified", "verified": False, "timestamp": self._ts(0, now)},
            "novts": {"content": "no timestamp", "verified": False},
        }
        result, evicted = expire(store, max_age_days=90, max_entries=100)
        assert evicted == 2  # u120 and u200 (unverified + > 90 days)
        assert "u30" in result and "fresh" in result and "novts" in result
        assert "v120" in result  # verified exempt from age expiry
        assert "u120" not in result and "u200" not in result

    def test_expiry_final_cap_drops_verified_only_after_unverified(self):
        now = datetime.datetime.now()
        store = {}
        for i in range(5):
            store[f"u{i}"] = {"verified": False, "timestamp": self._ts(i)}
        store["v"] = {"verified": True, "timestamp": self._ts(0)}
        # max_age_days huge -> no age eviction; hard cap of 3 forces trimming
        result, evicted = expire(store, max_age_days=100000, max_entries=3)
        assert evicted == 3
        assert "v" in result  # verified dropped only after all unverified
        assert "u4" not in result and "u3" not in result and "u2" not in result


class TestCompaction:
    def test_returns_unchanged_within_budget_and_recent(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ]
        out, dropped = compact_messages(msgs, budget_tokens=10000, keep_recent=6)
        assert out == msgs
        assert dropped == 0

    def test_enforces_budget_even_when_every_non_system_message_is_recent(self):
        msgs = [
            {"role": "system", "content": "system guidance " * 20},
            {"role": "user", "content": "recent request " * 20},
        ]
        original = [dict(message) for message in msgs]

        out, _dropped = compact_messages(msgs, budget_tokens=70, keep_recent=6)

        assert inspect(out)["est_tokens"] <= 70
        assert msgs == original
        assert any("system context truncated" in str(m.get("content")) for m in out)

    def test_merges_oldest_non_system_into_one_summary(self):
        msgs = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "u4"},
            {"role": "assistant", "content": "a5"},
            {"role": "user", "content": "u6"},
            {"role": "assistant", "content": "a7"},
        ]
        out, dropped = compact_messages(msgs, budget_tokens=100000, keep_recent=2)
        assert dropped == 6
        assert out[-1] == msgs[-1] and out[-2] == msgs[-2]
        summaries = [m for m in out if m.get("content", "").startswith("[SUMMARY")]
        assert len(summaries) == 1
        assert "user: u0" in summaries[0]["content"] and "assistant: a5" in summaries[0]["content"]
        assert out[0]["role"] == "system"

    def test_preserves_critical_lines_from_older_context(self):
        msgs = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Objective: repair the queue"},
            {"role": "assistant", "content": "Decision: keep the lease bounded"},
            {"role": "user", "content": "A very long investigation " * 20 + " unresolved: provider fallback"},
            {"role": "assistant", "content": "newest response"},
        ]

        out, _dropped = compact_messages(msgs, budget_tokens=100000, keep_recent=1)
        summary = "\n".join(str(message.get("content") or "") for message in out if message.get("role") == "system")

        assert "Objective: repair the queue" in summary
        assert "Decision: keep the lease bounded" in summary
        assert "unresolved: provider fallback" in summary

    def test_never_splits_tool_call_from_result(self):
        # Tool window straddles the recent cutoff: without the cutoff push the
        # call would be merged while its result stayed in the tail — a split.
        msgs = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "reasoning"},
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "thinking"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "content": "42"},
            {"role": "user", "content": "ok"},
        ]
        out, dropped = compact_messages(msgs, budget_tokens=100000, keep_recent=2)
        idx = next(i for i, m in enumerate(out)
                   if m.get("tool_calls") and m["tool_calls"][0].get("id") == "t1")
        assert out[idx]["role"] == "assistant"
        assert out[idx + 1]["role"] == "tool"
        assert out[idx + 1]["tool_call_id"] == "t1"
        assert out[-1] == msgs[-1]

    def test_orphan_tool_call_is_dropped_but_window_survives(self):
        msgs = [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "orphan", "type": "function", "function": {"name": "g", "arguments": "{}"}}
            ]},
            {"role": "user", "content": "y"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t2", "type": "function", "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "t2", "content": "7"},
            {"role": "user", "content": "z"},
        ]
        out, dropped = compact_messages(msgs, budget_tokens=100000, keep_recent=2)
        ids = [
            m["tool_calls"][0].get("id") if m.get("tool_calls") else None
            for m in out
        ]
        assert "orphan" not in ids  # the orphan was elided
        assert "t2" in ids          # the real window survived intact
        i = ids.index("t2")
        assert out[i + 1]["role"] == "tool" and out[i + 1]["tool_call_id"] == "t2"
        assert dropped == 3  # u0, orphan, y merged/dropped


class TestInspect:
    def test_inspect_correct_breakdown(self):
        msgs = [
            {"role": "system", "content": "sys-prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": [
                {"type": "function", "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "?", "content": "out"},
        ]
        info = inspect(msgs)
        assert info["count"] == 4
        assert info["system_chars"] == len("sys-prompt")
        assert info["user_chars"] == len("hello")
        assert info["tool_chars"] == len("out")
        assert info["assistant_chars"] >= len("hi")  # incl. serialized tool_calls
        total = (
            info["system_chars"]
            + info["user_chars"]
            + info["assistant_chars"]
            + info["tool_chars"]
        )
        assert info["total_chars"] == total
        assert info["est_tokens"] == total // 4

    def test_inspect_empty(self):
        assert inspect([]) == {
            "total_chars": 0, "est_tokens": 0,
            "system_chars": 0, "user_chars": 0,
            "assistant_chars": 0, "tool_chars": 0, "count": 0,
        }
