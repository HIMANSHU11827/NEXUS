"""Tests that the runtime write-guard is ACTIVE and protects core modules from
evolution / self-improvement file writes.

These tests cover both the guard primitives in ``utils.runtime_guard`` and the
integration point inside ``SelfImprovementEngine`` (which must route its log
writes through the guard so a bad root/config can never rewrite orchestrators/,
kernel/, nexus/ or server/ at runtime).
"""
import json
import os

import pytest

from utils import runtime_guard as guard
from utils.runtime_guard import (
    CoreRewriteBlocked,
    guarded_append_text,
    guarded_jsonl_append,
    guarded_open,
    guarded_write_text,
    is_core_path,
    protected_core_writes,
)

from evolution.self_improvement.scripts.engine import (
    ImprovementRecord,
    SelfImprovementEngine,
)


PROTECTED = guard.PROTECTED_DIRS


# ── is_core_path ────────────────────────────────────────────────────────────
class TestIsCorePath:
    def test_protected_dirs_are_detected(self):
        for d in PROTECTED:
            assert is_core_path(os.path.join(d, "loop.py")) is True
            assert is_core_path(os.path.join(d, "sub", "mod.py")) is True

    def test_non_core_is_not_detected(self):
        for p in ("logs/improvements/x.jsonl", "config/foo.json", "skills/x/SKILL.md"):
            assert is_core_path(p) is False

    def test_exact_dir_boundary_is_protected(self):
        # The protected dir itself (not a child) counts as protected.
        for d in PROTECTED:
            assert is_core_path(d) is True

    def test_unrelated_dir_with_similar_name_is_safe(self):
        # A non-protected dir that merely *contains* a protected name is safe.
        assert is_core_path(os.path.join("my_orchestrators", "x.py")) is False


# ── assert_not_rewriting_core ───────────────────────────────────────────────
class TestAssertNotRewritingCore:
    def test_blocks_protected_path(self):
        with pytest.raises(CoreRewriteBlocked):
            guard.assert_not_rewriting_core("orchestrators/loop.py", "write")

    def test_block_is_permissionerror_subclass(self):
        with pytest.raises(PermissionError):
            guard.assert_not_rewriting_core("server/app.py")

    def test_allows_non_core_path_and_returns_it(self):
        p = guard.assert_not_rewriting_core("logs/improvements/x.jsonl")
        assert p == "logs/improvements/x.jsonl"

    def test_disabled_guard_passes_through(self):
        prev = guard.set_enabled(False)
        try:
            # Even a protected path is allowed while the guard is disabled.
            assert guard.assert_not_rewriting_core("kernel/core.py") == "kernel/core.py"
        finally:
            guard.set_enabled(prev)


# ── guarded_open ────────────────────────────────────────────────────────────
class TestGuardedOpen:
    def test_write_to_core_is_blocked(self, tmp_path):
        with pytest.raises(CoreRewriteBlocked):
            guarded_open("nexus/boot.py", "w")

    def test_append_to_core_is_blocked(self, tmp_path):
        with pytest.raises(CoreRewriteBlocked):
            guarded_open("orchestrators/loop.py", "a")

    def test_safe_write_and_read(self, tmp_path):
        f = tmp_path / "safe.txt"
        with guarded_open(str(f), "w") as fh:
            fh.write("hello")
        with guarded_open(str(f), "r") as fh:
            assert fh.read() == "hello"


# ── guarded text / jsonl writers ────────────────────────────────────────────
class TestGuardedWriters:
    def test_write_text_blocks_core(self, tmp_path):
        with pytest.raises(CoreRewriteBlocked):
            guarded_write_text("server/app.py", "evil")

    def test_write_text_writes_safe_and_creates_parents(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "out.txt"
        n = guarded_write_text(str(target), "payload")
        assert n == len("payload")
        assert target.read_text(encoding="utf-8") == "payload"

    def test_append_text_blocks_core(self, tmp_path):
        with pytest.raises(CoreRewriteBlocked):
            guarded_append_text("kernel/runtime.py", "x")

    def test_append_text_appends(self, tmp_path):
        target = tmp_path / "log.txt"
        guarded_append_text(str(target), "a")
        guarded_append_text(str(target), "b")
        assert target.read_text(encoding="utf-8") == "ab"

    def test_jsonl_append_serializes_dict(self, tmp_path):
        target = tmp_path / "rec.jsonl"
        guarded_jsonl_append(str(target), {"k": 1, "v": "two"})
        line = target.read_text(encoding="utf-8").strip()
        assert json.loads(line) == {"k": 1, "v": "two"}

    def test_jsonl_append_serializes_dataclass(self, tmp_path):
        target = tmp_path / "rec.jsonl"
        rec = ImprovementRecord(session_id="s1", summary="ok", score=0.5)
        guarded_jsonl_append(str(target), rec)
        line = target.read_text(encoding="utf-8").strip()
        assert json.loads(line)["session_id"] == "s1"

    def test_jsonl_append_blocks_core(self, tmp_path):
        with pytest.raises(CoreRewriteBlocked):
            guarded_jsonl_append("orchestrators/loop.py", {"x": 1})


# ── protected_core_writes scope ─────────────────────────────────────────────
class TestProtectedCoreWritesScope:
    def test_reraises_violation(self):
        with pytest.raises(CoreRewriteBlocked):
            with protected_core_writes("test"):
                guard.assert_not_rewriting_core("nexus/run.py", "write")

    def test_passes_through_normally(self):
        with protected_core_writes("test"):
            guard.assert_not_rewriting_core("logs/x.jsonl", "write")

    def test_other_exceptions_propagate(self):
        with pytest.raises(ValueError):
            with protected_core_writes("test"):
                raise ValueError("boom")


# ── enable flag ────────────────────────────────────────────────────────────
class TestEnableFlag:
    def test_set_enabled_toggles_and_restores(self):
        original = guard.is_enabled()
        assert guard.set_enabled(False) == original
        assert guard.is_enabled() is False
        assert guard.set_enabled(True) is False
        assert guard.is_enabled() is True


# ── verify_core_integrity ──────────────────────────────────────────────────
class TestVerifyCoreIntegrity:
    def test_clean_root_returns_true(self, tmp_path):
        core = tmp_path / "orchestrators"
        core.mkdir()
        (core / "loop.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        assert guard.verify_core_integrity(str(tmp_path)) is True

    def test_corrupted_marker_returns_false(self, tmp_path):
        core = tmp_path / "orchestrators"
        core.mkdir()
        # The historical runtime corruption marker from loop.py.
        (core / "loop.py").write_text("x = getcworkspace\n", encoding="utf-8")
        assert guard.verify_core_integrity(str(tmp_path)) is False

    def test_syntax_error_returns_false(self, tmp_path):
        core = tmp_path / "orchestrators"
        core.mkdir()
        (core / "loop.py").write_text("def broken(:\n", encoding="utf-8")
        assert guard.verify_core_integrity(str(tmp_path)) is False

    def test_missing_loop_returns_false(self, tmp_path):
        assert guard.verify_core_integrity(str(tmp_path)) is False


# ── integration: SelfImprovementEngine routes writes through the guard ──────
class TestSelfImprovementEngineGuardIntegration:
    def test_log_write_is_guarded_and_persisted(self, tmp_path, monkeypatch):
        eng = SelfImprovementEngine(str(tmp_path))
        rec = ImprovementRecord(session_id="s1", summary="lesson", score=0.9)

        seen = {}
        real = guard.guarded_jsonl_append

        def spy(path, record):
            seen["path"] = path
            return real(path, record)

        monkeypatch.setattr(guard, "guarded_jsonl_append", spy)
        eng._log(rec)

        assert seen.get("path") == eng.log_path
        content = open(eng.log_path, encoding="utf-8").read().strip()
        assert json.loads(content)["session_id"] == "s1"

    def test_guard_violation_is_swallowed(self, tmp_path, monkeypatch):
        eng = SelfImprovementEngine(str(tmp_path))
        rec = ImprovementRecord(session_id="s2", score=0.1)

        def boom(path, record):
            raise CoreRewriteBlocked("blocked by guard")

        monkeypatch.setattr(guard, "guarded_jsonl_append", boom)
        # Must not raise — self-improvement is non-fatal to the agent.
        eng._log(rec)

        # No line was written because the guard blocked it.
        assert not os.path.exists(eng.log_path) or open(
            eng.log_path, encoding="utf-8"
        ).read().strip() == ""

    def test_log_dir_is_under_logs_not_core(self, tmp_path):
        eng = SelfImprovementEngine(str(tmp_path))
        assert not is_core_path(eng.log_path)
        assert "logs" in eng.log_path
