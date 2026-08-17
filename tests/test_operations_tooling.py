"""Tests for the NEXUS AI setup & operations tooling.

Covers the `setup.ps1` multi-action installer/repairer and the
`nexus-*.cmd`/`nexus-*.ps1` wrappers that were added so a developer can
setup, install, update, reinstall, restart, configure, doctor, status, and
check the project from one command.

These are structural/contract tests: they assert the tooling exists, parses,
and advertises the expected actions without executing any installs.
"""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(ROOT, *parts)


EXPECTED_ACTIONS = [
    "setup",
    "install",
    "update",
    "reinstall",
    "fresh",
    "restart",
    "configure",
    "doctor",
    "status",
    "check",
]


EXPECTED_FUNCTIONS = [
    "Install-Deps",
    "Update-Deps",
    "Install-NodeDeps",
    "Seed-Env",
    "Check-Backend",
    "Show-Status",
    "Show-Doctor",
    "Restart-Server",
    "Show-Go-Inventory",
    "Do-Check",
]


EXPECTED_WRAPPERS = [
    "nexus-setup.cmd",
    "nexus-doctor.cmd",
    "nexus-doctor.ps1",
    "nexus-status.cmd",
    "nexus-status.ps1",
]


@pytest.mark.parametrize("action", EXPECTED_ACTIONS)
def test_setup_ps1_actions_in_help(action):
    """setup.ps1 -Help must advertise every supported action."""
    path = _path("setup.ps1")
    assert os.path.isfile(path), "setup.ps1 is missing"
    text = open(path, encoding="utf-8").read()
    # help text contains the action name
    assert ("  " + action) in text or action in text


@pytest.mark.parametrize("action", EXPECTED_ACTIONS)
def test_setup_ps1_actions_validated(action):
    """Every action must be accepted by the ValidateSet guard."""
    path = _path("setup.ps1")
    text = open(path, encoding="utf-8").read()
    match = re.search(r"ValidateSet\((.*?)\)", text, re.DOTALL)
    assert match, "ValidateSet not found"
    assert action in match.group(1)


@pytest.mark.parametrize("func", EXPECTED_FUNCTIONS)
def test_setup_ps1_defines_function(func):
    """setup.ps1 must define every required helper function."""
    path = _path("setup.ps1")
    text = open(path, encoding="utf-8").read()
    assert ("function %s" % func) in text


@pytest.mark.parametrize("wrapper", EXPECTED_WRAPPERS)
def test_wrapper_files_exist(wrapper):
    """Each operator-facing wrapper file must exist."""
    assert os.path.isfile(_path(wrapper)), "%s is missing" % wrapper


def _powershell_parse_errors(path):
    """Return PowerShell AST parse errors for the given .ps1 file."""
    script = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e)|Out-Null;"
        "if($e -and $e.Count){$e|ForEach-Object{Write-Host(('ERR L{0}: {1}' -f "
        "$_.Extent.StartLineNumber,$_.Message))}}else{Write-Host 'OK'}" % path
    )
    # write the parse probe to a temp file to avoid command-line quoting issues
    probe = os.path.join(os.path.dirname(path), "_ps_parse_probe.ps1")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(script)
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", probe],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return (res.returncode, res.stdout)
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def test_setup_ps1_parses_cleanly():
    """setup.ps1 must be valid PowerShell (no AST parse errors)."""
    if not shutil.which("powershell"):
        pytest.skip("powershell not available on this host")
    code, out = _powershell_parse_errors(_path("setup.ps1"))
    assert "OK" in out, "setup.ps1 has parse errors:\n" + out


def test_nexus_doctor_and_status_reference_their_scripts():
    """The .cmd wrappers must delegate to the .ps1 helpers (Bypass)."""
    for wrapper in ("nexus-doctor.cmd", "nexus-status.cmd"):
        text = open(_path(wrapper), encoding="utf-8").read()
        assert "powershell" in text.lower(), "%s must call powershell" % wrapper
        assert wrapper.replace(".cmd", ".ps1") in text


def test_setup_ps1_flags_defined():
    """setup.ps1 must define the documented flag switches."""
    path = _path("setup.ps1")
    text = open(path, encoding="utf-8").read()
    for flag in ("SkipNode", "SkipEnv", "SkipBackend", "Quiet", "Force", "Help"):
        assert ("[switch]$%s" % flag) in text, "missing flag %s" % flag


def test_setup_ps1_has_default_action():
    """setup.ps1 must default to the 'setup' action."""
    path = _path("setup.ps1")
    text = open(path, encoding="utf-8").read()
    assert "$Action = \"setup\"" in text