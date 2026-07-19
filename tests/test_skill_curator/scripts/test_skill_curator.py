__version__ = "1.0.0"

import json
import os

import pytest

from evolution.curator.scripts.curator import SkillCurator


class TestSkillCurator:
    @pytest.fixture
    def curator(self, tmp_path):
        c = SkillCurator(str(tmp_path))
        c.stale_after_days = 0  # force immediate staleness for testing
        return c

    def test_init(self, curator):
        assert curator.enabled
        assert curator.stale_after_days == 0
        assert not curator._usage_cache

    def test_usage_file_created(self, curator):
        assert os.path.isfile(curator.usage_file)
        with open(curator.usage_file) as f:
            data = json.load(f)
        assert data == {}

    def test_record_use(self, curator):
        usage = curator.record_use("my_skill")
        assert usage["use_count"] == 1
        assert usage["state"] == "active"
        assert usage["last_activity_at"] is not None

    def test_record_use_increments(self, curator):
        curator.record_use("my_skill")
        usage = curator.record_use("my_skill")
        assert usage["use_count"] == 2

    def test_pin_skill(self, curator):
        curator.record_use("my_skill")
        result = curator.pin_skill("my_skill")
        assert result["success"]
        assert result["action"] == "pinned"
        usage = curator._get_usage("my_skill")
        assert usage["state"] == "pinned"

    def test_unpin_skill(self, curator):
        curator.record_use("my_skill")
        curator.pin_skill("my_skill")
        result = curator.unpin_skill("my_skill")
        assert result["success"]
        assert result["action"] == "unpinned"
        usage = curator._get_usage("my_skill")
        assert usage["state"] == "active"

    def test_archive_pinned_skill_fails(self, curator):
        curator.pin_skill("pinned_skill")
        result = curator.archive_skill("pinned_skill")
        assert not result["success"]
        assert "pinned" in result.get("error", "")

    def test_archive_nonexistent_skill(self, curator):
        result = curator.archive_skill("nonexistent")
        assert not result["success"]

    def test_restore_nonexistent(self, curator):
        result = curator.restore_skill("nonexistent")
        assert not result["success"]

    def test_get_stats(self, curator):
        stats = curator.get_stats()
        assert "enabled" in stats
        assert "total_skills" in stats
        assert stats["config"]["stale_after_days"] == 0

    def test_set_config(self, curator):
        curator.set_config(stale_after_days=15, enabled=False)
        assert curator.stale_after_days == 15
        assert not curator.enabled

    def test_list_skills_empty(self, curator):
        assert curator.list_skills() == []

    def test_list_skills_filter_state(self, curator):
        curator.record_use("active_skill")
        curator.pin_skill("pinned_skill")
        pinned = curator.list_skills(state="pinned")
        assert all(s["state"] == "pinned" or s["pinned"] for s in pinned)

    def test_run_disabled(self, curator):
        curator.enabled = False
        result = curator.run_once()
        assert result["status"] == "disabled"

    def test_run_enabled_no_skills(self, curator):
        result = curator.run_once()
        assert result["status"] == "ok"
        assert result["archived"] == 0
