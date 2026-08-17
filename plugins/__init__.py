"""Backward-compat shim for the old top-level ``plugins`` package.

The canonical implementation now lives under ``extensions.plugins.built_in`` (architecture spec).
This shim aliases every ``extensions.plugins.built_in.*`` module to ``plugins.*`` using the same
module object (single identity across import paths) and re-exposes public
names. Legacy ``import plugins`` / ``from plugins import X`` keep working.
"""

import sys

import extensions.plugins.built_in as _canon

_PREFIX = "extensions.plugins.built_in."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "plugins." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

sys.modules[__name__] = _canon

for _name, _val in list(_canon.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
