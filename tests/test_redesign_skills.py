"""Tests for the NEXUS skills redesign: runtime selection, adapter
instruction blocks, health/isolation, and experience tracking.

Run serially:  .venv/Scripts/python.exe -m pytest tests/test_redesign_skills.py -q
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from extensions.skills.built_in.engine import NexusSkillEngine
from extensions.skills.built_in.experience import SkillExperience
from extensions.tools.built_in.nexus_tools.skill_adapter import (
    SkillExecutor,
    SkillToolAdapter,
    build_instruction_block,
    parse_skill_md,
)


# ─── helpers ─────────────────────────────────────────────────────

def write_skill(root, name, description, body, tags=None, required=False, top_level_tags=False):
    """Write a canonical .opencode/skills/<name>/SKILL.md under root."""
    skill_dir = Path(root) / ".opencode" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f'description: "{description}"',
        "version: 1.0.0",
    ]
    if required:
        lines.append("required: true")
    if tags:
        if top_level_tags:
            lines.append("tags: [" + ", ".join(tags) + "]")
        else:
            lines.append("metadata:")
            lines.append("  hermes:")
            lines.append("    tags: [" + ", ".join(tags) + "]")
    lines.append("---")
    lines.append("")
    lines.append(body)
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def make_engine(tmp_path):
    """Build a fresh, hermetic skill engine with a temp experience store."""
    env = os.environ.get("NEXUS_ALL_SKILLS_INJECT")
    if env:
        del os.environ["NEXUS_ALL_SKILLS_INJECT"]
    empty_bundled = tmp_path / "_no_bundled"
    empty_bundled.mkdir(parents=True, exist_ok=True)
    NexusSkillEngine.bundled_dir = str(empty_bundled)  # keep discovery hermetic
    engine = NexusSkillEngine(str(tmp_path))
    engine._experience = SkillExperience(str(tmp_path / "experience.json"))
    return engine


@pytest.fixture(autouse=True)
def _reset_bundled_dir():
    yield
    # Never let the overridden bundled dir leak into other test modules.
    NexusSkillEngine.bundled_dir = None


# ─── runtime selection ────────────────────────────────────────────

class TestSelection:
    def test_picks_top_matching_and_excludes_non_matching(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        write_skill(tmp_path, "git", "Git version control workflows, commits, branches",
                    "GIT_BODY", tags=["git", "version-control"], top_level_tags=True)
        write_skill(tmp_path, "calendar", "Schedule meetings and manage calendar events",
                    "CALENDAR_BODY", tags=["calendar", "meetings"])
        write_skill(tmp_path, "email", "Manage email drafts and send messages",
                    "EMAIL_BODY", tags=["email", "communication"])
        engine = make_engine(tmp_path)

        selected = engine.select_skills("please review my pull request for quality issues", limit=3)
        ids = {s.id for s in selected}

        assert "code-review" in ids
        assert "calendar" not in ids
        assert "email" not in ids
        assert "git" not in ids
        assert len(selected) <= 3

    def test_top_k_honored(self, tmp_path):
        for i in range(6):
            write_skill(tmp_path, f"tool-{i}", "review quality review quality python code",
                        f"BODY_{i}", tags=["review", "python"])
        engine = make_engine(tmp_path)
        selected = engine.select_skills("review code quickly please", limit=3)
        assert len(selected) <= 3
        # All six match equally; only the cap matters.
        assert len(selected) == 3

    def test_required_always_included(self, tmp_path):
        write_skill(tmp_path, "safety", "unrelated maintenance instructions for the runtime",
                    "SAFETY_BODY", tags=["system", "runtime"], required=True)
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        engine = make_engine(tmp_path)

        selected = engine.select_skills("code quality review please", limit=3)
        ids = {s.id for s in selected}
        assert "safety" in ids          # required even with zero lexical overlap
        assert "code-review" in ids     # best match

    def test_blank_task_returns_all(self, tmp_path):
        write_skill(tmp_path, "a", "alpha description body", "A_BODY", tags=["alpha"])
        write_skill(tmp_path, "b", "beta description body", "B_BODY", tags=["beta"])
        engine = make_engine(tmp_path)
        assert len(engine.select_skills("  ")) == 2

    def test_all_inject_env_override(self, tmp_path):
        write_skill(tmp_path, "a", "alpha description body", "A_BODY", tags=["alpha"])
        write_skill(tmp_path, "b", "beta description body", "B_BODY", tags=["beta"])
        engine = make_engine(tmp_path)
        os.environ["NEXUS_ALL_SKILLS_INJECT"] = "1"
        try:
            all_skills = engine.select_skills("something totally unrelated")
            assert len(all_skills) == 2
            prompt = engine.get_active_prompt("something totally unrelated")
            assert "A_BODY" in prompt and "B_BODY" in prompt
        finally:
            del os.environ["NEXUS_ALL_SKILLS_INJECT"]

    def test_get_active_prompt_uses_selection(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        write_skill(tmp_path, "calendar", "Schedule meetings and manage calendar events",
                    "CALENDAR_BODY", tags=["calendar", "meetings"])
        engine = make_engine(tmp_path)
        prompt = engine.get_active_prompt("review the pull request please")
        assert "CODE_REVIEW_BODY" in prompt
        assert "CALENDAR_BODY" not in prompt


# ─── skill health + isolation ─────────────────────────────────────

class TestHealthIsolation:
    def test_unhealthy_after_three_consecutive_errors_excluded(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        write_skill(tmp_path, "git", "Git version control workflows, commits, branches",
                    "GIT_BODY", tags=["git", "version-control"])
        engine = make_engine(tmp_path)

        # Two failures: still healthy.
        engine.record_use("code-review", success=False)
        engine.record_use("code-review", success=False)
        assert engine.is_healthy("code-review") is True

        # Third consecutive failure: marked unhealthy.
        engine.record_use("code-review", success=False)
        assert engine.is_healthy("code-review") is False
        assert engine._health["code-review"].consecutive_failures == 3

        # Excluded from selection even for its best-matching task.
        selected = engine.select_skills("review quality python code", limit=3)
        assert "code-review" not in {s.id for s in selected}
        assert "git" not in {s.id for s in selected}  # no overlap either

    def test_success_resets_unhealthy(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        engine = make_engine(tmp_path)
        for _ in range(3):
            engine.record_use("code-review", success=False)
        assert engine.is_healthy("code-review") is False
        engine.record_use("code-review", success=True)
        assert engine.is_healthy("code-review") is True
        assert engine._health["code-review"].consecutive_failures == 0

    def test_broken_skill_never_blocks_engine(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        # A malformed SKILL.md (undecodable bytes) must not break discovery.
        broken = Path(tmp_path) / ".opencode" / "skills" / "broken"
        broken.mkdir(parents=True, exist_ok=True)
        (broken / "SKILL.md").write_bytes(b"\xff\xfe\x00broken")
        engine = make_engine(tmp_path)
        assert engine.get_skill("code-review") is not None
        assert "broken" not in {s.id for s in engine._skills.values()}  # skipped, not fatal
        assert engine.get_active_prompt("review code")  # never empty from a crash


# ─── adapter instruction block ────────────────────────────────────

class TestAdapter:
    def test_parse_skill_md(self, tmp_path):
        p = tmp_path / "custom" / "SKILL.md"
        p.parent.mkdir(parents=True)
        p.write_text(
            "---\n"
            'name: fancy-skill\n'
            'description: "Fancy description"\n'
            "metadata:\n"
            "  hermes:\n"
            "    tags: [fancy, neat]\n"
            "---\n"
            "Step 1: do the thing.\n"
            "Step 2: profit.\n",
            encoding="utf-8",
        )
        parsed = parse_skill_md(p.read_text(encoding="utf-8"))
        assert parsed["name"] == "fancy-skill"
        assert parsed["description"] == "Fancy description"
        assert "fancy" in parsed["tags"] and "neat" in parsed["tags"]
        assert "Step 1: do the thing." in parsed["prompt"]

    def test_adapter_returns_real_instructions(self, tmp_path, monkeypatch):
        write_skill(tmp_path, "email", "Manage email drafts and send messages",
                    "EXPERIMENTAL_EMAIL_INSTRUCTION_BODY", tags=["email"])

        async def _run():
            adapter = SkillToolAdapter(
                name="email",
                skill_path=str(Path(tmp_path) / ".opencode" / "skills" / "email" / "SKILL.md"),
            )
            return await adapter.execute()

        result = asyncio.run(_run())
        output = result.output
        assert "[SKILL_ACTIVE" not in output  # no echo of the old marker
        assert "EXPERIMENTAL_EMAIL_INSTRUCTION_BODY" in output
        assert "Instructions" in output
        assert "Description:" in output
        assert "Skill: email" in output
        assert result.status == "ok"
        assert result.metadata["skill_name"] == "email"
        assert "email" in (result.metadata.get("tags") or [])

    def test_adapter_fallback_without_skill_path(self):
        async def _run():
            adapter = SkillToolAdapter(name="legacy", skill_prompt="LEGACY_PROMPT")
            return await adapter.execute()

        result = asyncio.run(_run())
        assert "LEGACY_PROMPT" in result.output

    def test_build_instruction_block_shape(self):
        assert "Instructions" in build_instruction_block("x", "PROMPT")
        assert build_instruction_block("x", "PROMPT").startswith("Skill: x")

    def test_skill_executor_failure_is_not_reported_as_success(self):
        async def failing_llm(_prompt):
            raise RuntimeError("provider unavailable")

        async def _run():
            executor = SkillExecutor(
                name="research",
                skill_prompt="Research the requested topic",
                llm_call=failing_llm,
            )
            return await executor.execute(args="latest findings")

        result = asyncio.run(_run())
        assert result.status == "error"
        assert result.success is False
        assert result.error == "provider unavailable"
        assert result.error_info["type"] == "RuntimeError"
        assert result.metadata["execution_failed"] is True


# ─── experience tracking ──────────────────────────────────────────

class TestExperience:
    def test_experience_records_and_reloads(self, tmp_path):
        exp_path = tmp_path / "experience.json"
        store = SkillExperience(str(exp_path))
        assert store.record("email", success=True) is True
        assert store.record("email", success=False) is True
        assert store.record("git", success=True) is True

        exp = store.get("email")
        assert exp["uses"] == 2
        assert exp["successes"] == 1
        assert exp["failures"] == 1
        assert exp["last_used"] > 0
        assert store.get("git")["uses"] == 1
        assert store.get("missing") == {}

        # Persisted: a fresh store reading the same file sees the data.
        reloaded = SkillExperience(str(exp_path))
        assert reloaded.get("email")["uses"] == 2
        assert reloaded.get("git")["successes"] == 1
        assert json.loads(exp_path.read_text(encoding="utf-8"))["email"]["uses"] == 2

    def test_experience_never_raises(self):
        store = SkillExperience(str(Path("Z:/nonexistent_dir/exp.json")))
        # Record succeeds in memory even when the on-disk write is impossible.
        assert store.record("anything", success=True) is True
        assert store.get("anything")["uses"] == 1
        assert store.record("") is False
        assert store.summary()["total_uses"] >= 0

    def test_engine_wires_experience(self, tmp_path):
        write_skill(tmp_path, "code-review", "Review GitHub pull requests for quality issues",
                    "CODE_REVIEW_BODY", tags=["code", "review", "github"])
        engine = make_engine(tmp_path)
        engine.record_use("code-review", success=True)
        engine.record_use("code-review", success=False)
        assert engine.get_experience("code-review")["uses"] == 2
        assert len(engine.get_experience()) >= 1
