# VERIFY SKILL (GOD-ARCHITECT)

## OBJECTIVE
This skill enforces a recursive "High-Quality Commitment" loop. No task is considered complete until it passes both static and dynamic verification.

## INSTRUCTIONS
1.  **Static Analysis**: Call `LSP_CHECK('<file>')` to ensure zero syntax errors.
2.  **Symbol Tracking**: Call `SYMBOL_MAP('<file>')` to ensure correct object references.
3.  **Dynamic Verification**: Call `RUN_TESTS('tests/')` to ensure logic correctness.
4.  **Refactor Loop**: If tests fail, use the `FAIL_SUMMARY` to identify relevant code chunks via `RAG_QUERY`, fix them with `EDIT_FILE`, and repeat verification.

## USAGE
```python
LSP_CHECK('core/kernel.py')
RUN_TESTS('tests/unit/test_kernel.py')
```
