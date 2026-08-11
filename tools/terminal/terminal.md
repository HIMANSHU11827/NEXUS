# Terminal Tool
**Version:** 2.0.0

Run shell commands with timeout control. This is also the tool for local build, preview,
and development-server commands such as `npm run dev` or `python -m http.server`.

## Parameters
- `command` (string, required): Command to execute
- `timeout` (int, optional, default=30): Timeout in seconds
- `workdir` (string, optional, default=`.`): Workspace-relative working directory
- `shell` (string, optional, default=`cmd` on Windows): `cmd`, explicit
  `powershell`, `bash`, or `wsl` when installed.

On Windows, `cmd` does not support Unix commands such as `head`/`tail`, and
uses `&`/`&&` rather than `;` for command chaining. Use `shell="powershell"`
when PowerShell syntax is required; NEXUS rejects incompatible syntax with a
repair hint instead of letting it reach the wrong command parser. Bash and WSL
are never silently downgraded to `cmd`.

Long-running preview servers remain subject to the command timeout and are stopped when
the tool call ends. Do not claim a preview is running after a timed-out or stopped command.
