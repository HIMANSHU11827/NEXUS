# Core Test Loop

Tests for `NexusLoop` evolution hooks and core types (`orchestrators.loop`), covering:

- **TestNexusLoopInstantiation**: Verifies `NexusLoop` creation, hook registration, and evolution method presence.
- **TestToolCall**: Tests `ToolCall` creation and `to_dict` serialization.
- **TestHookRegistry**: Tests `HookRegistry` hook registration and async trigger execution.
- **TestAgentExecutionContract**: Tests public work-event chunks, command failure events, tool-call parsing, removed `file_ops` syntax compatibility, and verified fallback summaries.
