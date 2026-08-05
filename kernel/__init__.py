"""NEXUS kernel: shared runtime services for tools, providers, memory, and telemetry.

Redesigned bootstrap:
  * Thread-safe singleton (``get_nexus_kernel()``) with lazy-loaded subsystems.
  * Each lazy subsystem loads behind its own try/except — a failure degrades to
    a :class:`FailedSubsystem` placeholder (``loaded=False``, records ``error``)
    instead of crashing ``get_nexus_kernel()``.
  * ``kernel.health_check()`` reports per-subsystem ``{name, loaded, ok, error,
    latency_ms}`` and never raises.
  * Declared dependency ordering (``after`` refs): a subsystem whose dependency
    failed is skipped with a recorded reason instead of raising.
  * Memoized lazy properties with first-access latency tracking; nothing is
    pre-loaded until accessed.
  * ``kernel.reset()`` drops the cached singleton cleanly;
    ``kernel.reload(reason=...)`` drops cached instances so loaders re-run and
    records the reason.
  * ``kernel.get_component_stages()`` maps loaded subsystems to ``LifecycleStage``
    names by importing the lifecycle constants read-only (degrades to a minimal
    dict if lifecycle is unavailable). Lifecycle is NOT wired into the kernel.
"""

import glob
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil
from dotenv import load_dotenv

from utils.nexus_compat import import_requests, itail, s, safe_round
from utils.singleton import ThreadSafeSingleton

# Load .env at kernel import — covers both `python -m nexus` and direct imports
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", ".env")
if os.path.isfile(_env_path):
    load_dotenv(_env_path)

_requests: Any = import_requests()
logger = logging.getLogger("NEXUS_KERNEL")


# ─────────────────────────────────────────────────────────────────────────────
# Soft-degrade primitives
# ─────────────────────────────────────────────────────────────────────────────

class _Missing:
    """Singleton sentinel returned when a FailedSubsystem attribute is touched.

    Callable, iterable, and falsy, so attribute chains degrade gracefully
    instead of raising. Anything seriously sensitive (dunders) still raises
    AttributeError to keep Python internals safe.
    """

    def __new__(cls):
        if getattr(cls, "_instance", None) is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __call__(self, *args: Any, **kwargs: Any) -> "_Missing":
        return self

    def __bool__(self) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0

    def __eq__(self, other: Any) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash("_Missing")

    def __getattr__(self, item: str) -> "_Missing":
        if item.startswith("__"):
            raise AttributeError(item)
        return self

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


class FailedSubsystem:
    """Placeholder for a subsystem that could not be loaded.

    Carries the failure/skip reason and load latency so callers and
    ``health_check()`` can diagnose the fault. Attribute and method access
    soft-degrades to the ``_MISSING`` sentinel rather than raising, so one sick
    subsystem can never take the whole kernel down.
    """

    def __init__(self,
                 name: str,
                 error: Optional[BaseException] = None,
                 reason: Optional[str] = None,
                 latency_ms: Optional[float] = None) -> None:
        self.name = name
        self.error = error
        self.reason = reason
        self.latency_ms = latency_ms
        self.loaded = False
        self.ok = False
        self.skipped = reason is not None

    @property
    def msg(self) -> str:
        if self.error is not None:
            return f"{type(self.error).__name__}: {self.error}"
        return self.reason or "unknown failure"

    def __getattr__(self, item: str) -> Any:
        if item.startswith("__"):
            raise AttributeError(item)
        return _MISSING

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<FailedSubsystem name={self.name!r} {self.msg!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# Subsystem registry — registration order is load order.
# ─────────────────────────────────────────────────────────────────────────────

# Each entry: {"loader": callable(self) -> instance, "after": tuple of names
# that must load first (dependency ordering)}.
_SUBSYSTEMS: Dict[str, Dict[str, Any]] = {}


def _register(name: str, after: Tuple[str, ...] = ()) -> Callable:
    """Register a subsystem loader with optional dependency refs."""
    def deco(fn: Callable) -> Callable:
        _SUBSYSTEMS[name] = {"loader": fn, "after": tuple(after)}
        return fn
    return deco


class NexusKernel(ThreadSafeSingleton):
    """
    Shared core runtime.
    Lazily owns configuration, provider routing, tools, RAG, memory, and telemetry.
    """

    # Degraded stage names used when the lifecycle package is unavailable.
    _MINIMAL_STAGES: Dict[str, str] = {
        "CREATED": "created", "READY": "ready", "RUNNING": "running",
        "FAILED": "failed", "QUARANTINED": "quarantined",
    }

    def __init__(self, root_dir: Optional[str] = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # ── 1. Path Initialization ──
        _curr = os.path.dirname(os.path.abspath(__file__))
        self.root = root_dir if root_dir else os.path.dirname(_curr)
        self.workspace = os.path.join(self.root, "workspace")
        os.makedirs(self.workspace, exist_ok=True)

        # ── 2. Identity & Metrics ──
        self.kernel_id = str(uuid.uuid4())
        self.start_time = time.time()
        self.token_usage = 0
        self.model_mesh: Dict[str, List[str]] = {}
        self._state_path = os.path.join(self.workspace, "kernel_state.json")

        # ── 3. Private Cache for Lazy Loading ──
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._load_latency_ms: Dict[str, float] = {}

        # ── 4. Reload & Lifecycle Bookkeeping ──
        self._reload_reason: Optional[str] = None
        self._reload_history: List[Dict[str, Any]] = []
        self._lifecycle_stage_cache: Optional[Dict[str, str]] = None

        # ── 5. Boot Sequence ──
        logger.info(f"--- NEXUS KERNEL active (ID: {s(self.kernel_id, 4)}) ---")
        self._restore_state()

    # ── Subsystem Loaders ────────────────────────────────────────────────────
    # Registered in load order. Each loader runs behind its own try/except
    # inside _component(): import errors AND constructor failures both degrade
    # to a FailedSubsystem placeholder instead of crashing the kernel.

    @_register("config")
    def config(self):
        from config.config_loader import NexusConfigLoader
        return NexusConfigLoader()

    @_register("moe")
    def moe(self):
        from intelligence.moe_router import NexusMoERouter
        return NexusMoERouter()

    @_register("moa", after=("moe",))
    def moa(self):
        from intelligence.moa import MixtureOfArchitects
        return MixtureOfArchitects(self.moe.base_router)

    @_register("nerve")
    def nerve(self):
        from neural.nerve_center import NexusNerveCenter
        return NexusNerveCenter(self.root)

    @_register("omni")
    def omni(self):
        from evolution.omni_kernel import OmniEvolutionKernel
        return OmniEvolutionKernel(self.root)

    @_register("hyper")
    def hyper(self):
        from evolution.hyper_kernel import HyperKernel
        return HyperKernel(self.root)

    @_register("researcher")
    def researcher(self):
        from evolution.researcher import NexusResearcher
        return NexusResearcher(self.root)

    @_register("persistence")
    def persistence(self):
        from context.persistence import NexusFilePersistence
        return NexusFilePersistence(self.root)

    @_register("hal")
    def hal(self):
        from hardware.manager import NexusHardwareManager
        return NexusHardwareManager()

    @_register("horizons")
    def horizons(self):
        from evolution.horizons import StrategicHorizons
        return StrategicHorizons(self.root)

    @_register("local_brain")
    def local_brain(self):
        from intelligence.local_brain import NexusLocalBrain
        return NexusLocalBrain(self.root)

    @_register("trainer")
    def trainer(self):
        from neural.trainer import NexusTrainer
        return NexusTrainer(self.root)

    @_register("indexer")
    def indexer(self):
        from indexer import NexusSemanticIndexer
        return NexusSemanticIndexer(self.root)

    @_register("intent")
    def intent(self):
        from evolution.intent.scripts.engine import NexusIntentEngine
        return NexusIntentEngine()

    @_register("prover")
    def prover(self):
        from safety.prover import LogicProver
        return LogicProver(strictness=0.9)

    @_register("tools")
    def tools(self):
        from tools.nexus_tools.registry import ToolRegistry
        return ToolRegistry(self.root)

    @_register("telemetry")
    def telemetry(self):
        from kernel.telemetry import NexusTelemetryDB
        return NexusTelemetryDB()

    @_register("rag")
    def rag(self):
        from rag.engine import NexusAtlasRAG
        return NexusAtlasRAG()

    @_register("hive")
    def hive(self):
        from hive.engine import NexusHiveEngine
        return NexusHiveEngine(self.root)

    @_register("plugins")
    def plugins(self):
        from plugins.manager import PluginManager
        return PluginManager(self.root)

    # ── Lazy loading core ────────────────────────────────────────────────────

    def _component(self, name: str, loader: Optional[Callable[[], Any]] = None) -> Any:
        """Memoized, fault-isolated lazy loader for a subsystem.

        Returns the cached instance when present (memoization — subsystems are
        never double-loaded). On first access it resolves ``after`` dependency
        refs in declared order; a dependency that failed skips this subsystem
        with a recorded reason. Any import or construction error degrades to a
        :class:`FailedSubsystem` placeholder instead of raising.
        """
        with self._lock:
            cached = self._instances.get(name)
            if cached is not None:
                return cached

            spec = _SUBSYSTEMS.get(name, {})
            effective_loader = loader if loader is not None else spec.get("loader")

            if loader is None:
                # Dependency ordering: prerequisites must load first.
                for dep in spec.get("after", ()):
                    dep_instance = self._component(dep)
                    if isinstance(dep_instance, FailedSubsystem):
                        placeholder = FailedSubsystem(name, reason=f"dependency '{dep}' failed")
                        self._instances[name] = placeholder
                        logger.warning("Subsystem '%s' skipped: dependency '%s' failed", name, dep)
                        return placeholder

            if effective_loader is None:
                placeholder = FailedSubsystem(
                    name, error=RuntimeError(f"no loader registered for subsystem '{name}'"))
                self._instances[name] = placeholder
                return placeholder

            started = time.perf_counter()
            try:
                # Registry loaders take self; explicit _get_or_init() loaders are
                # zero-argument closures/classes (kept for backward compat).
                instance = effective_loader(self) if loader is None else effective_loader()
            except Exception as exc:  # noqa: BLE001 — hard isolation boundary
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                placeholder = FailedSubsystem(name, error=exc, latency_ms=elapsed_ms)
                self._instances[name] = placeholder
                logger.warning("Subsystem '%s' failed to load (%.1f ms): %s: %s",
                               name, elapsed_ms, type(exc).__name__, exc)
                return placeholder
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._load_latency_ms[name] = elapsed_ms
            self._instances[name] = instance
            logger.info("[*] Lazy-loaded module: %s (%.1f ms)", name, elapsed_ms)
            return instance

    def _get_or_init(self, key: str, class_factory: Any) -> Any:
        """Backward-compatible memoized lazy accessor with fault isolation."""
        return self._component(key, loader=class_factory)

    # ── Health / lifecycle / control ─────────────────────────────────────────

    def health_check(self) -> Dict[str, Dict[str, Any]]:
        """Per-subsystem health report. Never raises.

        Ensures every registered subsystem is (re)loaded, reporting one entry
        per subsystem: ``{name, loaded, ok, error, latency_ms}``.
        """
        report: Dict[str, Dict[str, Any]] = {}
        for name in list(_SUBSYSTEMS):
            try:
                instance = self._component(name)
            except Exception as exc:  # belt-and-braces: never raise
                report[name] = {
                    "name": name, "loaded": False, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}", "latency_ms": None,
                }
                continue
            if isinstance(instance, FailedSubsystem):
                report[name] = {
                    "name": name, "loaded": False, "ok": False,
                    "error": instance.msg, "latency_ms": instance.latency_ms,
                }
            else:
                report[name] = {
                    "name": name, "loaded": True, "ok": True,
                    "error": None, "latency_ms": self._load_latency_ms.get(name),
                }
        return report

    def reload(self, reason: str = "manual", eager: bool = False) -> Dict[str, Any]:
        """Drop cached subsystem instances so loaders re-run (lazy by default).

        Records the reload reason (plus a timestamped history entry). With
        ``eager=True``, forces every subsystem to reload immediately and
        returns the resulting health report.
        """
        with self._lock:
            dropped = len(self._instances)
            self._instances.clear()
            self._load_latency_ms = {}
            self._reload_reason = reason
            self._reload_history.append({
                "reason": reason, "timestamp": time.time(), "dropped": dropped,
            })
        logger.info("[KERNEL]: Reloading subsystem cache (reason=%s, dropped=%d)", reason, dropped)
        if eager:
            report = self.health_check()
            ok_count = sum(1 for value in report.values() if value["ok"])
            return {"reason": reason, "dropped": dropped, "loaded": ok_count, "report": report}
        return {"reason": reason, "dropped": dropped}

    @classmethod
    def reset(cls) -> bool:
        """Drop the cached singleton cleanly (module global + class cache)."""
        global _kernel
        _kernel = None
        cls._reset_instance()
        logger.info("[KERNEL]: Singleton reset — next get_nexus_kernel() builds a fresh instance")
        return True

    def get_component_stages(self) -> Dict[str, str]:
        """Map every subsystem to a ``LifecycleStage`` name (read-only).

        Loaded -> ``running``, failed -> ``failed``, dependency-skipped ->
        ``quarantined``, not-yet-accessed -> ``created``. Imports the lifecycle
        constants lazily and degrades to a minimal map if lifecycle is
        unavailable. Lifecycle is NOT wired into the kernel.
        """
        stages = self._lifecycle_stage_names()
        out: Dict[str, str] = {}
        with self._lock:
            for name in _SUBSYSTEMS:
                inst = self._instances.get(name)
                if isinstance(inst, FailedSubsystem):
                    out[name] = stages.get("QUARANTINED" if inst.skipped else "FAILED", "failed")
                elif inst is not None:
                    out[name] = stages.get("RUNNING", "running")
                else:
                    out[name] = stages.get("CREATED", "created")
        return out

    def _lifecycle_stage_names(self) -> Dict[str, str]:
        cache = self._lifecycle_stage_cache
        if cache is not None:
            return cache
        try:
            from lifecycle.supervisor import LifecycleStage
            cache = {stage.name: stage.value for stage in LifecycleStage}
        except Exception:  # lifecycle optional — degrade gracefully
            cache = dict(self._MINIMAL_STAGES)
        self._lifecycle_stage_cache = cache
        return cache

    # ── State persistence ────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Atomically saves the kernel state to disk."""
        state = {
            "kernel_id": self.kernel_id,
            "metrics": {"token_usage": self.token_usage},
            "mesh": self.model_mesh,
            "last_active": time.time()
        }
        temp_path = self._state_path + f".{uuid.uuid4().hex[:8]}.tmp"
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            # Atomic swap
            if os.path.exists(self._state_path):
                old_path = self._state_path + ".old"
                if os.path.exists(old_path): os.remove(old_path)
                os.rename(self._state_path, old_path)
            os.rename(temp_path, self._state_path)
            logger.debug(f"[KERNEL]: State saved to {self._state_path}")
        except Exception as e:
            logger.error(f"Atomic state save failed: {e}")
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to remove temp state file {temp_path}: {e}")

    def _restore_state(self) -> None:
        """Restores kernel state with fallback to legacy snapshots or boots a fresh state file."""
        legacy_paths = sorted(
            glob.glob(os.path.join(self.workspace, "kernel_state*.json")),
            key=os.path.getmtime,
            reverse=True,
        )
        paths_to_try = [self._state_path, self._state_path + ".old"]
        for legacy_path in legacy_paths:
            if legacy_path not in paths_to_try:
                paths_to_try.append(legacy_path)

        for path in paths_to_try:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    self.token_usage = state.get("metrics", {}).get("token_usage", 0)
                    self.model_mesh = state.get("mesh", {})
                    logger.info(f"[KERNEL]: Restored state from {os.path.basename(path)}")
                    if os.path.abspath(path) != os.path.abspath(self._state_path):
                        self._save_state()
                    return
                except Exception as e:
                    logger.error(f"Failed to restore kernel state from {path}: {e}")

        logger.info("[KERNEL]: No prior state file found. Initializing fresh kernel state.")
        self._save_state()

    def get_stats(self) -> Dict[str, Any]:
        """Comprehensive system health and evolution metrics."""
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        return {
            "id": self.kernel_id,
            "version": "21.1-local-agent-runtime",
            "status": "HEALTHY",
            "uptime": int(time.time() - self.start_time),
            "load": {"cpu": f"{cpu}%", "ram": f"{mem}%"},
            "tools": "Ready",
            "research_node": "Configured",
            "token_usage": self.token_usage
        }

    def boot(self) -> bool:
        """Compatibility boot check used by integration tests."""
        os.makedirs(self.workspace, exist_ok=True)
        self._save_state()
        return os.path.isdir(self.workspace)

    # --- Evolution Proxies ---
    def reinforce(self, task_type: str, tool_name: str, delta: float):
        try:
            self.nerve.reinforce(task_type, tool_name, delta)
        except (AttributeError, TypeError):
            logger.warning("kernel/__init__.py:326 suppressed error", exc_info=True)


# Build the public lazy properties from the registered loaders. Each property
# defers to _component(), which provides memoization + fault isolation.
for _name in list(_SUBSYSTEMS):
    def _make_subsystem_property(name: str, loader_fn: Callable) -> property:
        @property
        def subsystem(self) -> Any:  # noqa: N805 — bound property getter
            return self._component(name)
        subsystem.__name__ = name
        doc = getattr(loader_fn, "__doc__", None)
        subsystem.__doc__ = doc or f"Lazily-loaded, fault-isolated subsystem: '{name}'."
        return subsystem

    setattr(NexusKernel, _name, _make_subsystem_property(_name, _SUBSYSTEMS[_name]["loader"]))

del _make_subsystem_property, _name


# --- GLOBAL WRAPPER (For Singleton Access) ---
_kernel = None


def get_nexus_kernel(root_dir: Optional[str] = None) -> NexusKernel:
    global _kernel
    requested_root = os.path.abspath(root_dir) if root_dir else None
    if _kernel is None:
        _kernel = NexusKernel(root_dir=root_dir)
    elif requested_root and os.path.abspath(_kernel.root) != requested_root:
        NexusKernel._reset_instance()
        _kernel = NexusKernel(root_dir=root_dir)
    return _kernel
