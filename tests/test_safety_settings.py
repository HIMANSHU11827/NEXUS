"""Tests for the persistent Safety settings system (safety/safety_store.py).

All state is isolated to a temporary config file via ``_CONFIG_PATH``
monkeypatching, so the real ``config/nexus_config.yaml`` is never modified.
Server tests additionally redirect ``server._CONFIG_PATH`` so runtime-preference
persistence also stays inside the temp file.
"""

import os

import pytest
import yaml

import safety.safety_store as safety_store

EXPECTED_PERMISSION_MODES = {"automatic", "ask", "read_only", "restricted", "trusted", "custom", "deny_all"}
EXPECTED_SANDBOX_MODES = {"no_tools", "read_only", "workspace", "restricted", "isolated_temp", "custom", "no_sandbox"}
SANDBOX_METADATA_KEYS = {
    "filesystem_scope",
    "workspace_access",
    "additional_dir_access",
    "write_access",
    "network_access",
    "env_access",
    "child_process_access",
    "temp_dir_access",
    "system_dir_access",
    "resource_limits",
    "isolation_level",
}


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the Safety store at a throwaway config file, seeded with defaults."""
    config_path = tmp_path / "nexus_config.yaml"
    monkeypatch.setattr(safety_store, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(safety_store, "_STATE", None)
    safety_store._SCAN_COUNTS.update({"blocked": 0, "redacted": 0, "pending": 0, "last_scan": None})
    result = safety_store.reset()
    assert result.get("ok") is True
    yield safety_store
    safety_store.reset()
    monkeypatch.setattr(safety_store, "_STATE", None)


# ── 1. Separation of the three systems (workspace / permission / sandbox) ─────

def test_save_never_changes_workspace_root(isolated_store):
    ws_before = safety_store.workspace_root()
    state = safety_store.get_state()
    result = safety_store.save(state)
    assert result.get("ok") is True
    assert result.get("workspace_unchanged") is True
    assert safety_store.workspace_root() == ws_before


def test_set_permission_and_sandbox_never_change_workspace_root(isolated_store):
    ws_before = safety_store.workspace_root()
    safety_store.set_permission_mode("ask")
    safety_store.set_sandbox_mode("read_only")
    assert safety_store.workspace_root() == ws_before
    # Re-read from disk to confirm nothing leaked into the workspace config.
    safety_store.get_state(refresh=True)
    assert safety_store.workspace_root() == ws_before
    safety_store.set_permission_mode("automatic")
    safety_store.set_sandbox_mode("workspace")


# ── 2. Permission modes ───────────────────────────────────────────────────────

def test_seven_permission_modes_exist(isolated_store):
    assert set(safety_store.PERMISSION_MODES) == EXPECTED_PERMISSION_MODES


def test_set_permission_mode_accepts_all_seven_and_rejects_invalid(isolated_store):
    for mode in EXPECTED_PERMISSION_MODES:
        result = safety_store.set_permission_mode(mode)
        assert result.get("ok") is True, f"mode {mode!r} rejected: {result}"
        assert safety_store.get_state()["permission_mode"] == mode
    invalid = safety_store.set_permission_mode("not-a-real-mode")
    assert invalid.get("ok") is False
    assert safety_store.get_state()["permission_mode"] in EXPECTED_PERMISSION_MODES
    safety_store.set_permission_mode("automatic")


# ── 3. Sandbox modes ──────────────────────────────────────────────────────────

def test_seven_sandbox_modes_exist_with_metadata(isolated_store):
    assert set(safety_store.SANDBOX_MODES) == EXPECTED_SANDBOX_MODES
    for mode, meta in safety_store.SANDBOX_MODES.items():
        assert isinstance(meta, dict), mode
        assert meta.get("label"), mode
        assert SANDBOX_METADATA_KEYS.issubset(meta.keys()), f"{mode} missing sandbox metadata"


def test_set_sandbox_mode_accepts_all_seven_and_rejects_invalid(isolated_store):
    for mode in EXPECTED_SANDBOX_MODES:
        result = safety_store.set_sandbox_mode(mode)
        assert result.get("ok") is True, f"mode {mode!r} rejected: {result}"
        assert safety_store.get_state()["sandbox_mode"] == mode
    invalid = safety_store.set_sandbox_mode("not-a-real-sandbox")
    assert invalid.get("ok") is False
    assert safety_store.get_state()["sandbox_mode"] in EXPECTED_SANDBOX_MODES
    safety_store.set_sandbox_mode("workspace")


# ── 4. Mode reduction enforcement via the permission engine overlay ───────────

def test_permission_overlay_deny_all_denies_read(isolated_store):
    from permissions import PermissionSystem
    system = PermissionSystem()
    safety_store.set_permission_mode("deny_all")
    try:
        result = system.check("read_file", "foo.txt")
    finally:
        safety_store.set_permission_mode("automatic")
    assert result.granted is False
    assert result.decision.get("source") == "safety:deny_all"


def test_permission_overlay_automatic_falls_through(isolated_store):
    from permissions import PermissionSystem
    system = PermissionSystem()
    safety_store.set_permission_mode("automatic")
    result = system.check("read_file", "foo.txt")
    source = result.decision.get("source") or ""
    assert not source.startswith("safety:"), f"overlay denied under automatic: {source}"


# ── 5. Protected paths ────────────────────────────────────────────────────────

def test_default_protected_paths_nonempty_and_env_write_denied(isolated_store):
    state = safety_store.get_state()
    assert state["protected_paths"], "default protected paths should not be empty"
    assert any(p.get("pattern") == ".env" for p in state["protected_paths"])
    result = safety_store.enforce_file_action("write", ".env")
    assert result.allowed is False
    assert result.decision == "deny"
    assert result.category == "protected_path"


def test_add_and_remove_user_protected_path(isolated_store):
    add = safety_store.add_protected_path({"pattern": "secrets/config.toml", "reason": "test rule"})
    assert add.get("ok") is True
    state = safety_store.get_state()
    assert any(p["pattern"] == "secrets/config.toml" and p["source"] == "user" for p in state["protected_paths"])
    denied = safety_store.enforce_file_action("write", "secrets/config.toml")
    assert denied.allowed is False
    removed = safety_store.remove_protected_path("secrets/config.toml")
    assert removed.get("ok") is True
    state = safety_store.get_state()
    assert not any(p["pattern"] == "secrets/config.toml" for p in state["protected_paths"])


def test_mandatory_rules_cannot_be_removed(isolated_store):
    result = safety_store.remove_protected_path(".git/**")
    assert result.get("ok") is False
    state = safety_store.get_state()
    assert any(p["pattern"] == ".git/**" for p in state["protected_paths"])


# ── 6. Secret redaction ───────────────────────────────────────────────────────

def test_redact_text_redacts_secret_values(isolated_store):
    redacted = safety_store.redact_text("api_key=abc123")
    assert "[REDACTED:" in redacted
    assert "abc123" not in redacted
    scan = safety_store.redaction_scan("token=supersecretvalue")
    assert isinstance(scan, dict)
    assert scan["matches"] >= 1


def test_secret_counts_returns_only_counts(isolated_store):
    counts = safety_store.secret_counts()
    assert isinstance(counts, dict)
    assert set(counts) == {"protected", "blocked", "redacted", "pending", "last_scan"}
    for key in ("protected", "blocked", "redacted", "pending"):
        assert isinstance(counts[key], int)


# ── 7. Network policies ───────────────────────────────────────────────────────

def test_six_network_policies_exist(isolated_store):
    assert len(safety_store.NETWORK_POLICIES) == 6
    assert set(safety_store.NETWORK_POLICIES) == {
        "deny_all", "ask", "approved_domains", "browser_only", "registries_only", "allow_all",
    }


def test_network_cloud_metadata_url_never_silently_allowed(isolated_store):
    state = safety_store.get_state()
    assert state["network"]["block_cloud_metadata"] is True
    result = safety_store.enforce_network("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    assert result.decision != "allow", "metadata URL must not be auto-allowed"
    deny = safety_store.set_network({"policy": "deny_all"})
    assert deny.get("ok") is True
    blocked = safety_store.enforce_network("http://169.254.169.254/latest/meta-data/")
    assert blocked.allowed is False
    assert blocked.decision == "deny"


def test_network_enforce_respects_allowlist(isolated_store):
    result = safety_store.set_network({"policy": "approved_domains", "allowlist": ["example.com"]})
    assert result.get("ok") is True
    allowed = safety_store.enforce_network("http://example.com/data")
    assert allowed.allowed is True
    assert allowed.decision == "allow"
    blocked = safety_store.enforce_network("http://other-domain.org/data")
    assert blocked.allowed is False
    assert blocked.decision == "deny"


# ── 8. Command policies ───────────────────────────────────────────────────────

def test_twenty_six_command_categories_exist(isolated_store):
    assert len(safety_store.COMMAND_CATEGORIES) == 26
    assert {c["id"] for c in safety_store.COMMAND_CATEGORIES} == set(safety_store.get_state()["command_policies"])


def test_destructive_command_denied_under_defaults(isolated_store):
    result = safety_store.enforce_command("rm -rf /")
    assert result.allowed is False
    assert result.decision in ("deny", "block")
    assert result.category == "destructive_commands"


def test_safe_read_command_allowed_under_defaults(isolated_store):
    result = safety_store.enforce_command("ls -la")
    assert result.allowed is True
    assert result.decision == "allow"
    assert result.requires_approval is False


# ── 9. Temp permissions + approvals ───────────────────────────────────────────

def test_temp_permission_lifecycle(isolated_store):
    add = safety_store.add_temp_permission({"permission": "run_command", "duration_seconds": 3600, "scope": "workspace"})
    assert add.get("ok") is True
    listed = safety_store.list_temp_permissions()
    assert listed, "no temp permissions listed"
    permission = listed[0]
    assert permission["permission"] == "run_command"
    assert permission["expired"] is False
    original_expiry = permission["expires_at"]
    extended = safety_store.extend_temp_permission(permission["id"], seconds=600)
    assert extended.get("ok") is True
    assert safety_store.list_temp_permissions()[0]["expires_at"] >= original_expiry
    revoked = safety_store.revoke_temp_permission(permission["id"])
    assert revoked.get("ok") is True
    assert safety_store.list_temp_permissions() == []


def test_approval_lifecycle(isolated_store):
    recorded = safety_store.record_approval({"action": "write_file", "permission": "write_file", "decision": "allow", "scope": "once"})
    assert recorded.get("ok") is True
    approvals = safety_store.list_approvals()
    assert approvals, "no approvals listed"
    approval = approvals[0]
    assert approval["action"] == "write_file"
    filtered = safety_store.list_approvals({"decision": "allow"})
    assert any(a["id"] == approval["id"] for a in filtered)
    revoked = safety_store.revoke_approval(approval["id"])
    assert revoked.get("ok") is True
    assert safety_store.list_approvals() == []


# ── 10. Presets ───────────────────────────────────────────────────────────────

def test_six_presets_including_custom(isolated_store):
    presets = safety_store.list_presets()
    assert [p["id"] for p in presets] == ["maximum_protection", "recommended", "development", "read_only", "offline", "custom"]


def test_apply_preset_recommended(isolated_store):
    ws_before = safety_store.workspace_root()
    result = safety_store.apply_preset("recommended")
    assert result.get("ok") is True
    state = safety_store.get_state()
    assert state["permission_mode"] == "automatic"
    assert state["sandbox_mode"] == "workspace"
    assert safety_store.workspace_root() == ws_before


def test_apply_unknown_preset_rejected(isolated_store):
    result = safety_store.apply_preset("unknown")
    assert result.get("ok") is False


# ── 11. Legacy sync ───────────────────────────────────────────────────────────

def test_sync_permission_from_legacy(isolated_store):
    assert safety_store.sync_permission_from_legacy("allowlist") == "restricted"
    assert safety_store.sync_permission_from_legacy("auto") == "automatic"
    assert safety_store.get_state()["permission_mode"] == "automatic"


def test_sync_sandbox_from_legacy(isolated_store):
    assert safety_store.sync_sandbox_from_legacy("docker") == "isolated_temp"
    assert safety_store.sync_sandbox_from_legacy("no_sandbox") == "no_sandbox"
    assert safety_store.get_state()["sandbox_mode"] == "no_sandbox"
    safety_store.set_sandbox_mode("workspace")


# ── 12. Server endpoints (minimal) ────────────────────────────────────────────

@pytest.fixture
def safety_server(tmp_path, monkeypatch):
    """TestClient for the real FastAPI app, fully redirected to a temp config."""
    monkeypatch.setenv("NEXUS_ALLOW_LOCAL_ANON", "true")
    import server
    import authentication

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    config_path = tmp_path / "nexus_config.yaml"

    monkeypatch.setattr(safety_store, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(safety_store, "_STATE", None)
    monkeypatch.setattr(server, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(server, "_RUNTIME_SETTINGS", dict(server._RUNTIME_SETTINGS, workspace_root=str(ws_dir)))
    monkeypatch.setattr(server, "_workspace_summary_snapshot_path", lambda: str(tmp_path / "workspace_summary.json"))
    monkeypatch.setattr(authentication, "is_loopback_request", lambda request: True)
    monkeypatch.setattr(server, "is_loopback_request", lambda request: True)

    config_path.write_text(
        yaml.safe_dump(
            {"runtime": {"workspace_root": str(ws_dir), "permission_mode": "auto", "sandbox_tier": "normal"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = safety_store.reset()
    assert result.get("ok") is True
    yield server
    safety_store.reset()
    monkeypatch.setattr(safety_store, "_STATE", None)


def test_server_safety_summary_endpoint(safety_server):
    from fastapi.testclient import TestClient
    with TestClient(safety_server.app) as client:
        response = client.get("/api/safety/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["permission_mode"] == "automatic"
    assert data["sandbox_mode"] == "workspace"


def test_server_safety_meta_endpoint(safety_server):
    from fastapi.testclient import TestClient
    with TestClient(safety_server.app) as client:
        response = client.get("/api/safety/meta")
    assert response.status_code == 200
    data = response.json()
    assert len(data["permission_modes"]) == 7
    assert len(data["sandbox_modes"]) == 7


def test_server_safety_save_endpoint(safety_server):
    from fastapi.testclient import TestClient
    ws_before = safety_store.workspace_root()
    with TestClient(safety_server.app) as client:
        response = client.post("/api/safety/save", json=safety_store.get_state())
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("workspace_unchanged") is True
    assert safety_store.workspace_root() == ws_before
    assert safety_store.get_state()["permission_mode"] == "automatic"
    assert safety_store.get_state()["sandbox_mode"] == "workspace"


def test_server_safety_permission_mode_endpoint(safety_server):
    from fastapi.testclient import TestClient
    ws_before = safety_store.workspace_root()
    with TestClient(safety_server.app) as client:
        response = client.post("/api/safety/permission-mode", json={"mode": "ask"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True
    assert data.get("mode") == "ask"
    assert safety_store.workspace_root() == ws_before
    assert safety_store.get_state()["permission_mode"] == "ask"
    safety_store.set_permission_mode("automatic")
    safety_store.set_sandbox_mode("workspace")
    assert safety_store.get_state()["permission_mode"] == "automatic"
    assert safety_store.get_state()["sandbox_mode"] == "workspace"
