"""Backward-compatibility shim for the old top-level ``tools`` package.

The canonical tools system now lives under ``extensions.tools.built_in``
(architecture spec section 15). To keep a single identity for every class
(ToolCallResult, ToolRegistry, ...) across both import paths, this shim:

  1. imports ``extensions.tools.built_in`` (populating sys.modules for it and
     all of its submodules under the ``extensions.tools.built_in.*`` keys);
  2. aliases every ``extensions.tools.built_in.<x>`` module to ``tools.<x>``
     using the *same* module object (no second copy, so isinstance holds);
  3. re-exposes the public names for ``from tools import X``.

Legacy ``import tools`` / ``from tools import X`` / ``from tools.<tool> import Y``
all keep working.
"""

import sys

import extensions.tools.built_in as _built_in

_PREFIX = "extensions.tools.built_in."
# Alias every already-imported submodule to the legacy ``tools.*`` key, reusing
# the exact same module object so class identities never diverge.
for _key, _mod in list(sys.modules.items()):
    if _key.startswith(_PREFIX) and _mod is not None:
        _legacy = "tools." + _key[len(_PREFIX):]
        if _legacy not in sys.modules:
            sys.modules[_legacy] = _mod

# Make ``import tools`` resolve to the canonical module object.
sys.modules[__name__] = _built_in

# Re-expose public names for ``from tools import X``.
for _name, _val in list(_built_in.__dict__.items()):
    if not _name.startswith("_"):
        try:
            globals()[_name] = _val
        except Exception:
            pass
