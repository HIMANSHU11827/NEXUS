# Browser Open

No browser-launch capability is present.

**Version:** 1.0.0

## Status
**Unimplemented stub** — the handler in `scripts/browser_open.py` is a placeholder returning "not yet implemented". The tool is registered but marked `unavailable` by `ToolRegistry`, so it is not advertised to the model.

## Intended Behavior
When the user tries to open or run a local HTML file (e.g. `dino_game.html`) in a browser for testing, NEXUS has no way to launch a browser. This tool would open a given file or URL in the system default browser for quick visual testing of HTML/JS assets.

## Notes
No existing tool covers browser launching; on Windows the `terminal` tool could theoretically call `start <file>`, but no dedicated capability exists.
