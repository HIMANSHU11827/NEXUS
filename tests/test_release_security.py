import pytest
from pathlib import Path


def test_public_deployment_requires_explicit_safe_configuration(monkeypatch):
    import server

    monkeypatch.setenv("NEXUS_PUBLIC_DEPLOYMENT", "true")
    monkeypatch.setenv("NEXUS_DASHBOARD_TOKEN", "r" * 40)
    monkeypatch.setenv("NEXUS_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("NEXUS_ALLOW_LOCAL_ANON", "false")
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "normal")
    monkeypatch.setenv("NEXUS_CORS_ORIGINS", "https://app.example.com")
    server._validate_public_deployment()

    monkeypatch.setenv("NEXUS_ALLOW_LOCAL_ANON", "true")
    with pytest.raises(RuntimeError, match="NEXUS_ALLOW_LOCAL_ANON"):
        server._validate_public_deployment()

    monkeypatch.setenv("NEXUS_ALLOW_LOCAL_ANON", "false")
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "no_sandbox")
    with pytest.raises(RuntimeError, match="NEXUS_SANDBOX_TIER"):
        server._validate_public_deployment()

    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "normal")
    monkeypatch.setenv("NEXUS_CORS_ORIGINS", "http://dashboard.example.com")
    with pytest.raises(RuntimeError, match="HTTPS production"):
        server._validate_public_deployment()


def test_public_deployment_rejects_missing_credentials_and_local_cors(monkeypatch):
    import server

    monkeypatch.setenv("NEXUS_PUBLIC_DEPLOYMENT", "true")
    monkeypatch.delenv("NEXUS_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setenv("NEXUS_ALLOW_LOCAL_ANON", "false")
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "normal")
    monkeypatch.setenv("NEXUS_CORS_ORIGINS", "http://127.0.0.1:5173")
    with pytest.raises(RuntimeError) as error:
        server._validate_public_deployment()
    message = str(error.value)
    assert "NEXUS_DASHBOARD_TOKEN" in message
    assert "NEXUS_CORS_ORIGINS" in message


def test_server_rate_limit_is_applied_before_route_execution(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    server._RATE_BUCKETS.clear()
    monkeypatch.setattr(server, "_RATE_LIMIT", 1)
    monkeypatch.setattr(server, "_RATE_WINDOW_SECONDS", 60.0)
    with TestClient(server.app) as client:
        assert client.get("/api/version").status_code == 200
        assert client.get("/api/version").status_code == 429
    server._RATE_BUCKETS.clear()


def test_command_risk_scorer_blocks_credential_reads():
    from sandbox.risk import CommandRiskScorer

    scorer = CommandRiskScorer()
    assert scorer.assess("type .env").blocked is True
    assert scorer.assess("echo ok && type .env").blocked is True


def test_remote_file_reads_block_sensitive_files(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=do-not-return", encoding="utf-8")
    with pytest.raises(Exception, match="Sensitive files"):
        server.safe_workspace_read_path(str(secret))


def test_compose_has_fail_closed_public_defaults():
    import yaml

    with open(Path(__file__).parents[1] / "deploy" / "docker-compose.yml", encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)
    backend = compose["services"]["nexus"]
    environment = backend["environment"]
    assert "NEXUS_PUBLIC_DEPLOYMENT=true" in environment
    assert "NEXUS_ALLOW_LOCAL_ANON=false" in environment
    assert "NEXUS_EMBED_QUEUE_DRIVER=true" in environment
    assert "NEXUS_QUEUE_WORKERS=1" in environment
    assert "NEXUS_SANDBOX_TIER=normal" in environment
    assert "127.0.0.1:8000:8000" in backend["ports"]
    assert backend["read_only"] is True
    assert compose["services"]["nexus"]["restart"] == "unless-stopped"
    assert compose["services"]["nexus-gui"]["restart"] == "unless-stopped"
    assert isinstance(compose["services"]["nexus-gui"].get("healthcheck"), dict)


def test_workspace_containment_resolves_symlink_escape(tmp_path):
    import server

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    assert server._is_within(str(root), str(link / "secret.txt")) is False


def test_website_import_rejects_private_and_redirected_targets():
    import gui.api as gui_api

    with pytest.raises(Exception, match="Private/internal"):
        gui_api._validate_public_source_url("http://127.0.0.1/internal")
    with pytest.raises(Exception, match="Redirects are not allowed"):
        gui_api._NoRedirectHandler().redirect_request(None, None, 302, "Found", {}, "http://example.com")
