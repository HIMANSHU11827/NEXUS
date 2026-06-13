# SOP: CODING_STANDARD_v1
# TRIGGER: Code Creation or Refactoring

## 1. SIMULATE
- Before writing a single line, use 'bash' to check for existing files.
- Draft the architecture in your internal monologue.

## 2. ISOLATE
- Use 'bash' with 'sandbox=True' to test new library versions or complex logic fragments.

## 3. IMPLEMENT
- Use 'file_edit' for surgical changes.
- Ensure all docstrings follow the NEXUS Sovereign style (Upper-case headers).

## 4. VERIFY
- Run 'pytest' or 'test_agi.py' after every major change.
- Perform a final 'grep' to ensure no sensitive placeholders remain.
