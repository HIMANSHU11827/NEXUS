# Terminal Tool

Execute shell commands through `SovereignSandbox.stream_execute` — 3-tier sandbox (NO_SANDBOX/NORMAL/DOCKER) with risk scoring, blocking, and timeout handling.

**Version:** 2.0.0

## Behavior
- Commands run inside the SovereignSandbox pipeline, not a bare subprocess
- Risk-scored before execution; blocked commands surface `[SANDBOX_BLOCK]`
- Timeouts surface `[SANDBOX_TIMEOUT]`; result exposes the exit code and resolved workdir
- On Windows the default shell is `cmd`; use the explicit `shell="powershell"`
  parameter when PowerShell syntax is needed. Unsupported unquoted `;` and
  Unix-only `head`/`tail` commands produce a structured repair hint. Explicit
  `bash` and `wsl` selections are honored when installed and otherwise fail
  clearly rather than falling back to `cmd`.
- Long-running preview/development servers may use `background=true` (and
  common server commands are auto-detected); detached launches return promptly
  and are not killed when the observing terminal stream is closed.
