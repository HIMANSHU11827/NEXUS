from configure.profiles import create_profile, get_profile_path, switch_profile
from utils.nexus_path import get_profiles_root


def test_switch_profile_uses_stable_profiles_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path / ".nexus"))
    monkeypatch.delenv("NEXUS_BASE_HOME", raising=False)
    monkeypatch.delenv("NEXUS_PROFILE", raising=False)

    create_profile("alpha")
    create_profile("beta")

    switch_profile("alpha")
    first_root = get_profiles_root()
    switch_profile("beta")

    assert get_profiles_root() == first_root
    assert get_profile_path("alpha") == first_root / "alpha"
    assert get_profile_path("beta") == first_root / "beta"
