"""Tests for the setup wizard's unified, system-aware gateway setup.

Proves the wizard now configures SMS (Twilio) — which needs three secrets
and optional deps — not just single-token platforms, and that missing
gateway dependencies are detected and offered an install.
"""

import importlib.util
import os
from unittest import mock as _m

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WIZARD_PATH = os.path.join(_ROOT, "apps", "tui", "setup_wizard.py")


def _load_wizard():
    spec = importlib.util.spec_from_file_location("setup_wizard_gw_test", _WIZARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wizard = _load_wizard()


def test_sms_gateway_is_defined_with_three_secrets():
    assert "sms" in wizard.GATEWAY_DEFS
    sms = wizard.GATEWAY_DEFS["sms"]
    # The real SMS adapter (gateways/platforms/sms.py) requires these three.
    assert sms["env_keys"] == [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
    ]


def test_single_token_platforms_unchanged():
    for name in ("telegram", "discord", "slack", "whatsapp"):
        assert "env_key" in wizard.GATEWAY_DEFS[name]
    assert "sms" not in wizard.GATEWAY_DEFS["telegram"]


def test_ensure_gateway_deps_skips_when_present():
    calls = []

    def fake_import(name, *a, **k):
        # Pretend every dep is importable.
        class _M:
            pass

        return _M()

    with _m.patch.object(wizard.importlib, "import_module", fake_import):
        with _m.patch.object(wizard, "status_ok") as ok:
            wizard._ensure_gateway_deps(["twilio", "flask"])
    ok.assert_called()


def test_ensure_gateway_deps_offers_install_when_missing():
    # First import fails (missing), second (after "install") succeeds.
    state = {"imports": 0}

    def fake_import(name, *a, **k):
        state["imports"] += 1
        if state["imports"] <= 1:
            raise ImportError("missing")
        class _M:
            pass
        return _M()

    with _m.patch.object(wizard.importlib, "import_module", fake_import):
        with _m.patch.object(wizard, "Confirm") as confirm:
            confirm.ask.return_value = True
            with _m.patch.object(wizard.subprocess, "run") as run:
                with _m.patch.object(wizard, "status_ok") as ok:
                    wizard._ensure_gateway_deps(["twilio"])
    run.assert_called()
    ok.assert_called()
