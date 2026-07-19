"""NEXUS kernel: shared runtime services for tools, providers, memory, and telemetry."""

import glob
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

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
        self._lock = threading.RLock()

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
        try:
            from config.config_loader import NexusConfigLoader
        except ImportError:
            logger.warning("Subsystem 'config' not available")
            return {}
        return self._get_or_init("config", NexusConfigLoader)

    @property
    def moe(self):
        try:
            from intelligence.moe_router import NexusMoERouter
        except ImportError:
            logger.warning("Subsystem 'moe' not available")
            return {}
        return self._get_or_init("moe", NexusMoERouter)

    @property
    def moa(self):
        try:
            from intelligence.moa import MixtureOfArchitects
        except ImportError:
            logger.warning("Subsystem 'moa' not available")
            return {}
        return self._get_or_init("moa", lambda: MixtureOfArchitects(self.moe.base_router))

    @property
    def nerve(self):
        try:
            from neural.nerve_center import NexusNerveCenter
        except ImportError:
            logger.warning("Subsystem 'nerve' not available")
            return {}
        return self._get_or_init("nerve", lambda: NexusNerveCenter(self.root))

    @property
    def omni(self):
        try:
            from evolution.omni_kernel import OmniEvolutionKernel
        except ImportError:
            logger.warning("Subsystem 'omni' not available")
            return {}
        return self._get_or_init("omni", lambda: OmniEvolutionKernel(self.root))

    @property
    def hyper(self):
        try:
            from evolution.hyper_kernel import HyperKernel
        except ImportError:
            logger.warning("Subsystem 'hyper' not available")
            return {}
        return self._get_or_init("hyper", lambda: HyperKernel(self.root))

    @property
    def researcher(self):
        try:
            from evolution.researcher import NexusResearcher
        except ImportError:
            logger.warning("Subsystem 'researcher' not available")
            return {}
        return self._get_or_init("researcher", lambda: NexusResearcher(self.root))

    @property
    def persistence(self):
        try:
            from context.persistence import NexusFilePersistence
        except ImportError:
            logger.warning("Subsystem 'persistence' not available")
            return {}
        return self._get_or_init("persistence", lambda: NexusFilePersistence(self.root))

    @property
    def hal(self):
        try:
            from hardware.manager import NexusHardwareManager
        except ImportError:
            logger.warning("Subsystem 'hal' not available")
            return {}
        return self._get_or_init("hal", NexusHardwareManager)

    @property
    def horizons(self):
        try:
            from evolution.horizons import StrategicHorizons
        except ImportError:
            logger.warning("Subsystem 'horizons' not available")
            return {}
        return self._get_or_init("horizons", lambda: StrategicHorizons(self.root))

    @property
    def local_brain(self):
        try:
            from intelligence.local_brain import NexusLocalBrain
        except ImportError:
            logger.warning("Subsystem 'local_brain' not available")
            return {}
        return self._get_or_init("local_brain", lambda: NexusLocalBrain(self.root))

    @property
    def trainer(self):
        try:
            from neural.trainer import NexusTrainer
        except ImportError:
            logger.warning("Subsystem 'trainer' not available")
            return {}
        return self._get_or_init("trainer", lambda: NexusTrainer(self.root))

    @property
    def indexer(self):
        try:
            from indexer import NexusSemanticIndexer
        except ImportError:
            logger.warning("Subsystem 'indexer' not available")
            return {}
        return self._get_or_init("indexer", lambda: NexusSemanticIndexer(self.root))

    @property
    def intent(self):
        try:
            from evolution.intent.scripts.engine import NexusIntentEngine
        except ImportError:
            logger.warning("Subsystem 'intent' not available")
            return {}
        return self._get_or_init("intent", NexusIntentEngine)

    @property
    def prover(self):
        try:
            from safety.prover import LogicProver
        except ImportError:
            logger.warning("Subsystem 'prover' not available")
            return {}
        return self._get_or_init("prover", lambda: LogicProver(strictness=0.9))

    @property
    def tools(self):
        try:
            from tools.nexus_tools.registry import ToolRegistry
        except ImportError:
            logger.warning("Subsystem 'tools' not available")
            return {}
        return self._get_or_init("tools", lambda: ToolRegistry(self.root))

    @property
    def telemetry(self):
        try:
            from telemetry.database import NexusTelemetryDB
        except ImportError:
            logger.warning("Subsystem 'telemetry' not available")
            return {}
        return self._get_or_init("telemetry", NexusTelemetryDB)

    @property
    def rag(self):
        try:
            from rag.engine import NexusAtlasRAG
        except ImportError:
            logger.warning("Subsystem 'rag' not available")
            return {}
        return self._get_or_init("rag", NexusAtlasRAG)

    @property
    def hive(self):
        try:
            from hive.engine import NexusHiveEngine
        except ImportError:
            logger.warning("Subsystem 'hive' not available")
            return {}
        return self._get_or_init("hive", lambda: NexusHiveEngine(self.root))

    @property
    def plugins(self):
        try:
            from plugins.manager import PluginManager
        except ImportError:
            logger.warning("Subsystem 'plugins' not available")
            return {}
        return self._get_or_init("plugins", lambda: PluginManager(self.root))

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
