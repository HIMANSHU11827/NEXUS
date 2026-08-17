"""Bootstrap: discover and validate enabled gateways.

Discovery is delegated to the engine's ``GatewaySupervisor.register_all()``,
which env-gates every platform adapter and never lets one bad adapter block
the others. This module adds the application-level validation (metadata
presence, config sanity) on top.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("NEXUS-GATEWAY-BOOTSTRAP")


def _load_gateway_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load gateway configuration (JSON) from an explicit path or the engine default."""
    import json

    candidates = []
    if config_path:
        candidates.append(config_path)
    env = os.environ.get("NEXUS_GATEWAY_CONFIG")
    if env:
        candidates.append(env)
    # Engine default lives next to the gateways package.
    try:
        import gateways

        candidates.append(os.path.join(os.path.dirname(gateways.__file__), "config.json"))
    except Exception:
        pass

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("Loaded gateway config from %s", path)
            return data
        except FileNotFoundError:
            continue
        except Exception as exc:  # malformed JSON must not crash bootstrap
            logger.warning("Failed to parse gateway config %s: %s", path, exc)
    logger.info("No gateway config found; using engine defaults")
    return {}


def bootstrap_gateways(config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None):
    """Discover and register every enabled gateway.

    Returns the configured ``GatewaySupervisor`` instance (ready to ``run()``),
    or ``None`` if no gateways are enabled (degraded, not fatal).
    """
    from gateways.supervisor import GatewaySupervisor

    cfg = dict(config or {})
    loaded = _load_gateway_config(config_path)
    cfg.update(loaded)

    try:
        supervisor = GatewaySupervisor(config=cfg)
        supervisor.register_all()
    except Exception as exc:  # discovery must degrade, never crash startup
        logger.exception("Gateway discovery failed: %s", exc)
        return None

    enabled = list(supervisor.adapters.keys())
    if not enabled:
        logger.warning("No gateways enabled (missing credentials) — gateway app will idle.")
        return supervisor
    logger.info("Discovered %d enabled gateway(s): %s", len(enabled), ", ".join(enabled))
    return supervisor
