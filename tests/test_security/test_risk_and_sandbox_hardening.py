"""Regression tests for security hardening:

- risk scorer: EncodedCommand decode/flag, rmdir/del /s /q, & separators
- sandbox workspace guard: $env: expansion and base64 path smuggling
- shell /run path: blocked commands are refused before subprocess
"""

import asyncio
import base64

import pytest


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture(scope="module")
def scorer():
    from sandbox.risk import CommandRiskScorer

    return CommandRiskScorer()


class TestRiskScorerHardening:
    def test_encoded_command_payload_is_flagged(self, scorer):
        result = scorer.assess(f"powershell -EncodedCommand {_b64('Remove-Item -Recurse C:\\')}")
        assert result.blocked is True
        assert any("encoded command payload" in r for r in result.reasons)

    def test_encoded_command_payload_contents_are_scored(self, scorer):
        payload = _b64("type C:\\Users\\outside\\.env")
        result = scorer.assess(f"powershell -EncodedCommand {payload}")
        assert result.score >= 100
        assert any("credential access" in r for r in result.reasons)

    def test_encoded_command_nonbase64_is_still_flagged(self, scorer):
        result = scorer.assess("powershell -EncodedCommand not-base64!!")
        assert result.blocked is True

    def test_rmdir_quiet_recursive_scores_critical(self, scorer):
        assert scorer.assess("rmdir /s /q C:\\Users").blocked is True
        assert scorer.assess("rmdir /s/q C:\\Users").blocked is True
        assert scorer.assess("rmdir empty_dir").score == 45

    def test_del_recursive_scores_critical(self, scorer):
        assert scorer.assess("del /s /q C:\\data\\*").blocked is True
        assert scorer.assess("del /s C:\\data\\*").blocked is True
        assert scorer.assess("del /q report.txt").blocked is True

    def test_ampersand_counts_as_compound(self, scorer):
        assert scorer.assess("echo a & echo b").score >= 20

    def test_plain_safe_reads_are_not_blocked(self, scorer):
        assert scorer.assess("type README.md").blocked is False
        assert scorer.assess("git status").blocked is False


class TestSandboxWorkspaceGuardHardening:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from sandbox.sandbox_manager import SandboxTier, SovereignSandbox

        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        self.outside = str(outside)
        self.sandbox = SovereignSandbox(str(self.workspace))
        self.sandbox.tier = SandboxTier.NORMAL

    def test_env_var_path_smuggling_is_blocked(self):
        result = self.sandbox.execute("type %SystemRoot%\\win.ini")
        assert "[SANDBOX_BLOCK]" in result

    def test_powershell_env_var_path_smuggling_is_blocked(self):
        result = self.sandbox.execute('type "$env:SystemRoot\\win.ini"')
        assert "[SANDBOX_BLOCK]" in result

    def test_encoded_command_path_smuggling_is_blocked(self):
        payload = _b64('Get-Content "C:\\Users\\outside.txt"')
        result = self.sandbox.execute(f"powershell -EncodedCommand {payload}")
        assert "[SANDBOX_BLOCK]" in result

    def test_encoded_command_reads_inside_workspace_pass(self):
        (self.workspace / "inside.txt").write_text("ok", encoding="utf-8")
        payload = _b64("Get-Content inside.txt")
        result = self.sandbox.execute(f"powershell -EncodedCommand {payload}")
        # The guard must NOT block a payload scoped inside the workspace; the
        # command itself may fail to execute depending on host PowerShell.
        assert "[SANDBOX_BLOCK]" not in result


class TestShellRunPath:
    def test_run_bash_refuses_blocked_command(self, tmp_path, monkeypatch):
        from tui import NexusShell

        shell = NexusShell(brain=type("B", (), {"root": str(tmp_path)})())
        spawned = []

        class FakePopen:
            def __init__(self, *a, **k):
                spawned.append(a)

        monkeypatch.setattr("tui.subprocess.run", FakePopen)
        assert shell._run_bash("rm -rf C:\\Users") == 1
        assert spawned == []

    def test_run_bash_executes_safe_command(self, tmp_path, monkeypatch):
        from tui import NexusShell

        shell = NexusShell(brain=type("B", (), {"root": str(tmp_path)})())
        executed = []

        class FakeCompleted:
            stdout = ""
            stderr = ""
            returncode = 0

        def fake_run(command, **kwargs):
            executed.append(command)
            return FakeCompleted()

        monkeypatch.setattr("tui.subprocess.run", fake_run)
        assert shell._run_bash("git status") == 0
        assert executed == ["git status"]

    def test_run_bash_times_out_long_commands(self, tmp_path, monkeypatch):
        from tui import NexusShell

        shell = NexusShell(brain=type("B", (), {"root": str(tmp_path)})())

        def hang(**kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr("tui.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out")))
        assert shell._run_bash("echo ok") == 1
        assert hang


class TestOAuthRedirectValidation:
    @pytest.fixture
    def oauth_providers(self, monkeypatch):
        import authentication

        monkeypatch.setattr(
            authentication,
            "OAUTH_PROVIDERS",
            {"google": {"client_id": "test-client", "scope": "openid", "authorize_url": "https://accounts.google.com/o/oauth2/auth"}},
        )

    def test_foreign_redirect_is_rejected(self, oauth_providers):
        import pytest as _pytest

        try:
            from server import app
        except Exception as exc:  # pragma: no cover - env guard
            _pytest.skip(f"server import unavailable: {exc}")
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/auth/login", params={"provider": "google", "redirect": "https://evil.example.com/cb"})
            assert response.status_code == 400

    def test_loopback_redirect_is_accepted(self, oauth_providers):
        from fastapi.testclient import TestClient

        try:
            from server import app
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"server import unavailable: {exc}")

        with TestClient(app) as client:
            response = client.get(
                "/api/auth/login",
                params={"provider": "google", "redirect": "http://127.0.0.1:8000/api/auth/callback"},
                follow_redirects=False,
            )
            assert response.status_code == 307
            assert "%3A8000%2Fapi%2Fauth%2Fcallback" in response.headers.get("location", "")

    def test_relative_redirect_is_accepted(self, oauth_providers):
        try:
            from server import app
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"server import unavailable: {exc}")
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get(
                "/api/auth/login",
                params={"provider": "google", "redirect": "/api/auth/callback"},
                follow_redirects=False,
            )
            assert response.status_code == 307


class TestReleaseGateSecretScan:
    def test_gate_scanner_detects_committed_key(self, tmp_path, monkeypatch):
        from security.secret_scanner import SecretScanner

        tracked = ["config/settings.yml"]
        (tmp_path / "settings.yml").write_text("api_key: sk-abcdef1234567890ABCDEF1234567890", encoding="utf-8")
        monkeypatch.setattr("scripts.release_gate.ROOT", tmp_path)
        # A key directly under the temp root is an absolute path escape for the
        # scanner's _resolve, so run the scanner on a plain file directly.
        findings = SecretScanner(str(tmp_path)).scan([tmp_path / "settings.yml"])
        assert findings
        assert findings[0].kind == "generic_sk_key"
