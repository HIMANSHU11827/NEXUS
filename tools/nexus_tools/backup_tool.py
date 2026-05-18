import os
import shutil
import time
from .base_tool import BaseTool, ToolResult

class BackupTool(BaseTool):
    """
    NEXUS BACKUP — Evolutionary Snapshotting.
    Creates a full system state snapshot for the Phoenix Recovery system.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "system_snapshot"
        self.description = "Creates a full system backup for emergency recovery. Params: 'label' (str)."
        self.backup_base = os.path.join(self.root, "workspace", "backups")
        os.makedirs(self.backup_base, exist_ok=True)

    def call(self, **kwargs) -> ToolResult:
        label = kwargs.get("label", "auto_evolution")
        ts = int(time.time())
        backup_id = f"{ts}_{label}"
        target_dir = os.path.join(self.backup_base, backup_id)
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            
            # Critical Core components
            to_save = ["core", "orchestrators", "tools", "nexus.py", "configs", "manifest.json"]
            for item in to_save:
                src = os.path.join(self.root, item)
                dest = os.path.join(target_dir, item)
                if os.path.exists(src):
                    if os.path.isdir(src):
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)
            
            return ToolResult(data=f"[BACKUP_SUCCESS]: System snapshot '{backup_id}' created.")
        except Exception as e:
            return ToolResult(error=str(e))
