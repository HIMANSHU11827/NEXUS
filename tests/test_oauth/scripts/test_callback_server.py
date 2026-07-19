import pytest

from providers.oauth.callback_server import (
    parse_oauth_authorization_input,
)


class TestParseOAuthAuthorizationInput:
    def test_parses_full_url(self):
        result = parse_oauth_authorization_input(
            "http://localhost:1455/callback?code=abc123&state=xyz789"
        )
        assert result.code == "abc123"
        assert result.state == "xyz789"

    def test_parses_code_hash_state(self):
        result = parse_oauth_authorization_input("authcode#mystate")
        assert result.code == "authcode"
        assert result.state == "mystate"

    def test_parses_raw_query_string(self):
        result = parse_oauth_authorization_input("code=abc&state=def")
        assert result.code == "abc"
        assert result.state == "def"

    def test_parses_just_code(self):
        result = parse_oauth_authorization_input("simplecode")
        assert result.code == "simplecode"
        assert result.state == ""

    def test_raises_on_empty_input(self):
        with pytest.raises(ValueError, match="No input provided"):
            parse_oauth_authorization_input("")

    def test_raises_on_url_missing_code(self):
        with pytest.raises(ValueError, match="Missing 'code' parameter"):
            parse_oauth_authorization_input("http://localhost?state=x")
