"""Real-world OS execution control."""

from core.os_power.rollback import RollbackManager
from core.os_power.process_manager import ProcessManager
from core.os_power.patch_ledger import PatchLedger

__all__ = ["RollbackManager", "ProcessManager", "PatchLedger"]
