# Terminal Tool
**Version:** 2.0.0

Run shell commands with timeout control. This is also the tool for local build, preview,
and development-server commands such as `npm run dev` or `python -m http.server`.

## Parameters
- `command` (string, required): Command to execute
- `timeout` (int, optional, default=30): Timeout in seconds
- `workdir` (string, optional, default=`.`): Workspace-relative working directory

Long-running preview servers remain subject to the command timeout and are stopped when
the tool call ends. Do not claim a preview is running after a timed-out or stopped command.
