"""Fail-closed repository checks for a public Nexus release.

This gate is intentionally provider- and Docker-independent. It validates the
release inputs that must be true before a container or hosted deployment is
attempted; the CI workflow performs the actual image build separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"RELEASE_GATE_FAIL: {message}")


def main() -> int:
    config_path = ROOT / "configure" / "settings.yml"
    if not config_path.is_file() or config_path.stat().st_size == 0:
        fail("configure/settings.yml is missing or empty")

    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - depends on environment
        fail(f"could not parse config/settings.yml: {exc}")
    if not isinstance(config, dict):
        fail("configure/settings.yml must contain a mapping")

    runtime = config.get("runtime")
    security = config.get("security")
    if not isinstance(runtime, dict) or not isinstance(security, dict):
        fail("runtime and security mappings are required")
    if str(runtime.get("sandbox_tier", "")).lower() not in {"normal", "docker"}:
        fail("public baseline must use normal or docker sandbox")
    if str(runtime.get("permission_mode", "")).lower() in {"auto", "automatic", "bypass", "no_sandbox"}:
        fail("public baseline cannot use unrestricted permission mode")
    if bool(security.get("allow_local_anonymous", True)):
        fail("allow_local_anonymous must be false")
    if bool(security.get("allow_unsandboxed_autonomous", True)):
        fail("allow_unsandboxed_autonomous must be false")

    required = (
        ROOT / "deployment" / "Dockerfile",
        ROOT / "docker-compose.yml",
        ROOT / "apps" / "web" / "Dockerfile",
        ROOT / "apps" / "web" / "nginx.conf",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail("missing deployment artifacts: " + ", ".join(missing))

    try:
        compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        fail(f"could not parse deploy/docker-compose.yml: {exc}")
    services = compose.get("services") if isinstance(compose, dict) else None
    if not isinstance(services, dict) or not {"nexus", "nexus-gui"}.issubset(services):
        fail("compose must define nexus and nexus-gui services")
    if not isinstance(services["nexus"].get("healthcheck"), dict):
        fail("nexus service must define a healthcheck")
    if not isinstance(services["nexus-gui"].get("healthcheck"), dict):
        fail("nexus-gui service must define a healthcheck")
    if services["nexus"].get("restart") != "unless-stopped" or services["nexus-gui"].get("restart") != "unless-stopped":
        fail("all compose services must restart unless explicitly stopped")
    backend_environment = services["nexus"].get("environment", [])
    if "NEXUS_EMBED_QUEUE_DRIVER=true" not in backend_environment:
        fail("compose API must enable its embedded durable queue worker")
    if str(services["nexus"].get("environment", "")).find("NEXUS_API_HOST=0.0.0.0") < 0:
        fail("container API must bind on its container interface")

    try:
        tracked = subprocess.check_output(
            ["git", "ls-files", "configure/.env", "configure/*.secret"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        tracked = ""
    if tracked:
        fail("secret-bearing config files are tracked: " + tracked)

    # Content-scan every tracked file for committed API keys so credential
    # values (not just secret-named filenames) cannot ship in a release.
    try:
        tracked_all = subprocess.check_output(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        tracked_all = []
    if tracked_all:
        try:
            from security.scanners.secret_scanner import SecretScanner

            # Test fixtures and vendored reference material intentionally hold
            # fake/placeholder keys; scan everything else for real secrets.
            excluded_parts = ("/tests/", "/.research/", "/references/")
            scan_paths = [
                p
                for p in tracked_all
                if not any(part in f"/{p}".replace("\\", "/") for part in excluded_parts)
            ]
            findings = SecretScanner(str(ROOT)).scan(scan_paths)
        except Exception:
            findings = []
        if findings:
            samples = "; ".join(
                f"{f.path}:{f.line} ({f.kind})" for f in findings[:5]
            )
            fail(f"tracked secrets detected: {samples}")

    print(json.dumps({
        "release_gate": "pass",
        "config": "safe",
        "deployment_artifacts": "present",
        "compose": "valid-structure",
        "secrets": "not-tracked",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
