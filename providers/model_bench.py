"""Per-task model scoreboard for task-aware provider routing.

NEXUS routers historically ordered fallback providers by static capability +
recent health alone. This module adds the missing quality signal: models are
scored per *task* via a benchmark-weight × score dot product (the task tables
live in ``config/model_tasks.json``, the per-model benchmark scores in
``config/provider.yml -> model_capabilities.providers.<id>``), hard-filtered
by latency/cost preference tiers, and ranked with a guaranteed deterministic
last-resort pick so a fallback mesh is never empty.

Design goals:
- Pure Python, stdlib only (no numpy) so it stays importable anywhere.
- Defensive: every config read is guarded. Any failure degrades to neutral
  scores / legacy ordering rather than raising into the router.
- Native NEXUS inputs: per-model annotations come from provider.yml and live
  provider state comes from ``providers/profiles.py`` (cooldown / error_count /
  usage_count) plus ``providers/health.py`` telemetry.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("NEXUS_MODEL_BENCH")

# ---------------------------------------------------------------------------
# Latency/cost preference tiers. These act as HARD filters applied *before*
# selection: candidates whose annotated latency or cost exceeds the tier caps
# are dropped from the mesh rather than merely scored lower.
#   latency_ms  -> milliseconds to first token
#   cost_per_1m -> USD per 1M tokens
# ---------------------------------------------------------------------------
_TIER_LIMITS: Dict[str, Dict[str, float]] = {
    "fast":     {"latency_ms": 1500.0, "cost_per_1m": 1.5},
    "balanced": {"latency_ms": 5000.0, "cost_per_1m": 10.0},
    "quality":  {"latency_ms": 20000.0, "cost_per_1m": 60.0},
}

# User-facing preference names map onto the three tiers above. Both the
# OmniRouter-style enums (lightning/cheap/premium/performance) and NEXUS's own
# vocabulary (fast/balanced/quality) resolve here.
_TIER_ALIASES: Dict[str, str] = {
    "lightning": "fast",
    "fast": "fast",
    "cheap": "fast",
    "balanced": "balanced",
    "premium": "quality",
    "performance": "quality",
    "heavy": "quality",
    "quality": "quality",
}

# Neutral score/an annotation defaults for providers without explicit config.
_DEFAULT_QUALITY = 0.5
_DEFAULT_ANNOTATIONS: Dict[str, Any] = {
    "cost_per_1m": 0.0,
    "latency_ms": 0.0,
    "benchmarks": {},
    "quality": _DEFAULT_QUALITY,
}

# Deterministic last-resort provider returned when there is nothing at all to
# rank. Lives in the same provider family as ``default_provider`` and the
# fallback_chain so resolvers can always construct it.
_DETERMINISTIC_FALLBACK: Tuple[str, ...] = ("deepseek",)

# Embedded fallback tables so ranking still produces results when the on-disk
# ``config/model_tasks.json`` is missing or corrupted.
_DEFAULT_TASKS: List[Dict[str, Any]] = [
    {
        "id": "coding",
        "keywords": ["code", "program", "python", "function", "api", "script", "debug", "bug", "implement"],
        "benchmarks": {"coding": 0.7, "reasoning": 0.2, "chat": 0.1},
    },
    {
        "id": "reasoning",
        "keywords": ["solve", "equation", "math", "logic", "reason", "deduce", "why", "proof"],
        "benchmarks": {"reasoning": 0.7, "coding": 0.2, "chat": 0.1},
    },
    {
        "id": "chat",
        "keywords": ["hello", "hi ", "how are you", "thanks", "small talk"],
        "benchmarks": {"chat": 0.8, "coding": 0.1, "reasoning": 0.1},
    },
    {
        "id": "summarization",
        "keywords": ["summarize", "summary", "abstract", "condense", "key points"],
        "benchmarks": {"summarization": 0.8, "chat": 0.1, "search": 0.1},
    },
    {
        "id": "search",
        "keywords": ["search", "find", "look up", "query", "web", "source", "reference"],
        "benchmarks": {"search": 0.7, "summarization": 0.2, "chat": 0.1},
    },
]


def resolve_tier(preferred: Optional[str] = None,
                 latency_tier: Optional[str] = None,
                 cost_tier: Optional[str] = None) -> str:
    """Collapse user latency/cost preferences into a routing tier name.

    Explicit kwargs win over the implicit ``NEXUS_PREFERRED`` /
    ``NEXUS_HEAVY_MODE`` environment signals. Unknown/empty values keep the
    balanced default so callers are never rejected.
    """
    for value in (latency_tier, cost_tier, preferred, os.environ.get("NEXUS_PREFERRED")):
        tier = _TIER_ALIASES.get(str(value or "").strip().lower())
        if tier:
            return tier
    heavy = os.environ.get("NEXUS_HEAVY_MODE", "").strip().lower()
    if heavy == "false":
        return "fast"
    if heavy in ("true", "1"):
        return "quality"
    return "balanced"


def tier_limits(tier: str) -> Dict[str, float]:
    """Resolve a tier name into (max_latency_ms, max_cost_per_1m) caps."""
    limits = _TIER_LIMITS.get(str(tier or "").lower())
    if not limits:
        # Unknown tier never blocks anything — bounded by the quality cap.
        return dict(_TIER_LIMITS["quality"])
    return dict(limits)


def load_tasks() -> List[Dict[str, Any]]:
    """Load per-task keyword + benchmark-weight tables from config."""
    path = Path(__file__).resolve().parent.parent / "config" / "model_tasks.json"
    raw: Any = None
    try:
        if path.exists():
            raw = json.loads(path.read_text("utf-8"))
    except Exception:
        logger.warning("providers/model_bench.py:16 load_tasks suppressed error", exc_info=True)
    tasks: List[Dict[str, Any]] = []
    if isinstance(raw, dict):
        listed = raw.get("tasks") or []
        if isinstance(listed, list):
            tasks = [t for t in listed if isinstance(t, dict) and t.get("id")]
    # Embedded tables guarantee the scoreboard is never empty.
    return tasks or [dict(t) for t in _DEFAULT_TASKS]


def classify_task(text: str, candidates: Optional[Sequence[str]] = None) -> Optional[str]:
    """Cheap keyword-only task classifier (no embeddings required).

    Scores each known task by keyword overlap with the prompt and returns the
    single best task id. ``candidates`` optionally restricts classification to
    a caller-provided set (for example the keys of a routing table). Returns
    None when nothing matches so callers can keep their legacy classifier as
    a true fallback.
    """
    text = " ".join(str(text or "").split()).lower()
    if not text:
        return None
    tasks = load_tasks()
    if candidates:
        known = {str(t.get("id", "")) for t in tasks}
        tasks = [t for t in tasks if str(t.get("id", "")) in {str(c) for c in candidates}]
        for candidate in candidates:
            candidate = str(candidate or "")
            # Unknown routing key: treat a verbatim occurrence as a hit so
            # existing substring-based routing tables keep working unchanged.
            if candidate and candidate not in known:
                tasks.append({"id": candidate, "keywords": [candidate], "benchmarks": {}})
    best_id: Optional[str] = None
    best_score = 0
    for entry in tasks:
        keywords = entry.get("keywords") or []
        if not isinstance(keywords, list):
            continue
        score = sum(1 for kw in keywords if str(kw or "") and str(kw) in text)
        if score > best_score:
            best_score = score
            best_id = str(entry.get("id", "")) or None
    return best_id


def _task_entry(task: Any) -> Dict[str, Any]:
    """Normalize a task given as id string or entry dict."""
    if isinstance(task, dict):
        return task if task.get("id") else {}
    task_id = str(task or "")
    if not task_id:
        return {}
    for entry in load_tasks():
        if entry.get("id") == task_id:
            return entry
    return {}


def _provider_config() -> Dict[str, Any]:
    """Raw provider.yml via the shared loader (itself cached)."""
    try:
        from config.config_loader import NexusConfigLoader
        cfg = NexusConfigLoader().get("provider", {}) or {}
    except Exception:
        logger.debug("providers/model_bench.py:78 _provider_config skipped", exc_info=True)
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _provider_annotations(provider_id: Any,
                          override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merged cost/latency/benchmark annotations for one provider."""
    provider_id = str(provider_id or "").lower()
    if override and provider_id in override:
        entry = override[provider_id]
        return dict(entry) if isinstance(entry, dict) else dict(_DEFAULT_ANNOTATIONS)
    annotations = dict(_DEFAULT_ANNOTATIONS)
    caps = _provider_config().get("model_capabilities") or {}
    providers = caps.get("providers") or {}
    entry = providers.get(provider_id)
    if isinstance(entry, dict):
        for key in ("cost_per_1m", "latency_ms", "benchmarks", "quality"):
            if key in entry:
                annotations[key] = entry[key]
    return annotations


def _profile_penalty(provider: Any) -> float:
    """Small ranking penalty for providers whose live profile state says "hurt".

    Builds on ``providers/profiles.py`` (cooldown_until / error_count / usage):
    a profile in cooldown or with a growing error_count is a real availability
    risk and should rank a notch below an otherwise equal competitor.
    """
    try:
        from providers import profiles as _profiles_module
        store = _profiles_module.load_profile_store()
        profiles = store.list_profiles(str(provider or "").lower())
    except Exception:
        return 0.0
    if not profiles:
        return 0.0
    worst = 0.0
    for profile in profiles:
        if profile.in_cooldown:
            worst = max(worst, 0.3)
        else:
            worst = max(worst, min(0.05 * getattr(profile, "error_count", 0), 0.25))
    return worst


def score_model(task: Any, provider: Any, caps: Any = None,
                annotations: Optional[Dict[str, Any]] = None,
                health: Any = None) -> float:
    """Numeric quality score (0..1) for one provider on one task.

    Baseline is a benchmark-weight × per-model-benchmark dot product from the
    task tables and provider.yml annotations. NEXUS-native signals — the
    capability registry, live profile state and health telemetry — nudge the
    score without ever dominating the configured benchmark ordering.
    """
    entry = _task_entry(task)
    if not entry or not provider:
        return 0.0
    info = _provider_annotations(provider, annotations)
    benchmarks = info.get("benchmarks") or {}
    if not isinstance(benchmarks, dict):
        benchmarks = {}
    weights = entry.get("benchmarks") or {}
    acc = 0.0
    denom = 0.0
    for bench, weight in (weights or {}).items():
        bench_score = benchmarks.get(bench)
        if bench_score is None:
            continue
        acc += float(bench_score) * float(weight)
        denom += float(weight)
    quality = acc / denom if denom else float(info.get("quality", _DEFAULT_QUALITY))

    # Capability signal: more context / richer tool support nudges an
    # otherwise-tied benchmark score upward (bounded so it stays a nudge).
    if caps is not None:
        try:
            cap = caps.get(provider)
            quality += min(max(int(cap.context_window), 0) / 8_000_000, 0.08)
            if cap.tools:
                quality += 0.03
            if cap.vision:
                quality += 0.02
        except Exception:
            pass

    quality -= _profile_penalty(provider)
    if health is not None:
        try:
            if health.is_degraded(provider):
                quality -= 0.35
        except Exception:
            pass
    return max(0.0, min(1.0, quality))


def rank_models(task: Any, candidates: Sequence[str], caps: Any = None, *,
                max_cost: Optional[float] = None,
                max_latency: Optional[float] = None,
                tier: str = "balanced",
                annotations: Optional[Dict[str, Any]] = None,
                health: Any = None,
                fallback: Optional[Sequence[str]] = None) -> List[str]:
    """Return provider ids for a task, best-first, hard-filtered by latency/cost.

    HARD FILTERS: providers whose annotated latency_ms or cost_per_1m exceeds
    the tier caps are dropped before selection. When every candidate would be
    dropped the ranking relaxes to the best-scoring candidate so the mesh is
    never empty, and when there is nothing to rank at all the deterministic
    fallback is returned. Sorting is stable, so ties keep caller order.
    """
    limits = tier_limits(tier)
    max_cost = float(max_cost) if max_cost is not None else float(limits["cost_per_1m"])
    max_latency = float(max_latency) if max_latency is not None else float(limits["latency_ms"])
    fallback = list(fallback) if fallback else list(_DETERMINISTIC_FALLBACK)
    names = [str(candidate) for candidate in (candidates or [])]
    if not names:
        return fallback

    scored = []
    for name in names:
        info = _provider_annotations(name, annotations)
        latency = float(info.get("latency_ms", 0.0) or 0.0)
        cost = float(info.get("cost_per_1m", 0.0) or 0.0)
        scored.append((
            score_model(task, name, caps=caps, annotations=annotations, health=health),
            name,
            latency,
            cost,
        ))
    scored.sort(key=lambda item: item[0], reverse=True)

    within_limits = [name for _, name, latency, cost in scored
                     if latency <= max_latency and cost <= max_cost]
    if within_limits:
        return within_limits
    # Hard filters would empty the mesh: relax to the best-score ordering. A
    # degraded-but-reachable provider beats dispatching to nothing at all.
    relaxed = [name for _, name, _, _ in scored]
    return relaxed if relaxed else fallback
