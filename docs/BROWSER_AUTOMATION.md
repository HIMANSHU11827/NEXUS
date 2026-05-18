# Browser Automation

NEXUS includes a `browser` tool for browser-driven UI checks and web automation.

The tool is honest about runtime capability:

- `browser status` reports whether Playwright is installed.
- `browser fetch` works with the current base dependencies for static HTML checks.
- `browser run_sequence` uses Playwright when optional browser support is installed.

## Install Real Browser Control

```powershell
python -m pip install -e .[browser]
python -m playwright install chromium
```

## Tool Commands

Check runtime:

```python
registry.execute("browser", command="status")
```

Fetch static content:

```python
registry.execute("browser", command="fetch", url="https://example.com")
```

Run browser actions:

```python
registry.execute(
    "browser",
    command="run_sequence",
    url="http://127.0.0.1:5173",
    actions=[
        {"action": "text", "selector": "body"},
        {"action": "screenshot"},
    ],
)
```

Artifacts are written under:

```text
workspace/browser/
```

## Design

Browser automation is kept separate from plain `web_fetch` because rendered UI verification needs a real browser, screenshots, action logs, and repeatable artifacts. This closes one of the main product gaps against stronger coding agents: they can inspect and validate frontend behavior, not only source code.
