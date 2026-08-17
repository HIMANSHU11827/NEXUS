# Reading Tool

Read file contents from the filesystem.

For large files, `start_line` and `end_line` can be supplied as an inclusive,
1-based range so an agent can inspect targeted sections without streaming the
whole file through the run event channel. Large unscoped reads are archived
with a bounded preview by the tool execution policy.

**Version:** 2.0.0
