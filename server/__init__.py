"""Backward-compat shim for the old top-level ``server`` package.

The canonical implementation now lives under ``apps.api`` (architecture spec).
This shim aliases every ``apps.api.*`` module to ``server.*`` using the same
module object (single identity across import paths) and re-exposes public
names. Legacy ``import server`` / ``from server import X`` keep working.
"""

import sys

import apps.api as _canon

_PREFIX = "apps.api."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "server." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

sys.modules[__name__] = _canon

for _name, _val in list(_canon.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
