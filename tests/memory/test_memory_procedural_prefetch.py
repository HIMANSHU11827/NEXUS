"""Regression: the procedural memory channel must actually be populated.

``MemoryContext.procedural`` is read by the live V5 turn pipeline
(orchestrators/v5/core.py:1951 builds ``context_summary`` from it), but
nothing ever wrote it: ``_in_memory["procedural"]`` was only ever set by
manual ``set_memory``/import calls, so the skill corpus written by
evolution/skill_forge was never read back into a turn.  These tests pin the
closure: ``MemoryManager._prefetch_procedural`` ranks skills via
``NexusSkillEngine.select_skills`` and ``prefetch_all`` surfaces the digest.
"""
import asyncio
import sys
import types

from memory import MemoryManager


class _Skill:
    def __init__(self, name, description):
        self.id = name
        self.name = name
        self.description = description


class _Engine:
    last_query = None

    def __init__(self, root=None):
        self.root = root

    def select_skills(self, task_text="", limit=5):
        _Engine.last_query = task_text
        return [_Skill("recovery-checklist", "run the recovery checklist")]


def _install_stub_engine(monkeypatch):
    module = types.ModuleType("extensions.skills.built_in.engine")
    module.NexusSkillEngine = _Engine
    monkeypatch.setitem(sys.modules, "extensions.skills.built_in.engine", module)


def test_prefetch_procedural_populates_slot(tmp_path, monkeypatch):
    _install_stub_engine(monkeypatch)
    mgr = MemoryManager(str(tmp_path), session_id="s1")
    digest = mgr._prefetch_procedural("how do I recover?")
    assert "recovery-checklist" in digest
    assert "run the recovery checklist" in digest
    assert mgr.get("procedural") == digest
    assert _Engine.last_query == "how do I recover?"


def test_prefetch_all_exposes_procedural_context(tmp_path, monkeypatch):
    _install_stub_engine(monkeypatch)
    mgr = MemoryManager(str(tmp_path), session_id="s1")
    ctx = asyncio.run(mgr.prefetch_all("how do I recover?"))
    assert "recovery-checklist" in ctx.procedural
    assert "[PROCEDURAL]" in ctx.as_text()


def test_prefetch_procedural_never_raises(tmp_path, monkeypatch):
    broken = types.ModuleType("extensions.skills.built_in.engine")

    class _Boom:
        def __init__(self, root=None):
            raise RuntimeError("no engine")

    broken.NexusSkillEngine = _Boom
    monkeypatch.setitem(sys.modules, "extensions.skills.built_in.engine", broken)
    mgr = MemoryManager(str(tmp_path), session_id="s1")
    assert mgr._prefetch_procedural("anything") == ""
