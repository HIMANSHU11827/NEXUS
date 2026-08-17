"""Regression tests for the ThreadSafeSingleton partial-init race.

Found via a real multi-agent hive run: three sub-agents constructed
``NexusProviderFactory`` concurrently; two of them crashed with
``AttributeError: 'NexusProviderFactory' object has no attribute 'loader'``
because ``ThreadSafeSingleton.__new__`` published the instance before the
first thread's ``__init__`` had assigned ``self.loader``.

The fix (utils/singleton.py) completes initialization under the class lock
before the instance is observable; ``_initialized`` is also published last
in ``NexusProviderFactory`` as defense-in-depth.
"""

import threading
import time

from nexus.common.singleton import ThreadSafeSingleton


def _hammer(ctor, count: int = 8, per_result=None):
    """Construct ``ctor()`` from ``count`` threads concurrently.

    All threads align on a barrier BEFORE constructing, then construct and
    probe immediately — so a thread that received a partially-initialized
    singleton (the old bug) observes missing attributes before the first
    thread's slow ``__init__`` can finish. Returns ``(errors, results)``
    where each result is ``per_result(f)`` for a successfully constructed
    singleton (or None when not provided).
    """
    errors = []
    results = []
    barrier = threading.Barrier(count)

    def worker():
        try:
            barrier.wait()
            instance = ctor()
            results.append(per_result(instance) if per_result else instance)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors, results


def test_base_singleton_publishes_only_after_init():
    class SlowSingleton(ThreadSafeSingleton):
        def __init__(self):
            if getattr(self, "_initialized", False):
                return
            self._initialized = True
            time.sleep(0.02)  # widen the old race window
            self.ready = True

    SlowSingleton._reset_instance()

    errors, results = _hammer(SlowSingleton, per_result=lambda f: getattr(f, "ready", False))

    assert not errors, errors
    assert results and all(results), "some threads observed a partially-initialized singleton"


def test_provider_factory_concurrent_construction_is_fully_initialized(monkeypatch):
    import models.providers.core.factory as factory_mod
    from models.providers.core.factory import NexusProviderFactory

    NexusProviderFactory._reset_instance()

    real_loader = factory_mod.get_loader

    def slow_loader():
        time.sleep(0.05)  # widen the old race window
        return real_loader()

    monkeypatch.setattr(factory_mod, "get_loader", slow_loader)

    def probe(factory):
        return (
            getattr(factory, "loader", None) is not None,
            getattr(factory, "name", None) is not None,
            getattr(factory, "group", None) is not None,
        )

    errors, results = _hammer(NexusProviderFactory, per_result=probe)

    assert not errors, errors
    assert results and all(all(fields) for fields in results), (
        f"some threads saw a partially-initialized factory: {results}"
    )
