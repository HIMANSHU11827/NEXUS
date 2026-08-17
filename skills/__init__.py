"""Backward-compat shim for the old top-level ``skills`` package.

The canonical skills system now lives under ``extensions.skills.built_in``
(architecture spec section 16). To keep a single identity for every class
across both import paths, this shim aliases every ``extensions.skills.built_in.*``
module to ``skills.*`` using the *same* module object, then re-exposes the
public names. Legacy ``import skills`` / ``from skills import X`` /
``from skills.<pkg> import Y`` keep working.
"""

import sys

import extensions.skills.built_in as _built_in

_PREFIX = "extensions.skills.built_in."
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "skills." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

sys.modules[__name__] = _built_in

for _name, _val in list(_built_in.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
