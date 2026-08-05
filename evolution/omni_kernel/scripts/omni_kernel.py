"""OmniEvolutionKernel — minimal orchestration of the real evolution subsystems.

Runs a fixed sequence of already-implemented evolution stages — the
EvolutionLog win/lose ledger, the improvement-action backlog, MemoryForge
crystallization, and the SkillCurator sweep — and returns a per-stage result
dict. Each stage is fault-isolated: one failing stage is reported and never
blocks the others, and ``evolve()`` itself never raises because a stage did.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

IS_STUB = False

STAGE_LEDGER = "ledger"
STAGE_BACKLOG = "backlog"
STAGE_MEMORY_FORGE = "memory_forge"
STAGE_CURATOR = "curator"

DEFAULT_STAGES = (STAGE_LEDGER, STAGE_BACKLOG, STAGE_MEMORY_FORGE, STAGE_CURATOR)


class OmniEvolutionKernel:
    """Runs the real evolution subsystems in sequence with fault isolation."""

    is_stub = False

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.last_evolve: Dict[str, Any] = {}
        self.last_run_at: Optional[float] = None

    # ── Public API ─────────────────────────────────────────────────────

    def evolve(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Run all evolution stages and return per-stage results.

        Accepted forms (backward compatible with the old stub signature):
          evolve("win", {"title": "...", "action": "...", "score": 0.8}, reason="...")
          evolve(payload_dict)
          evolve(outcome="win", payload={...}, reason="...")
        An optional ``stages`` kwarg selects a subset of stage names to run.
        """
        outcome, payload, reason = _parse_evolve_args(args, kwargs)
        selected = list(kwargs.get("stages") or DEFAULT_STAGES)
        cycle_id = f"evolve_{uuid.uuid4().hex[:8]}"
        stages: List[Dict[str, Any]] = []
        for name in selected:
            stages.append(self._run_stage(name, outcome=outcome, payload=payload, reason=reason))
        result = {
            "status": "ok",
            "cycle_id": cycle_id,
            "stages": stages,
            "failed_stages": [s["name"] for s in stages if s["status"] != "ok"],
        }
        self.last_evolve = result
        self.last_run_at = time.time()
        return result

    def run_cycle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """A scheduled cycle is just an evolve() without a win/lose outcome."""
        kwargs.setdefault("outcome", None)
        return self.evolve(*args, **kwargs)

    def status(self) -> Dict[str, Any]:
        stages = self.last_evolve.get("stages", []) if self.last_evolve else []
        return {
            "status": "ok",
            "is_stub": False,
            "module": "OmniEvolutionKernel",
            "root": self.root,
            "stages": [s["name"] for s in stages],
            "last_cycle_id": self.last_evolve.get("cycle_id"),
            "last_run_at": self.last_run_at,
            "failed_stages": [s["name"] for s in stages if s["status"] != "ok"],
        }

    # ── Fault-isolated stage dispatch ──────────────────────────────────

    def _run_stage(self, name: str, *, outcome: Optional[str], payload: Dict[str, Any],
                   reason: str) -> Dict[str, Any]:
        try:
            detail = self._stage_handler(name)(outcome=outcome, payload=payload, reason=reason)
        except Exception as exc:  # fault isolation: never let one stage sink the cycle
            logger.warning("OmniEvolutionKernel stage '%s' failed: %s", name, exc)
            return {"name": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        if not detail:
            return {"name": name, "status": "ok"}
        return {"name": name, "status": "ok", **detail}

    def _stage_handler(self, name: str) -> Callable[..., Dict[str, Any]]:
        handlers: Dict[str, Callable[..., Dict[str, Any]]] = {
            STAGE_LEDGER: self._stage_ledger,
            STAGE_BACKLOG: self._stage_backlog,
            STAGE_MEMORY_FORGE: self._stage_memory_forge,
            STAGE_CURATOR: self._stage_curator,
        }
        handler = handlers.get(name)
        if handler is None:
            def _unknown(*, outcome: Optional[str], payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
                raise ValueError(f"unknown evolution stage: {name!r}")
            return _unknown
        return handler

    # ── Stages (each lazy-imports its real subsystem) ──────────────────

    def _stage_ledger(self, *, outcome: Optional[str], payload: Dict[str, Any],
                      reason: str) -> Dict[str, Any]:
        from evolution.logs import EvolutionLog
        if outcome not in ("win", "lose"):
            return {"recorded_outcome": None, "note": "no win/lose outcome provided; ledger untouched"}
        log = EvolutionLog(self.root)
        score = float(payload.get("score", payload.get("delta", 0.0)) or 0.0)
        message = str(payload.get("message") or reason or "evolution_cycle")
        record = (log.win if outcome == "win" else log.lose)(
            "evolve", message, message,
            score=score, metadata={"source": "omni_evolution", "reason": reason},
        )
        return {"recorded_outcome": outcome, "event_id": record.get("event_id"), "score": score}

    def _stage_backlog(self, *, outcome: Optional[str], payload: Dict[str, Any],
                       reason: str) -> Dict[str, Any]:
        from evolution.backlog import queue_improvement_action
        action_text = payload.get("action")
        if not action_text:
            return {"queued": 0, "note": "no payload['action'] provided; backlog untouched"}
        entry = queue_improvement_action(
            {"action": str(action_text), "source": "omni_evolution", "score": payload.get("score")},
            root=self.root,
        )
        return {"queued": 1 if entry else 0, "action_id": (entry or {}).get("id")}

    def _stage_memory_forge(self, *, outcome: Optional[str], payload: Dict[str, Any],
                            reason: str) -> Dict[str, Any]:
        title = payload.get("title")
        if not title:
            return {"forged": False, "note": "no payload['title'] provided; nothing crystallized"}
        from evolution.memory_forge.scripts.forge import MemoryForge
        content = str(payload.get("content") or f"Crystallized from evolution cycle: {reason}")
        result = MemoryForge(self.root).forge(str(title), content)
        return {
            "forged": bool(result.get("created")),
            "memory_name": result.get("name"),
            "memory_path": result.get("path"),
        }

    def _stage_curator(self, *, outcome: Optional[str], payload: Dict[str, Any],
                       reason: str) -> Dict[str, Any]:
        from evolution.curator.scripts.curator import SkillCurator
        result = SkillCurator(self.root).run_once()
        return {"curator_status": result.get("status"), "archived": result.get("archived", 0)}


def _parse_evolve_args(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any], str]:
    outcome: Optional[str] = None
    payload: Dict[str, Any] = {}
    if args:
        first = args[0]
        if isinstance(first, dict):
            payload.update(first)
        else:
            outcome = str(first)
    if len(args) > 1 and isinstance(args[1], dict):
        payload.update(args[1])
    if kwargs.get("payload") and isinstance(kwargs["payload"], dict):
        payload.update(kwargs["payload"])
    if kwargs.get("outcome") is not None:
        outcome = str(kwargs["outcome"])
    reason = str(kwargs.get("reason") or kwargs.get("signature") or "evolution_cycle")
    return outcome, payload, reason
