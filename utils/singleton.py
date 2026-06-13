"""
NEXUS THREAD-SAFE SINGLETON — Base class and decorator for singleton patterns.
Provides thread-safe singleton implementations for all NEXUS components.
"""

import threading
from typing import Any, Dict, Optional


class ThreadSafeSingleton:
    """
    Thread-safe singleton base class.

    Usage:
        class MyClass(ThreadSafeSingleton):
            def __init__(self, arg1=None):
                # initialization code here
                pass

    The __init__ is only called once, on first instantiation.
    Subsequent calls return the same instance.
    """

    _instances: Dict[type, Any] = {}
    _lock: threading.RLock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                # Double-check locking pattern
                if cls not in cls._instances:
                    instance = super().__new__(cls)
                    instance._singleton_initialized = False
                    cls._instances[cls] = instance
        return cls._instances[cls]

    def _singleton_init(self, *args, **kwargs):
        """
        Override this method instead of __init__ for singleton initialization.
        This is called only once when the singleton is first created.
        """
        pass

    @classmethod
    def _reset_instance(cls):
        """Reset the singleton instance (primarily for testing)."""
        with cls._lock:
            if cls in cls._instances:
                del cls._instances[cls]


def singleton(cls):
    """
    Thread-safe singleton decorator.

    Usage:
        @singleton
        class MyClass:
            def __init__(self, arg1=None):
                pass
    """
    instances = {}
    lock = threading.RLock()

    def get_instance(*args, **kwargs):
        if cls not in instances:
            with lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    # Preserve class metadata
    get_instance.__name__ = cls.__name__
    get_instance.__doc__ = cls.__doc__
    get_instance.__module__ = cls.__module__
    get_instance._wrapped_class = cls
    get_instance._reset = lambda: instances.clear()

    return get_instance
