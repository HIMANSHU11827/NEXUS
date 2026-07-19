import hashlib

from providers.oauth.pkce import base64url_encode, generate_oauth_state, generate_pkce


class TestPKCE:
    def test_generate_pkce_returns_valid_pair(self):
        verifier, challenge = generate_pkce()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 0
        assert len(challenge) > 0

    def test_challenge_is_sha256_of_verifier(self):
        verifier, challenge = generate_pkce()
        expected = base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
        assert challenge == expected

    def test_generate_oauth_state_is_random(self):
        states = {generate_oauth_state() for _ in range(100)}
        # With 32 bytes of entropy, 100 draws should all be unique
        assert len(states) == 100

    def test_pkce_is_deterministic_invariant(self):
        v1, c1 = generate_pkce()
        v2, c2 = generate_pkce()
        assert v1 != v2
        assert c1 != c2
