"""Gateway lifecycle state persistence.

Persists each platform adapter's supervised lifecycle state (state, health,
``last_error``, restart count, ``disabled_until``) to a single JSON file under
``~/.nexus/gateway/state.json`` so a supervised gateway can resume across
restarts without re-hitting a crash-looping platform at boot.

Guarantees:
* atomic writes — data is written to a temp file in the same directory and
  ``os.replace``-d into place, so a crash mid-write never corrupts state,
* never raises — a missing/unreadable file or a failed write degrades to an
  empty snapshot instead of taking the gateway down.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = os.path.join(
    os.path.expanduser("~"), ".nexus", "gateway", "state.json"
)


class GatewayStateStore:
    """Read/write the gateway lifecycle state file."""

    def __init__(self, path: Optional[str] = None):
        self.path = os.path.abspath(path or DEFAULT_STATE_FILE)

    def load(self) -> Dict[str, dict]:
        """Return the persisted per-platform states (empty dict on any failure)."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                platforms = data.get("platforms", {})
                if isinstance(platforms, dict):
                    return platforms
        except Exception:  # degrade softly — no gateway impact from a bad file
            logger.debug("gateway/state.py load: suppressed error", exc_info=True)
        return {}

    def save(self, platform_states: Dict[str, dict]) -> None:
        """Atomically persist ``platform_states``; never raises.

        Layout: ``{"version": 1, "updated_at": <ts>, "platforms": {...}}``.
        """
        try:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "updated_at": time.time(),
                "platforms": platform_states,
            }
            # Atomic write: same-directory temp file + rename.
            fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2)
                os.replace(tmp_path, self.path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:  # pragma: no cover - raced cleanup
                        pass
        except Exception:  # degrade softly — persistence must never crash the loop
            logger.warning("gateway/state.py save: suppressed error", exc_info=True)
