import base64
import hashlib
import secrets


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64url_encode(verifier_bytes)
    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64url_encode(challenge_bytes)
    return verifier, challenge


def generate_oauth_state() -> str:
    return base64url_encode(secrets.token_bytes(32))
