"""NEXUS compatibility shim for legacy imports."""

import math
import json
from typing import Any, Iterator


def import_requests():
    try:
        import requests
        return requests
    except ImportError:
        return None


def s(text: Any, length: int = 60) -> str:
    """Shorten/safe string representation."""
    result = str(text)
    if len(result) > length:
        return result[:length] + "..."
    return result


def safe_round(value: float, decimals: int = 2) -> float:
    """Safely round a value, handling None and non-numeric."""
    if value is None:
        return 0.0
    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return 0.0


def itail(iterable: Any, n: int = 5) -> Iterator[Any]:
    """Iterate over the last n items of an iterable."""
    if hasattr(iterable, "__len__"):
        return iter(list(iterable)[-n:])
    collected = list(iterable)
    return iter(collected[-n:])


def safe_del(obj: Any, key: str) -> None:
    """Safely delete a key from a dict-like object."""
    try:
        del obj[key]
    except (KeyError, TypeError, AttributeError):
        pass


def sx(obj: Any) -> str:
    """Safe string representation for any object."""
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError):
        return str(obj)
