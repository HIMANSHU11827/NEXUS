# Test Runner Tool
**Version:** 2.0.0

Runs targeted test commands with project-aware framework auto-detection. It inspects
Python test configuration and `package.json` scripts before selecting a command.

## Parameters
- `command` (string, optional): Explicit test command
- `target` (string, optional): Test file, folder, or expression
- `framework` (string, optional): `auto|pytest|npm|vitest|jest`
- `timeout` (int, optional, default=120): Timeout in seconds

The result includes the exact command, working directory, timeout, and exit code so the
agent and UI can distinguish a passing test, a failing test, and a timed-out test.
