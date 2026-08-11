"""Checkpoint secret-redaction guard.

The reviewer flagged that checkpoints persist `response` and `memory`
verbatim to plaintext JSON on disk. `orchestrators/v5/checkpoint.py` runs
every serialized string through `_checkpoint_safe` -> `redact_secrets`
(providers.reliability), which strips key-shaped secrets. This test pins
that guarantee for BOTH the in-memory transform and the actual on-disk
file a real `_checkpoint_save` writes, so a leaked checkpoint cannot leak
credentials.

Scope note: `redact_secrets` catches key-shaped secrets -- OpenAI `sk-`
tokens, bearer tokens, and full AWS access-key ids (AKIA + 16 alnum). It
does NOT catch inline `password=val` form; that is a known limitation of
the shared redactor in `providers/reliability.py` and is out of scope for
the checkpoint change.
"""

import json
import os

from orchestrators.v5.core import NexusLoopV5, V5TurnContext
from orchestrators.v5.checkpoint import _checkpoint_safe


def test_checkpoint_safe_redacts_key_shaped_secrets():
    """`_checkpoint_safe` must strip token / AWS-key / bearer secrets."""
    secret = (
        "token sk-1a2b3c4d5e6f7g8h9i0j and bearer xyz789 "
        "plus AKIAIOSFODNN7EXAMPLE access key"
    )
    safe = _checkpoint_safe({"response": secret, "memory": [{"content": secret}]})
    blob = json.dumps(safe)
    assert "sk-1a2b3c4d5e6f7g8h9i0j" not in blob, "raw token leaked"
    assert "AKIAIOSFODNN7EXAMPLE" not in blob, "raw AWS key leaked"
    assert "xyz789" not in blob, "raw bearer leaked"


def test_checkpoint_save_redacts_secrets_on_disk(tmp_path):
    """A real `_checkpoint_save` must write redacted content to disk."""
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-redact")
    loop.runtime.current_turn = V5TurnContext(
        turn_id="turn-redact", session_id="ckpt-redact", user_input="work"
    )
    secret = (
        "token sk-1a2b3c4d5e6f7g8h9i0j and bearer xyz789 "
        "plus AKIAIOSFODNN7EXAMPLE access key"
    )
    loop.runtime.last_result = {"response": secret, "success": True}
    path = loop._checkpoint_save(turn_id="turn-redact", phase="completed")
    assert path and os.path.exists(path), "checkpoint not written"
    raw = open(path, encoding="utf-8").read()
    assert "sk-1a2b3c4d5e6f7g8h9i0j" not in raw, "raw token on disk"
    assert "AKIAIOSFODNN7EXAMPLE" not in raw, "raw AWS key on disk"
