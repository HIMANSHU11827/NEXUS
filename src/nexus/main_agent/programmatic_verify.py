"""Explicit, sandboxed verification workflow for V5.

Hermes exposes ``hermes verify`` as a first-class recipe runner whose phase
facts are persisted independently of the model loop.  Nexus previously only
classified terminal actions after they had already run.  This module adds a
small equivalent for callers that already have an explicit verification
recipe: execute each command through :class:`SovereignSandbox`, preserve the
trusted exit code, and persist bounded verifier events/state.
"""

from __future__ import annotations

import asyncio
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from sandbox.sandbox_manager import SovereignSandbox
from nexus.runtime import safe_session_id

from .verification_commands import classify_verification_command
from .verification_events import VerifierEventStore
from .verification_state import VerifierStateStore


@dataclass
class VerificationCommandFact:
    """Bounded fact for one command in an explicit verification run."""

    command: str
    phase: str
    status: str
    exit_code: Optional[int]
    duration_seconds: float
    output_summary: str = ""
    canonical_command: str = ""
    kind: str = ""
    scope: str = "targeted"
    reason: str = ""
    cwd: str = ""
    root: str = ""
    session_id: str = ""
    timed_out: bool = False
    execution_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "phase": self.phase,
            "canonical_command": self.canonical_command,
            "kind": self.kind,
            "scope": self.scope,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "output_summary": self.output_summary,
            "reason": self.reason,
            "cwd": self.cwd,
            "root": self.root,
            "session_id": self.session_id,
            "timed_out": self.timed_out,
            "execution_error": self.execution_error,
        }


@dataclass
class VerificationReadinessFact:
    url: str
    ready: bool
    status_code: Optional[int]
    duration_seconds: float
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ready": self.ready,
            "status_code": self.status_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "error": self.error,
        }


@dataclass
class ProgrammaticVerificationResult:
    """Durable, JSON-ready result for a programmatic verification run."""

    run_id: str
    session_id: str
    root: str
    status: str
    sandbox_tier: str
    commands: list[VerificationCommandFact] = field(default_factory=list)
    readiness: Optional[VerificationReadinessFact] = None
    verifier_id: str = ""
    event_id: str = ""
    durable_status: str = "unverified"
    recipe_name: str = ""
    recipe_source: str = ""

    @property
    def success(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "root": self.root,
            "status": self.status,
            "success": self.success,
            "sandbox_tier": self.sandbox_tier,
            "commands": [item.to_dict() for item in self.commands],
            "readiness": self.readiness.to_dict() if self.readiness else None,
            "verifier_id": self.verifier_id,
            "event_id": self.event_id,
            "durable_status": self.durable_status,
            "recipe_name": self.recipe_name,
            "recipe_source": self.recipe_source,
        }


def _bounded_output(value: Any) -> str:
    from models.providers.core.reliability import redact_secrets

    return redact_secrets(str(value or "")).strip()[:1500]


def _loopback_url(value: Any) -> Optional[str]:
    text = str(value or "").strip()[:500]
    try:
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            return None
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return None
        return text
    except ValueError:
        return None


def _probe_readiness(url: str, timeout: float, interval: float = 0.25) -> VerificationReadinessFact:
    started = time.monotonic()
    deadline = started + max(0.1, float(timeout))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=min(5.0, max(0.1, deadline - time.monotonic()))) as response:
                return VerificationReadinessFact(
                    url=url, ready=True, status_code=int(getattr(response, "status", 200)),
                    duration_seconds=time.monotonic() - started,
                )
        except urllib.error.HTTPError as exc:
            return VerificationReadinessFact(
                url=url, ready=True, status_code=int(exc.code),
                duration_seconds=time.monotonic() - started,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = str(exc)[:500]
            time.sleep(min(interval, max(0.01, deadline - time.monotonic())))
    return VerificationReadinessFact(
        url=url, ready=False, status_code=None,
        duration_seconds=time.monotonic() - started,
        error=last_error or "readiness timeout",
    )


async def run_programmatic_verification(
    root: str | Path,
    commands: Iterable[str],
    *,
    session_id: str = "default",
    timeout: float = 600.0,
    shell: Optional[str] = None,
    configured_commands: Iterable[str] = (),
    total_timeout: Optional[float] = None,
    readiness_url: Optional[str] = None,
    readiness_timeout: float = 10.0,
    stop_on_failure: bool = True,
) -> ProgrammaticVerificationResult:
    """Run explicit verification commands and persist their trusted facts.

    Commands are executed one at a time through Nexus' configured sandbox.
    Shell composition, missing exit codes, and unclassifiable commands never
    produce a passing verdict.  The caller owns the recipe; unlike automatic
    detection, this function does not invent commands or silently fall back to
    an unisolated runner.
    """
    root_path = Path(root).expanduser().resolve()
    checks: list[tuple[str, str]] = []
    for item in commands:
        if isinstance(item, dict):
            command = str(item.get("command") or "").strip()
            phase = str(item.get("phase") or "test").strip().lower()
        else:
            command = str(item).strip()
            phase = "test"
        if command:
            checks.append((command[:12000], phase[:32] or "test"))
    normalized_commands = [command for command, _phase in checks]
    run_id = f"vr_{uuid.uuid4().hex[:24]}"
    sandbox = SovereignSandbox(str(root_path))
    started_run = time.monotonic()
    total_deadline = started_run + float(total_timeout if total_timeout is not None else timeout * max(1, len(normalized_commands)))
    trusted_recipe = tuple(str(item).strip()[:500] for item in configured_commands if str(item).strip())
    result = ProgrammaticVerificationResult(
        run_id=run_id,
        session_id=safe_session_id(session_id),
        root=str(root_path),
        status="unverified" if not normalized_commands else "passed",
        sandbox_tier=getattr(getattr(sandbox, "tier", None), "value", "unknown"),
    )

    status_rank = {"passed": 0, "unverified": 1, "failed": 2, "blocked": 3}
    for command, phase in checks:
        remaining = total_deadline - time.monotonic()
        if remaining <= 0:
            result.status = "blocked"
            result.commands.append(VerificationCommandFact(
                command=command[:500], phase=phase, status="blocked", exit_code=None,
                duration_seconds=0.0, reason="total verification deadline exceeded",
                cwd=str(root_path), root=str(root_path), session_id=result.session_id,
            ))
            break
        started = time.monotonic()
        chunks: list[str] = []
        execution_error = ""
        timed_out = False
        try:
            async for chunk in sandbox.stream_execute(
                command, str(root_path), timeout=min(float(timeout), remaining), shell=shell
            ):
                chunks.append(str(chunk))
            exit_code = sandbox.last_exit_code
        except Exception as exc:
            exit_code = None
            execution_error = str(exc)[:500]
            chunks.append(f"[VERIFICATION_ERROR]: {execution_error}")
            timed_out = "timeout" in execution_error.lower()
        output = _bounded_output("".join(chunks))
        fact = classify_verification_command(
            command,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            output=output,
            configured_commands=trusted_recipe,
        )
        duration = time.monotonic() - started
        if fact is None:
            item = VerificationCommandFact(
                command=command[:500], status="unverified",
                phase=phase,
                exit_code=exit_code if isinstance(exit_code, int) else None,
                duration_seconds=duration, output_summary=output,
                reason="command was not safely classifiable or had no trusted exit code",
                cwd=str(root_path), root=str(root_path), session_id=result.session_id,
                timed_out=timed_out, execution_error=execution_error,
            )
            if status_rank["unverified"] > status_rank.get(result.status, 0):
                result.status = "unverified"
        else:
            item = VerificationCommandFact(
                command=str(fact.get("command") or command)[:500],
                phase=phase,
                canonical_command=str(fact.get("canonical_command") or "")[:500],
                kind=str(fact.get("kind") or "")[:40],
                scope=str(fact.get("scope") or "targeted")[:40],
                status=str(fact.get("status") or "failed"),
                exit_code=fact.get("exit_code") if isinstance(fact.get("exit_code"), int) else None,
                duration_seconds=duration,
                output_summary=str(fact.get("output_summary") or "")[:1500],
                cwd=str(root_path), root=str(root_path), session_id=result.session_id,
                timed_out=timed_out, execution_error=execution_error,
            )
            item_status = item.status if item.status in status_rank else "unverified"
            if status_rank[item_status] > status_rank.get(result.status, 0):
                result.status = item_status
        result.commands.append(item)
        if result.status != "passed" and stop_on_failure:
            break

    if result.status == "passed" and readiness_url:
        safe_url = _loopback_url(readiness_url)
        if safe_url is None:
            result.readiness = VerificationReadinessFact(
                url=str(readiness_url)[:500], ready=False, status_code=None,
                duration_seconds=0.0, error="readiness URL must target localhost",
            )
            result.status = "failed"
        else:
            # urllib and its retry sleep are synchronous. Keep readiness
            # probing off the event loop so verification cannot starve active
            # runs, gateway heartbeats, or UI streaming.
            result.readiness = await asyncio.to_thread(
                _probe_readiness, safe_url, readiness_timeout
            )
            if not result.readiness.ready:
                result.status = "failed"

    if result.status in {"passed", "failed"}:
        verifier_id = f"verify_{uuid.uuid4().hex[:24]}"
        result.verifier_id = verifier_id
        event_store = VerifierEventStore(
            root_path / ".nexus_v5" / "verifier_events.sqlite3"
        )
        for command_fact in result.commands:
            event_store.record(
                result.session_id, str(root_path), verifier_id=verifier_id,
                run_id=run_id, phase=command_fact.phase,
                status=command_fact.status, command=command_fact.command,
                canonical_command=command_fact.canonical_command or command_fact.command,
                kind=command_fact.kind or "programmatic_verify",
                scope=command_fact.scope, exit_code=command_fact.exit_code,
                output_summary=command_fact.output_summary,
            )
        last = result.commands[-1] if result.commands else None
        failed_codes = [item.exit_code for item in result.commands if isinstance(item.exit_code, int) and item.exit_code != 0]
        aggregate_exit_code = failed_codes[0] if failed_codes else (0 if result.success else 1)
        event = event_store.record(
            result.session_id,
            str(root_path),
            verifier_id=verifier_id,
            run_id=run_id,
            phase="verify",
            status=result.status,
            command="nexus verify",
            canonical_command="nexus verify",
            kind="programmatic_verify",
            scope="targeted" if any(item.scope == "targeted" for item in result.commands) else "full",
            exit_code=aggregate_exit_code,
            output_summary=("\n".join(item.output_summary for item in result.commands)
                            + (f"\n[readiness] {result.readiness.error}" if result.readiness and result.readiness.error else ""))[-1500:],
        )
        result.event_id = str(event.get("event_id") or "")
        state = VerifierStateStore(root_path / ".nexus_v5" / "verifier_state.json").record_verification(
            result.session_id, str(root_path), status=result.status,
            verifier_id=verifier_id, event_id=result.event_id,
        )
        result.durable_status = str(state.get("status") or "unverified")
    return result


async def run_detected_verification(
    root: str | Path,
    *,
    session_id: str = "default",
    timeout: float = 600.0,
    total_timeout: Optional[float] = None,
    stop_on_failure: bool = True,
) -> ProgrammaticVerificationResult:
    """Detect and run a local recipe without starting an application process."""
    from .verification_recipes import detect_verification_recipe

    recipe = detect_verification_recipe(root)
    if recipe is None:
        path = Path(root).expanduser().resolve()
        return ProgrammaticVerificationResult(
        run_id=f"vr_{uuid.uuid4().hex[:24]}", session_id=safe_session_id(session_id),
            root=str(path), status="not_applicable", sandbox_tier="unknown",
        )
    result = await run_programmatic_verification(
        root, list(recipe.checks), session_id=session_id, timeout=timeout,
        total_timeout=total_timeout, configured_commands=tuple(item["command"] for item in recipe.checks),
        stop_on_failure=stop_on_failure,
    )
    result.recipe_name = recipe.name
    result.recipe_source = recipe.source
    return result


__all__ = [
    "ProgrammaticVerificationResult",
    "VerificationCommandFact",
    "VerificationReadinessFact",
    "run_programmatic_verification",
    "run_detected_verification",
]
