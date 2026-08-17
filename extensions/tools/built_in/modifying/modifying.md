# Modifying Tool
**Version:** 2.0.0

Edit text in an existing file. Replaces the first occurrence of `old_string` with `new_string`.

## Parameters
- `path` (string, required): File path to edit
- `old_string` (string, required): Text to replace
- `new_string` (string, optional, default=""): Replacement text
- `replace_all` (bool, optional, default=false): Replace every occurrence; multiple matches without it raise an error asking for more context or `replace_all: true`
