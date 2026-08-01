"""NEXUS durable task queue package.

NOTE: this package intentionally shadows the Python stdlib ``queue`` module when
the repo root is on ``sys.path`` (e.g. running from the project directory). To
keep other libraries (urllib3 -> queue.LifoQueue) working, any name we do NOT
define here is forwarded to the real stdlib ``queue`` module.
"""

import importlib
import importlib.util
import os
import sys

__all__ = ["TaskQueue", "QueueDriver", "enqueue_task", "start_queue_driver"]


def _load_stdlib_queue():
    """Import the genuine stdlib ``queue`` module without resolving to this package.

    We import it by its absolute filesystem path (Lib/queue.py) so there is zero
    chance of re-entering this package's __init__ (which would recurse).
    """
    # Locate the stdlib directory of the running interpreter.
    base = os.path.dirname(os.__file__)          # .../python3.x
    candidate = os.path.join(base, "queue.py")
    if not os.path.isfile(candidate):
        # PyPy / unusual layouts: search a bit
        for root in (base, os.path.dirname(base)):
            for name in ("queue.py", "queue/__init__.py"):
                c = os.path.join(root, name)
                if os.path.isfile(c):
                    candidate = c
                    break
    spec = importlib.util.spec_from_file_location("_stdlib_queue_shim", candidate)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_stdlib_queue = _load_stdlib_queue()


def __getattr__(name):  # lazy re-exports, avoids import cycles / heavy imports
    if name == "TaskQueue":
        from .store import TaskQueue
        return TaskQueue
    if name in ("QueueDriver", "enqueue_task", "start_queue_driver"):
        from . import driver
        return getattr(driver, name)
    # Forward everything else (LifoQueue, Queue, Empty, ...) to stdlib queue.
    # Guard: if stdlib lacks it too, raise AttributeError (no recursion).
    return getattr(_stdlib_queue, name)
