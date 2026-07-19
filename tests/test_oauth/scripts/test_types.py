
from providers.oauth.types import OAuthAuthInfo, OAuthCredentials, OAuthPrompt


class TestOAuthCredentials:
    def test_create_credentials(self):
        c = OAuthCredentials(access="abc", refresh="def", expires=99999.0)
        assert c.access == "abc"
        assert c.refresh == "def"
        assert c.expires == 99999.0

    def test_credentials_with_email(self):
        c = OAuthCredentials(access="a", refresh="r", expires=1.0, email="user@x.com")
        assert c.email == "user@x.com"

    def test_credentials_serialization(self):
        c = OAuthCredentials(access="a", refresh="r", expires=1.0)
        d = c.to_dict()
        assert d["access"] == "a"
        restored = OAuthCredentials.from_dict(d)
        assert restored.access == "a"
        assert restored.refresh == "r"


class TestOAuthAuthInfo:
    def test_create(self):
        info = OAuthAuthInfo(url="https://example.com/auth")
        assert info.url == "https://example.com/auth"
        assert info.instructions is None

    def test_with_instructions(self):
        info = OAuthAuthInfo(url="https://x.com", instructions="Open in browser")
        assert info.instructions == "Open in browser"


class TestOAuthPrompt:
    def test_create(self):
        p = OAuthPrompt(message="Enter code:")
        assert p.message == "Enter code:"
        assert p.placeholder is None

    def test_with_placeholder(self):
        p = OAuthPrompt(message="URL?", placeholder="http://localhost")
        assert p.placeholder == "http://localhost"
