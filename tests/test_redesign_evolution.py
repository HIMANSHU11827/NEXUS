"""Tests for the evolution + forge redesign (self-evolution system).

Covers, in order:
1. Version unification — all forges return real X.Y.Z version strings from ONE
   VersionManager-backed path (no per-forge local bumping).
2. Validation gate — validate_forge_output accepts good payloads and rejects
   secret-like tokens, empty output, and out-of-allowed-dir write paths; a
   rejected forge does NOT write the artifact.
3. Audit trail — EvolutionLedger.log_forge emits structured records and
   rollback() restores the previous version (both JSON artifacts and SKILL.md
   front-matter), plus full removal of a freshly-created artifact.
4. Fault isolation — a forced failure inside a guarded forge returns a
   structured {status: "failed", reason, evidence} and never raises.
5. V5 honesty — memory_forge / tool_forge reject provider-error or
   empty/whitespace evidence (never crystallize an error message).
"""
__version__ = "1.0.0"
import io
import json
import os
import re

import pytest

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.memory_forge.scripts.forge import MemoryForge
from evolution.quality import looks_like_provider_error, validate_forge_output
from evolution.tool_forge.scripts.engine import ToolForge
from versioning.version.scripts.version import VersionManager
from evolution.skill_forge.scripts.forge import SkillForge
from evolution.plugin_forge.scripts.forge import PluginForge
from evolution.knowledge_forge.scripts.forge import KnowledgeForge

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

_STRUCTURED_FIELDS = (
    "ts", "kind", "name", "action",
    "old_version", "new_version", "evidence",
    "tests_passed", "promoted", "rollback_info",
)


def _txn_versions(tmp_path):
    """Fresh VersionManager — proves one shared, durable version registry."""
    return VersionManager(str(tmp_path)).list_versions()


# ── 1. Version unification ────────────────────────────────────────────────

class TestVersionUnification:
    def test_all_forges_return_real_versions_from_one_path(self, tmp_path):
        # Every forge returns a real X.Y.Z string on both create and refine,
        # and each refined version is visible from a single fresh VersionManager
        # (the one JSON-backed registry under root/.nexus/versions.json).
        mf = MemoryForge(str(tmp_path))
        mr1 = mf.forge("Test Memory", "content for unification", importance=7, tags=["a"])
        assert mr1["created"] is True and mr1["promoted"] is True
        assert VERSION_RE.match(str(mr1["version"]))
        mr2 = mf.refine(mr1["name"], {"content": "updated"})
        assert mr2["refined"] is True
        assert VERSION_RE.match(str(mr2["version"]))
        assert mr2["version"] != mr1["version"]
        assert _txn_versions(tmp_path).get(mr1["name"]) == mr2["version"]

        tf = ToolForge(str(tmp_path))
        tr1 = tf.forge({"name": "unify_tool", "description": "unification tool"})
        assert tr1["created"] is True
        assert VERSION_RE.match(str(tr1["version"]))
        tr2 = tf.refine(tr1["name"], {"description": "updated"})
        assert tr2["refined"] is True
        assert VERSION_RE.match(str(tr2["version"]))
        assert _txn_versions(tmp_path).get(tr1["name"]) == tr2["version"]

        sf = SkillForge(str(tmp_path))
        sr1 = sf.forge("unify-skill", "unification skill")
        assert sr1["created"] is True
        assert VERSION_RE.match(str(sr1["version"]))
        sr2 = sf.refine(sr1["name"])
        assert sr2["refined"] is True
        assert VERSION_RE.match(str(sr2["version"]))
        assert _txn_versions(tmp_path).get(sr1["name"]) == sr2["version"]

        pf = PluginForge(str(tmp_path))
        pr1 = pf.forge("unify_plugin", "unification plugin")
        assert pr1["created"] is True
        assert VERSION_RE.match(str(pr1["version"]))
        pr2 = pf.refine(pr1["name"], {"description": "updated"})
        assert pr2["refined"] is True
        assert VERSION_RE.match(str(pr2["version"]))
        assert _txn_versions(tmp_path).get(pr1["name"]) == pr2["version"]

        kf = KnowledgeForge(str(tmp_path))
        kr1 = kf.forge("unify_topic", "knowledge content", key_concepts=["x"], tags=["t"])
        assert kr1["created"] is True
        assert VERSION_RE.match(str(kr1["version"]))
        kr2 = kf.refine(kr1["name"], {"content": "updated knowledge"})
        assert kr2["refined"] is True
        assert VERSION_RE.match(str(kr2["version"]))
        assert _txn_versions(tmp_path).get(kr1["name"]) == kr2["version"]

        # everything that survived in the shared registry is a real version
        for version in _txn_versions(tmp_path).values():
            assert VERSION_RE.match(version)

    def test_version_manager_ensure_and_bump_are_self_consistent(self, tmp_path):
        vm = VersionManager(str(tmp_path))
        assert vm.ensure("thing_a") == "1.0.0"
        assert vm.bump("thing_a", "minor") == "1.1.0"
        assert vm.bump("thing_a", "major") == "2.0.0"
        assert vm.bump("thing_a", "patch") == "2.0.1"
        # bump with an explicit current seed respects pre-existing on-disk version
        vm2 = VersionManager(str(tmp_path))
        assert vm2.bump("legacy_b", "minor", current="3.7.2") == "3.8.0"
        assert VersionManager(str(tmp_path)).get_version("legacy_b") == "3.8.0"


# ── 2. Validation gate ────────────────────────────────────────────────────

class TestValidationGate:
    def test_accepts_good_output(self):
        result = validate_forge_output("memory", {
            "title": "t", "content": "a real learning", "version": "1.0.0",
            "importance": 5, "tags": ["a"],
        })
        assert result["valid"] is True
        assert result["status"] == "ok"

    def test_rejects_secret_like_tokens(self):
        result = validate_forge_output("memory", {
            "title": "key material", "content": "the token is sk-abcdefghijklmnopqrstuvwxyz123456",
            "version": "1.0.0",
        })
        assert result["valid"] is False
        assert result["status"] == "rejected"
        assert "secret" in result["reason"].lower()

    def test_rejects_empty_str(self):
        result = validate_forge_output("memory", {
            "title": "empty", "content": "   ", "version": "1.0.0",
        })
        assert result["valid"] is False

    def test_rejects_missing_required_field(self):
        result = validate_forge_output("tool", {
            "name": "x", "description": "d", "defaults": {}, "permissions": {},
        })  # version missing
        assert result["valid"] is False
        assert any("version" in e for e in result["errors"])

    def test_rejects_out_of_allowed_dir(self, tmp_path):
        evil = os.path.join(str(tmp_path), "..", "..", "orchestrators", "evil.json")
        result = validate_forge_output("memory", {
            "title": "t", "content": "c", "version": "1.0.0",
        }, root=str(tmp_path), write_path=evil)
        assert result["valid"] is False
        assert "outside allowed dir" in result["reason"]

    def test_accepts_inside_allowed_dir(self, tmp_path):
        good = os.path.join(str(tmp_path), "data", "memory_forge", "m", "memory.json")
        result = validate_forge_output("memory", {
            "title": "t", "content": "c", "version": "1.0.0",
        }, root=str(tmp_path), write_path=good)
        assert result["valid"] is True

    def test_rejected_forge_does_not_write(self, tmp_path):
        forge = MemoryForge(str(tmp_path))
        result = forge.forge("leaky_mem", "the api key is sk-abcdefghijklmnopqrstuvwxyz123456")
        assert result.get("status") == "rejected"
        assert result.get("promoted") is False
        assert not os.path.exists(
            os.path.join(str(tmp_path), "data", "memory_forge", "leaky_mem", "memory.json")
        )


# ── 3. Audit trail + rollback ─────────────────────────────────────────────

class TestAuditTrailAndRollback:
    def _memory_entries(self, tmp_path, name):
        return [
            e for e in EvolutionLedger(str(tmp_path))._read_all()
            if e.get("kind") == "memory" and e.get("name") == name
        ]

    def test_ledger_records_structured_entries(self, tmp_path):
        forge = MemoryForge(str(tmp_path))
        created = forge.forge("rollback_memory", "original content")
        assert created["created"] is True
        name = created["name"]
        forge.refine(name, {"content": "updated content"})
        entries = self._memory_entries(tmp_path, name)
        assert len(entries) == 2
        for entry in entries:
            assert set(_STRUCTURED_FIELDS) <= set(entry)
        assert entries[0]["action"] == "forge"
        assert entries[0]["old_version"] is None
        assert entries[0]["new_version"] == "1.0.0"
        assert entries[0]["promoted"] is True
        assert entries[0]["rollback_info"]["path"].endswith("memory.json")
        assert entries[1]["action"] == "refine"
        assert entries[1]["old_version"] == "1.0.0"
        assert entries[1]["new_version"] == created["version"] is False or entries[1]["new_version"] != "1.0.0"

    def test_rollback_restores_json_version(self, tmp_path):
        forge = MemoryForge(str(tmp_path))
        created = forge.forge("rollback_memory", "original content")
        name = created["name"]
        refined = forge.refine(name, {"content": "updated content"})
        assert refined["version"] != "1.0.0"

        ledger = EvolutionLedger(str(tmp_path))
        rb = ledger.rollback("memory", name)
        assert rb.get("rolled_back") is True
        assert rb.get("restored") == "1.0.0"

        # The artifact on disk reflects the restored prior version.
        mem_path = os.path.join(str(tmp_path), "data", "memory_forge", name, "memory.json")
        with open(mem_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == "1.0.0"

    def test_rollback_restores_skill_frontmatter(self, tmp_path):
        forge = SkillForge(str(tmp_path))
        created = forge.forge("rb-skill", "original skill")
        assert created["created"] is True
        name = created["name"]
        refined = forge.refine(name)
        assert refined["version"] != "1.0.0"

        ledger = EvolutionLedger(str(tmp_path))
        rb = ledger.rollback("skill", name)
        assert rb.get("rolled_back") is True
        assert rb.get("restored") == "1.0.0"

        skill_md = os.path.join(str(tmp_path), "skills", name, "SKILL.md")
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        assert re.search(r"version:\s*1\.0\.0", content)

    def test_rollback_removes_created_artifact(self, tmp_path):
        forge = MemoryForge(str(tmp_path))
        created = forge.forge("drop_me", "fresh content")
        name = created["name"]
        target = os.path.join(str(tmp_path), "data", "memory_forge", name, "memory.json")
        assert os.path.exists(target)

        ledger = EvolutionLedger(str(tmp_path))
        rb = ledger.rollback("memory", name)
        assert rb.get("rolled_back") is True
        assert rb.get("deleted") is True
        assert not os.path.exists(target)

    def test_rollback_unknown_name_is_honest(self, tmp_path):
        ledger = EvolutionLedger(str(tmp_path))
        rb = ledger.rollback("memory", "never_created")
        assert rb.get("rolled_back") is False
        assert rb.get("reason") == "no ledger history"


# ── 4. Fault isolation ────────────────────────────────────────────────────

class TestFaultIsolation:
    def test_memory_forge_crash_returns_structured_failure(self, tmp_path, monkeypatch):
        import evolution.memory_forge.scripts.forge as forge_module

        def _boom(*args, **kwargs):
            raise RuntimeError("forced memory forge crash")

        monkeypatch.setattr(forge_module, "validate_forge_output", _boom)
        forge = MemoryForge(str(tmp_path))

        result = forge.forge("crash_memory", "would-be content")  # must NOT raise
        assert isinstance(result, dict)
        assert result.get("status") == "failed"
        assert result.get("created") is False
        assert result.get("promoted") is False
        assert "RuntimeError" in result.get("reason", "")
        assert "evidence" in result  # stdout/stderr preserved as evidence
        # nothing was persisted
        assert not os.path.exists(
            os.path.join(str(tmp_path), "data", "memory_forge", "crash_memory", "memory.json")
        )

    def test_refine_crash_returns_structured_failure(self, tmp_path, monkeypatch):
        import evolution.tool_forge.scripts.engine as engine_module

        forge = ToolForge(str(tmp_path))
        created = forge.forge({"name": "crash_tool", "description": "a tool"})
        assert created.get("created") is True

        def _boom(*args, **kwargs):
            raise ValueError("forced refine crash")

        monkeypatch.setattr(engine_module, "validate_forge_output", _boom)
        result = forge.refine(created["name"], {"description": "updated"})  # must NOT raise
        assert result.get("status") == "failed"
        assert "ValueError" in result.get("reason", "")
        assert result.get("promoted") is False


# ── 5. V5 honesty: never crystallize provider/error evidence ──────────────

class TestEvidenceHonesty:
    @pytest.mark.parametrize("evidence", [
        "OpenAI API error: rate limit exceeded, retrying...",
        "Traceback (most recent call last): ProviderError: context length exceeded",
        "Failed to connect: provider 500 Internal Server Error",
        "connection refused while calling the remote tool: non-zero exit code",
        "",
        "   \n\t ",
    ])
    def test_memory_forge_rejects_error_or_empty_evidence(self, tmp_path, evidence):
        forge = MemoryForge(str(tmp_path))
        result = forge.forge("learning_x", evidence)
        assert result.get("created") is False
        assert result.get("status") == "rejected"
        assert result.get("promoted") is False
        assert not os.path.exists(
            os.path.join(str(tmp_path), "data", "memory_forge", "learning_x", "memory.json")
        )

    def test_memory_forge_accepts_good_evidence(self, tmp_path):
        forge = MemoryForge(str(tmp_path))
        result = forge.forge("learning_y", "The user prefers concise answers with code.")
        assert result.get("created") is True
        assert result.get("promoted") is True
        assert result.get("status") == "ok"

    def test_tool_forge_rejects_error_description(self, tmp_path):
        forge = ToolForge(str(tmp_path))
        result = forge.forge({
            "name": "bad_tool",
            "description": "Failed to call provider: API error 500 - retrying",
        })
        assert result.get("created") is False
        assert result.get("status") == "rejected"
        assert result.get("promoted") is False
        assert not os.path.exists(os.path.join(str(tmp_path), "tools", "bad_tool"))

    def test_provider_error_detector(self):
        assert looks_like_provider_error("OpenAI API error: rate limit exceeded") is True
        assert looks_like_provider_error("Traceback ... ProviderError") is True
        assert looks_like_provider_error("") is True
        assert looks_like_provider_error("   ") is True
        assert looks_like_provider_error("Users prefer batch answers") is False
        assert looks_like_provider_error("Learned that the router prefers tool calls") is False
