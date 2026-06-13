"""Real-world OS execution control."""

from os_power.rollback import RollbackManager
from os_power.process_manager import ProcessManager
from os_power.patch_ledger import PatchLedger

__all__ = ["RollbackManager", "ProcessManager", "PatchLedger"]
