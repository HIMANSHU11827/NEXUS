"""Minimal greeting response handler.

Design goal: keep it tiny, readable, and easy to extend
(greetings list, responses, or time-aware behavior).
"""

from __future__ import annotations

import re
from datetime import datetime

# --- 1. Configurable matching data -------------------------------
GREETINGS: tuple[str, ...] = ("hello", "hi", "hey", "howdy", "good morning", "good afternoon", "good evening")

DEFAULT_RESPONSES: tuple[str, ...] = (
    "Hello!",
    "Hi there!",
    "Hey!",
    "How can I help you today?",
)

# Map time-of-day to a list of appropriate responses.
TIME_RESPONSES: dict[str, tuple[str, ...]] = {
    "morning": ("Good morning!", "Morning!", "Hi, good morning."),
    "afternoon": ("Good afternoon!", "Hello!", "Hi there!"),
    "evening": ("Good evening!", "Hello!", "Hi!"),
}

# --- 2. Normalization --------------------------------------------
_PUNCT_RE = re.compile(r"[^\w\s]+")


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation so 'Hello!!' == 'hello'."""
    return _PUNCT_RE.sub("", text.strip().lower())


# --- 3. Matching -------------------------------------------------
def is_greeting(text: str) -> bool:
    """Return True if the input looks like a greeting."""
    normalized = _normalize(text)
    if not normalized:
        return False
    # Match either the whole string or the first word(s).
    first_word = normalized.split()[0]
    return normalized in GREETINGS or first_word in GREETINGS


# --- 4. Response selection ----------------------------------------
def _time_of_day(now: datetime | None = None) -> str:
    now = now or datetime.now()
    hour = now.hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def handle(text: str, now: datetime | None = None, seed: int = 0) -> str | None:
    """Return a greeting response, or None if input isn't a greeting.

    Args:
        text: Raw user input.
        now: Optional datetime for time-aware responses (testable).
        seed: Simple deterministic index for picking from a response list.
    """
    if not is_greeting(text):
        return None

    tod = _time_of_day(now)
    responses = TIME_RESPONSES[tod]
    return responses[seed % len(responses)]


# --- 5. Convenience wrapper ----------------------------------------
def respond(text: str) -> str:
    """High-level helper: returns a response string, or a fallback for non-greetings."""
    reply = handle(text)
    if reply is None:
        return "Sorry, I didn't catch that. Try saying 'hello'."
    return reply


if __name__ == "__main__":
    import sys
    for sample in sys.argv[1:] or ["hello"]:
        print(f"{sample!r} -> {respond(sample)!r}")
