"""NEXUS kernel: shared runtime services for tools, providers, memory, and telemetry."""

import os
import json
import time
import uuid
import logging
import threading
import glob
from typing import List, Dict, Any, Optional
import psutil
from core.nexus_compat import import_requests, s, safe_round, itail
from utils.singleton import ThreadSafeSingleton

_requests: Any = import_requests()
logger = logging.getLogger("NEXUS_KERNEL")

class NexusKernel(ThreadSafeSingleton):
    """
    Shared core runtime.
    Lazily owns configuration, provider routing, tools, RAG, memory, and telemetry.
    """

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
        self._lock = threading.Lock()

        # ── 4. Boot Sequence ──
        logger.info(f"--- NEXUS KERNEL active (ID: {s(self.kernel_id, 4)}) ---")
        self._restore_state()

    def _get_or_init(self, key: str, class_factory: Any) -> Any:
        with self._lock:
            if key not in self._instances:
                logger.info(f"[*] Lazy-loading module: {key}...")
                self._instances[key] = class_factory()
            return self._instances[key]

    @property
    def config(self):
        from core.config_loader import NexusConfigLoader
        return self._get_or_init("config", NexusConfigLoader)

    @property
    def moe(self):
        from core.intelligence.moe_router import NexusMoERouter
        return self._get_or_init("moe", NexusMoERouter)

    @property
    def moa(self):
        from core.intelligence.moa import MixtureOfArchitects
        return self._get_or_init("moa", lambda: MixtureOfArchitects(self.moe.base_router))

    @property
    def nerve(self):
        from core.neural.nerve_center import NexusNerveCenter
        return self._get_or_init("nerve", lambda: NexusNerveCenter(self.root))

    @property
    def omni(self):
        from core.evolution.omni_kernel import OmniEvolutionKernel
        return self._get_or_init("omni", lambda: OmniEvolutionKernel(self.root))

    @property
    def hyper(self):
        from core.evolution.hyper_kernel import HyperKernel
        return self._get_or_init("hyper", lambda: HyperKernel(self.root))

    @property
    def researcher(self):
        from core.evolution.researcher import NexusResearcher
        return self._get_or_init("researcher", lambda: NexusResearcher(self.root))

    @property
    def persistence(self):
        from core.context.persistence import NexusFilePersistence
        return self._get_or_init("persistence", lambda: NexusFilePersistence(self.root))

    @property
    def hal(self):
        from core.hardware.manager import NexusHardwareManager
        return self._get_or_init("hal", NexusHardwareManager)

    @property
    def horizons(self):
        from core.evolution.horizons import StrategicHorizons
        return self._get_or_init("horizons", lambda: StrategicHorizons(self.root))

    @property
    def local_brain(self):
        from core.intelligence.local_brain import NexusLocalBrain
        return self._get_or_init("local_brain", lambda: NexusLocalBrain(self.root))

    @property
    def trainer(self):
        from core.neural.trainer import NexusTrainer
        return self._get_or_init("trainer", lambda: NexusTrainer(self.root))

    @property
    def indexer(self):
        from core.indexer import NexusSemanticIndexer
        return self._get_or_init("indexer", lambda: NexusSemanticIndexer(self.root))

    @property
    def intent(self):
        from core.evolution.intent_engine import NexusIntentEngine
        return self._get_or_init("intent", NexusIntentEngine)

    @property
    def prover(self):
        from core.safety.prover import LogicProver
        return self._get_or_init("prover", lambda: LogicProver(strictness=0.9))

    @property
    def tools(self):
        from tools.nexus_tools.registry import ToolRegistry
        return self._get_or_init("tools", ToolRegistry)

    @property
    def telemetry(self):
        from core.telemetry.database import NexusTelemetryDB
        return self._get_or_init("telemetry", NexusTelemetryDB)

    @property
    def rag(self):
        from rag.engine import NexusAtlasRAG
        return self._get_or_init("rag", NexusAtlasRAG)

    @property
    def hive(self):
        from core.hive import NexusHiveEngine
        return self._get_or_init("hive", lambda: NexusHiveEngine(self.root))

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
                except: pass

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
        self.nerve.reinforce(task_type, tool_name, delta)

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
