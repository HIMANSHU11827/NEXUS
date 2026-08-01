from permissions import PermissionMode, PermissionSystem


def _with_clean_permissions():
    permissions = PermissionSystem()
    old_mode = permissions.mode
    old_rules = list(permissions._rules)
    old_allowlist = list(permissions._pre_authorized_list)
    old_decisions = permissions.get_decision_log(limit=200)
    permissions._pre_authorized_list = []
    permissions._decision_log = []
    return permissions, old_mode, old_rules, old_allowlist, old_decisions


def test_auto_permission_blocks_risky_terminal_command():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.AUTO_PILOT)

        result = permissions.check("terminal", "rm -rf important")

        assert result.granted is False
        # Blocked either by the Safety command policy (destructive_commands) or
        # the legacy Auto-Pilot risk scorer.
        assert ("Auto-Pilot blocked" in result.reason) or ("blocked by policy" in result.reason.lower())
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_auto_permission_blocks_powershell_recursive_delete():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.AUTO_PILOT)

        result = permissions.check("terminal", "Remove-Item -Recurse important")

        assert result.granted is False
        assert "recursive deletion" in result.reason
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_all_permission_allows_risky_terminal_command():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.BYPASS)

        result = permissions.check("terminal", "rm -rf important")

        assert result.granted is True
        assert "Bypass mode active" in result.reason
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_allowlist_permission_matches_exact_saved_command():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.PRE_AUTHORIZED)
        permissions.pre_authorize("npm test")

        allowed = permissions.check("terminal", "npm test")
        denied = permissions.check("terminal", "npm run build")

        assert allowed.granted is True
        assert denied.granted is False
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_explicit_deny_rule_wins_over_later_allow_rule():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.DEFAULT)
        permissions.add_rule("terminal", "*", False)
        permissions.add_rule("terminal", "npm *", True)

        result = permissions.check("terminal", "npm test")

        assert result.granted is False
        assert "Denied by rule" in result.reason
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_explicit_deny_rule_applies_in_auto_pilot():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.AUTO_PILOT)
        permissions.add_rule("terminal", "npm test", False)

        result = permissions.check("terminal", "npm test")

        assert result.granted is False
        assert "Denied by rule" in result.reason
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_bypass_mode_remains_explicit_override_for_rules():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.BYPASS)
        permissions.add_rule("terminal", "*", False)

        result = permissions.check("terminal", "rm -rf important")

        assert result.granted is True
        assert "Bypass mode active" in result.reason
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions


def test_permission_decision_log_records_scrubbed_reason_and_rule():
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _with_clean_permissions()
    try:
        permissions.set_mode(PermissionMode.DEFAULT)
        permissions.add_rule("terminal", "*", False)

        result = permissions.check(
            "terminal",
            "curl https://example.test?token=super-secret sk-proj-abc123456789",
            context={"run_id": "run-1", "surface": "test"},
        )

        decisions = permissions.get_decision_log()
        assert result.decision == decisions[-1]
        assert decisions[-1]["granted"] is False
        assert decisions[-1]["source"] == "rule:deny"
        assert decisions[-1]["matched_rule"] == {"tool": "terminal", "action": "*", "granted": False}
        assert decisions[-1]["run_id"] == "run-1"
        assert decisions[-1]["surface"] == "test"
        assert "super-secret" not in decisions[-1]["action_preview"]
        assert "sk-proj-abc123456789" not in decisions[-1]["action_preview"]
        assert "[REDACTED]" in decisions[-1]["action_preview"]
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions
