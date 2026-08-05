def test_empty_sandbox_value_normalizes_to_no_sandbox():
    from server import _normalize_sandbox_tier

    assert _normalize_sandbox_tier("") == "no_sandbox"


def test_explicit_sandbox_choice_remains_available():
    from server import _normalize_sandbox_tier

    assert _normalize_sandbox_tier("normal") == "normal"
    assert _normalize_sandbox_tier("docker") == "docker"
