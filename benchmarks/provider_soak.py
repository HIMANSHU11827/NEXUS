"""Deterministic configured-provider soak benchmark.

The harness bypasses router fallback. Live runs may call only providers named
with ``--provider`` and present in ``config/provider.yml``. Missing credentials,
authentication errors, and unavailable providers remain explicit results.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.attempts import ProviderAttemptRecorder
from providers.health import ProviderHealthRegistry
from providers.reliability import classify_failure, redact_secrets

SCHEMA_VERSION = "nexus-provider-soak-v1"
BENCHMARK_PROMPT = (
    "Return exactly one short sentence confirming that the configured provider "
    "is reachable. Do not call tools."
)
BENCHMARK_MESSAGES = [
    {"role": "system", "content": "You are a deterministic provider probe."},
    {"role": "user", "content": BENCHMARK_PROMPT},
]


def _normalise(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def configured_provider_ids(config: Mapping[str, Any]) -> list[str]:
    providers = config.get("providers", {}) if isinstance(config, Mapping) else {}
    if not isinstance(providers, Mapping):
        return []
    return sorted({_normalise(name) for name in providers if _normalise(name)})


def _safe_error(exc: BaseException | str) -> str:
    return redact_secrets(str(exc))[:400]


def _status_from_failure(classification: Any) -> str:
    name = str(getattr(getattr(classification, "failure_class", None), "value", "unknown"))
    if name == "auth_error":
        return "auth_failed"
    if name in {"network_error", "timeout", "temporary_outage"}:
        return "unavailable"
    return "failed"


def _local_endpoint_reachable(endpoint: str, timeout: float = 1.5) -> bool:
    """Perform a bounded TCP preflight for local providers only."""
    try:
        parsed = urlparse(str(endpoint or ""))
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except (OSError, ValueError, TypeError):
        return False


def _record(*, provider_id: str, model: str, rep: int, status: str,
            reason: str = "", duration_ms: float = 0.0,
            health: Optional[ProviderHealthRegistry] = None,
            attempts: Optional[ProviderAttemptRecorder] = None) -> dict[str, Any]:
    current = health.get(provider_id) if health else None
    return {
        "provider": provider_id,
        "model": model,
        "rep": rep,
        "status": status,
        "reason": _safe_error(reason),
        "duration_ms": round(max(0.0, duration_ms), 3),
        "health": current.to_dict() if current else None,
        "attempts": attempts.snapshot() if attempts else [],
    }


def run_soak(*, mode: str = "dry-run", providers: Optional[Iterable[str]] = None,
             reps: int = 1, config: Optional[Mapping[str, Any]] = None,
             factory: Any = None,
             provider_resolver: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    """Run deterministic probes with no implicit provider fallback.

    ``provider_resolver`` is injectable so the offline test suite never needs
    network credentials. Live mode requires an explicit provider list.
    """
    mode = str(mode or "dry-run").strip().lower()
    if mode not in {"dry-run", "live"}:
        raise ValueError("mode must be 'dry-run' or 'live'")
    reps = max(1, int(reps))
    config = config or {}
    configured = configured_provider_ids(config)
    requested = sorted({_normalise(item) for item in (providers or []) if _normalise(item)})
    if mode == "live" and not requested:
        raise ValueError("live mode requires at least one explicit --provider")
    selected = requested or configured
    unknown = [item for item in selected if item not in configured]
    if unknown:
        raise ValueError("provider is not configured: " + ", ".join(unknown))
    if provider_resolver is None:
        if factory is None:
            from providers.factory import NexusProviderFactory
            factory = NexusProviderFactory()
        provider_resolver = lambda name: factory.get_provider_by_name("cloud", name)

    records: list[dict[str, Any]] = []
    for provider_id in selected:
        for rep in range(1, reps + 1):
            health = ProviderHealthRegistry()
            attempts = ProviderAttemptRecorder()
            try:
                provider = provider_resolver(provider_id)
            except Exception as exc:
                records.append(_record(provider_id=provider_id, model="", rep=rep,
                                       status="unavailable",
                                       reason=f"provider_resolution: {_safe_error(exc)}",
                                       health=health, attempts=attempts))
                continue
            model = str(getattr(provider, "model", "") or "") if provider else ""
            if provider is None:
                records.append(_record(provider_id=provider_id, model=model, rep=rep,
                                       status="unavailable", reason="provider could not be constructed",
                                       health=health, attempts=attempts))
                continue
            endpoint = str(getattr(provider, "endpoint", "") or "").lower()
            local = any(host in endpoint for host in ("127.0.0.1", "localhost", "::1"))
            has_credentials = local or not hasattr(provider, "validate_api_key") or bool(provider.validate_api_key())
            if not has_credentials:
                attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                                model=model, status="failed", reason="missing or invalid credentials")
                health.mark_failure(provider_id, "missing or invalid credentials")
                records.append(_record(provider_id=provider_id, model=model, rep=rep,
                                       status="auth_failed", reason="missing or invalid credentials",
                                       health=health, attempts=attempts))
                continue
            if mode == "dry-run":
                attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                                model=model, status="planned", reason="network call suppressed by dry-run")
                records.append(_record(provider_id=provider_id, model=model, rep=rep,
                                       status="planned",
                                       reason="would issue one deterministic probe; no network call",
                                       health=health, attempts=attempts))
                continue

            if local and not _local_endpoint_reachable(endpoint):
                reason = "local_server_unreachable"
                health.mark_failure(provider_id, reason)
                attempts.record(
                    provider_id, credential_id=getattr(provider, "_credential_id", ""),
                    model=model, status="failed", reason=reason,
                )
                records.append(_record(
                    provider_id=provider_id, model=model, rep=rep,
                    status="unavailable", reason=reason,
                    health=health, attempts=attempts,
                ))
                continue

            started = time.perf_counter()
            attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                            model=model, status="started")
            status, reason = "success", "probe completed"
            try:
                response = provider.generate(messages=BENCHMARK_MESSAGES,
                                             temperature=0, max_tokens=16)
                if response is None or not str(response).strip():
                    classification = classify_failure(body="empty provider response")
                    status = _status_from_failure(classification)
                    reason = classification.message or "empty provider response"
                    health.mark_failure(provider_id, reason)
                    attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                                    model=model, status="failed", classification=classification,
                                    reason=reason, duration_ms=(time.perf_counter() - started) * 1000)
                else:
                    health.mark_success(provider_id, (time.perf_counter() - started) * 1000)
                    attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                                    model=model, status="success",
                                    duration_ms=(time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001 - preserve provider failure shape
                classification = classify_failure(exc)
                status = _status_from_failure(classification)
                reason = classification.message or _safe_error(exc)
                health.mark_failure(provider_id, reason)
                attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""),
                                model=model, status="failed", classification=classification,
                                reason=reason, duration_ms=(time.perf_counter() - started) * 1000)
            records.append(_record(provider_id=provider_id, model=model, rep=rep,
                                   status=status, reason=reason,
                                   duration_ms=(time.perf_counter() - started) * 1000,
                                   health=health, attempts=attempts))

    counts: dict[str, int] = {}
    for item in records:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "nexus-configured-provider-soak-v1",
        "mode": mode,
        "deterministic_prompt": BENCHMARK_PROMPT,
        "providers": selected,
        "reps": reps,
        "records": records,
        "status_counts": counts,
        "limitations": [
            "This measures provider reachability and runtime routing evidence, not model quality.",
            "Live mode never follows fallback_chain; each requested provider is isolated.",
            "Dry-run status 'planned' is not a successful provider probe.",
        ],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    parser.add_argument("--provider", action="append", default=[],
                        help="Explicit configured provider; repeat for multiple providers")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        from configure.config_loader import NexusConfigLoader
        config = NexusConfigLoader().get("provider", {}) or {}
        report = run_soak(mode=args.mode, providers=args.provider, reps=args.reps, config=config)
    except ValueError as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if args.mode == "live" and any(item["status"] != "success" for item in report["records"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
