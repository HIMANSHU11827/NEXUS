# Core Test Loop

Tests for `NexusLoop` evolution hooks and core types (`orchestrators.loop`), covering:

- **TestNexusLoopInstantiation**: Verifies `NexusLoop` creation, hook registration, and evolution method presence.
- **TestSCAState**: Ensures all 7 `SCAState` enum values are correctly defined.
- **TestToolCall**: Tests `ToolCall` creation and `to_dict` serialization.
- **TestHookRegistry**: Tests `HookRegistry` hook registration and async trigger execution.
