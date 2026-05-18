# Legacy Tool Quarantine

These folders are retained only for reference while the project migrates to the
hardened `tools/nexus_tools` registry:

- `terminal`
- `file_ops`
- `tester`
- `git`
- `docker`
- `elite`

Active runtime code must not import these folders. Compatibility callers should
use `core.tool_adapters`, which routes through the risk-scored file, shell,
process, and audit tools.
