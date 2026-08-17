"""Backward-compat shim for the old top-level ``mcp`` package.

The canonical implementation now lives under ``extensions.mcp.core`` (architecture spec).
This shim aliases every ``extensions.mcp.core.*`` module to ``mcp.*`` using the same
module object (single identity across import paths) and re-exposes public
names. Legacy ``import mcp`` / ``from mcp import X`` keep working.
"""

import sys

import extensions.mcp.core as _canon

_PREFIX = "extensions.mcp.core."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "mcp." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

sys.modules[__name__] = _canon

for _name, _val in list(_canon.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
