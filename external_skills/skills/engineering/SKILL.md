# DEBUGGER SKILL (GOD-ARCHITECT)

## OBJECTIVE
Perform exhaustive Root Cause Analysis (RCA) and system-wide diagnostic scanning to resolve complex regressions.

## INSTRUCTIONS
1.  **Observability Scan**: Check the `workspace/nexus_ops.log` and `kernel_state_3_1.json` for turn-by-turn history.
2.  **Symbol Cross-Check**: Use `SYMBOL_MAP('<file>')` to verify incorrect object references or method signatures.
3.  **Terminal Triage**: Run verbose diagnostic commands via ```bash``` with `STDOUT` and `STDERR` enabled.
4.  **Test Verification**: Deploy a specific fix and immediately call `RUN_TESTS()` to ensure no regressions occur elsewhere.

## USAGE
```python
SYMBOL_MAP('orchestrators/coordinator.py')
RUN_TESTS('tests/unit/test_router.py')
```
---
# REFACTOR SKILL (GOD-ARCHITECT)

## OBJECTIVE
Upgrade legacy or fragile codebases to use modern NEXUS 3.3 patterns (Recursive, Grounded, Modular).

## INSTRUCTIONS
1.  **D.R.Y. Enforcement**: Identify duplicated tool logic and move it into specialized `tools/` modules.
2.  **Modular Decoupling**: Ensure all components use the `NexusAutoDiscover` system for grounding instead of hardcoded paths.
3.  **Typing and Docstrings**: Apply static typing and high-density docstrings to all refactored classes.
4.  **LSP Validation**: Run `LSP_CHECK()` on all modified files to ensure 100% syntactical correctness.

## USAGE
```python
EDIT_FILE('core/kernel.py', 'old_logic()', 'new_grounded_logic()', replace_all=False)
LSP_CHECK('core/kernel.py')
```
