import pytest

from providers.reliability import redact_secrets


@pytest.mark.parametrize(
    "secret",
    [
        "github_pat_abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "xoxb-123456789012-abcdef123456",
        "npm_abcdefghijklmnopqrstuvwxyz",
        "pypi-abcdefghijklmnopqrstuvwxyz",
        "sk_" + "live_" + "abcdefghijklmnopqrstuvwxyz",
        "AKIAIOSFODNN7EXAMPLE",
        "token=abcdefghijklmnopqrstuvwxyz1234",
        "password: abcdefghijklmnopqrstuvwxyz1234",
    ],
)
def test_common_secret_shapes_are_redacted(secret):
    output = redact_secrets(f"diagnostic {secret} end")

    assert secret not in output
    assert "***REDACTED***" in output


def test_private_key_block_is_redacted():
    secret = "-----BEGIN PRIVATE KEY-----\nvery-secret-material\n-----END PRIVATE KEY-----"

    output = redact_secrets(f"key={secret}")

    assert "very-secret-material" not in output
    assert "BEGIN PRIVATE KEY" not in output


def test_short_human_text_is_not_over_redacted():
    assert redact_secrets("token=short password=short") == "token=short password=short"
