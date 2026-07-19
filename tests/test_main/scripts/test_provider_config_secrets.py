import re
from pathlib import Path

from security.secret_scanner import SecretScanner


def test_provider_yml_uses_env_placeholders_not_raw_keys():
    text = Path("config/provider.yml").read_text(encoding="utf-8")
    raw_key = re.compile(r"api_key:\s*(?!\$\{)[A-Za-z0-9_-]{20,}")

    assert not raw_key.search(text)
    assert "api_key: ${" in text


def test_secret_scanner_detects_raw_keys_and_ignores_env_placeholders(tmp_path):
    (tmp_path / "unsafe.yml").write_text("api_key: sk-" + "a" * 24, encoding="utf-8")
    (tmp_path / "safe.yml").write_text("api_key: ${DEEPSEEK_API_KEY}", encoding="utf-8")

    findings = SecretScanner(str(tmp_path)).scan()

    assert [finding.path for finding in findings] == ["unsafe.yml"]
