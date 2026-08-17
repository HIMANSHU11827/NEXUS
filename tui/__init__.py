"""Backward-compat shim for the old top-level ``tui`` package.

The canonical implementation now lives under ``apps.tui`` (architecture spec).
This shim aliases every ``apps.tui.*`` module to ``tui.*`` using the same
module object (single identity across import paths) and re-exposes public
names. Legacy ``import tui`` / ``from tui import X`` keep working.
"""

import sys

import apps.tui as _canon

_PREFIX = "apps.tui."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "tui." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

sys.modules[__name__] = _canon

for _name, _val in list(_canon.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
