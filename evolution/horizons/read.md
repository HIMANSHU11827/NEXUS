# Strategic Horizons

Long-term evolution planning and roadmap management for NEXUS AI.

**Version:** 2.0.0

## Status
Implemented — `scripts/horizons.py` (v0.2.0).

## Components
- `StrategicHorizons`:
  - `DEFAULT_HORIZONS` — horizon definitions: `immediate`, `near_term`, `mid_term`, `long_term` (with status flags)
  - `get_active_horizons()` — only horizons with `status == "active"` (used by `prompts` via `kernel.horizons.get_active_horizons()`)
  - `get_horizons()` / `list_horizons()` — full horizon list
