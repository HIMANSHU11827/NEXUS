"""Side-effect reconciliation adapter for Nexus (P1 reliability gap).

This closes the gap: *"Side-effect reconciliation adapters — duplicate
attempt reconciles existing effect instead of repeating it."* NEXUS already
has :class:`hive.effects.HiveEffectLedger` (a durable idempotency ledger),
but it is only wired inside the Hive engine. This module exposes a small,
provider-agnostic adapter so the 24/7 queue/driver (and any retry path)
can wrap a side-effecting call and guarantee it runs at most once per
*effect key*, even across retries and process restarts.

Design constraints (consistent with the rest of the reliability package):

* Does not invent a new ledger — reuses ``HiveEffectLedger`` so all
  side-effects share one durable source of truth.
* Time-injectable (``clock``) and never raises from the wrapper itself;
  transport errors are recorded on the ledger and surfaced to the caller.
* ``execute_once`` returns a structured :class:`EffectOutcome` so callers
  can branch on ``execute`` vs ``replay`` vs ``uncertain``.
"""

from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from hive.effects import HiveEffectLedger

logger = logging.getLogger("nexus.reliability.side_effect")

# Verdicts returned by the ledger's claim() step.
EXECUTE = "execute"
REPLAY = "replay"
UNCERTAIN = "uncertain"


@dataclass
class EffectOutcome:
    """Result of a guarded side-effect attempt."""

    verdict: str  # EXECUTE | REPLAY | UNCERTAIN
    result: Any = None
    error: Optional[str] = None
    effect_key: str = ""
    replayed: bool = False  # True when the prior result was returned without re-running

    @property
    def ran(self) -> bool:
        """True only when the callable was actually executed this attempt."""
        return self.verdict == EXECUTE

    @property
    def ok(self) -> bool:
        """True only when the effect either ran successfully or was a clean
        replay of a prior successful result. Lets callers assert on a single
        boolean instead of misreading ``UNCERTAIN`` (no result) as success."""
        return (self.verdict in (EXECUTE, REPLAY)) and self.error is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "result": self.result,
            "error": self.error,
            "effect_key": self.effect_key,
            "replayed": self.replayed,
            "ok": self.ok,
        }


def _encode_result(result: Any) -> str:
    """Serialize a side-effect result for durable storage.

    ``HiveEffectLedger`` stores results as ``str(...)``, which would corrupt
    non-string values on replay (``{'a': 1}`` -> ``"{'a': 1}"``,
    ``None`` -> ``"None"``). We JSON-encode so the original type is
    faithfully restored on replay.
    """
    import json

    if result is None:
        return json.dumps(None)
    if isinstance(result, str):
        return json.dumps(result)
    try:
        return json.dumps(result)
    except (TypeError, ValueError):
        # Non-serializable (e.g. an object): fall back to repr so a replay
        # still carries *something* rather than crashing the caller.
        return repr(result)


def _decode_result(payload: str) -> Any:
    """Inverse of :func:`_encode_result`, with a raw-string fallback.

    If the stored payload is not valid JSON (legacy string stored by another
    code path, or a repr fallback), return it verbatim so callers that expect
    a string are not broken.
    """
    import json

    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return payload


class SideEffectGuard:
    """Makes a side-effecting call idempotent under a caller-supplied key.

    The ``effect_key`` is typically derived from the durable task identity
    (e.g. a queue ``idempotency_key``) so that a retry of the same logical
    work reconciles the previously-recorded effect instead of repeating it.
    """

    def __init__(
        self,
        root: str,
        *,
        db_path: Optional[str] = None,
        lease_seconds: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._ledger = HiveEffectLedger(
            root, db_path=db_path, lease_seconds=lease_seconds
        )
        self._clock = clock or time.time
        self.healthy = True  # False if the underlying ledger failed to init

    # -- key helpers ------------------------------------------------------

    @staticmethod
    def make_key(
        agent_id: str,
        task: str,
        step: int,
        tool: str,
        params: Dict[str, Any],
    ) -> str:
        """Stable effect key (mirrors ``HiveEffectLedger.key``)."""
        return HiveEffectLedger.key(agent_id, task, step, tool, params)

    # -- core API --------------------------------------------------------

    def claim_only(self, effect_key: str, *, agent_id: str, tool: str) -> Tuple[str, str]:
        """Claim the effect lease WITHOUT executing the callable.

        Returns ``(EXECUTE|REPLAY|UNCERTAIN, payload_or_message)`` — the same
        verdicts as the underlying ledger's ``claim``. Use this for
        long-running side-effects: call ``claim_only`` to take the lease, run
        the work, then ``complete(effect_key, result)`` / ``fail(effect_key, err)``.
        A concurrent or retried claim while the lease is held returns
        ``UNCERTAIN``, preventing duplicate execution.
        """
        verdict, payload = self._ledger.claim(effect_key, agent_id, tool)
        if verdict == REPLAY:
            # Decode the stored result so the caller sees the real type.
            return REPLAY, _decode_result(payload)
        return verdict, payload

    def execute_once(
        self,
        effect_key: str,
        *,
        agent_id: str,
        tool: str,
        call: Callable[[], Any],
        on_replay: Optional[Callable[[Any], None]] = None,
    ) -> EffectOutcome:
        """Run ``call`` at most once per ``effect_key``.

        * If the effect already ``succeeded``, the prior result is replayed
          (``verdict=REPLAY``) and ``call`` is NOT executed.
        * If the effect is in-flight and still leased, the attempt is refused
          (``verdict=UNCERTAIN``) to avoid concurrent double execution.
        * Otherwise ``call`` runs; its success/failure is persisted on the
          ledger so a subsequent retry reconciles rather than repeats.

        Never raises: transport failures from ``call`` are captured into
        ``EffectOutcome.error`` and recorded on the ledger as ``failed``.
        """
        verdict, payload = self._ledger.claim(effect_key, agent_id, tool)
        if verdict == REPLAY:
            result = _decode_result(payload)
            logger.info("side-effect %s replayed (already succeeded)", effect_key)
            if on_replay is not None:
                try:
                    on_replay(result)
                except Exception as exc:  # never break the replay path
                    logger.warning("on_replay hook failed: %s", exc)
            return EffectOutcome(
                verdict=REPLAY,
                result=result,
                effect_key=effect_key,
                replayed=True,
            )
        if verdict == UNCERTAIN:
            logger.warning(
                "side-effect %s refused: %s", effect_key, payload
            )
            return EffectOutcome(
                verdict=UNCERTAIN,
                error=payload,
                effect_key=effect_key,
            )

        # verdict == EXECUTE: run the callable and record the outcome.
        try:
            result = call()
        except Exception as exc:
            self._ledger.fail(effect_key, str(exc))
            logger.warning("side-effect %s failed: %s", effect_key, exc)
            return EffectOutcome(
                verdict=EXECUTE,
                error=str(exc),
                effect_key=effect_key,
            )
        # JSON-encode so a replay restores the original type (dict/None/etc).
        self._ledger.complete(effect_key, _encode_result(result))
        return EffectOutcome(
            verdict=EXECUTE, result=result, effect_key=effect_key
        )

    def as_decorator(
        self,
        agent_id: str,
        task: str,
        step: int,
        tool: str,
        key_fn: Optional[Callable[..., str]] = None,
    ):
        """Decorator factory binding a stable effect key from function args.

        By default the key is derived from the args/kwargs (slightly unstable
        for object args), so callers with logical identity should pass
        ``key_fn`` that returns a stable string from the same args::

            @guard.as_decorator("agent-1", "task-7", 0, "webhook",
                                key_fn=lambda payload: payload["id"])
            def send(payload: dict) -> str:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., EffectOutcome]:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                if key_fn is not None:
                    params = {"_key": key_fn(*args, **kwargs)}
                else:
                    params = {"a": args, "k": kwargs}
                key = self.make_key(agent_id, task, step, tool, params)
                return self.execute_once(
                    key, agent_id=agent_id, tool=tool, call=lambda: fn(*args, **kwargs)
                )

            return wrapper

        return decorator
