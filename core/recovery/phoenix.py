import os
import shutil
import json
import time
import sys

def restore_system(backup_id=None):
    """
    NEXUS PHOENIX RECOVERY SYSTEM v1.0
    The 'Resurrection Seed' that can rebuild the ecosystem from backups.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    backup_dir = os.path.join(root, "workspace", "backups")
    
    if not os.path.exists(backup_dir):
        print("[PHOENIX_ERROR]: No backup registry found.")
        return

    # Find latest backup if none specified
    if not backup_id:
        backups = sorted([d for d in os.listdir(backup_dir) if os.path.isdir(os.path.join(backup_dir, d))], reverse=True)
        if not backups:
            print("[PHOENIX_ERROR]: No valid backups detected.")
            return
        backup_id = backups[0]

    target_backup = os.path.join(backup_dir, backup_id)
    print(f"[PHOENIX_INIT]: Attempting resurrection from {backup_id}...")

    # Restore core files
    core_files = ["core", "orchestrators", "tools", "nexus.py", "configs"]
    for folder in core_files:
        src = os.path.join(target_backup, folder)
        dest = os.path.join(root, folder)
        if os.path.exists(src):
            if os.path.isdir(src):
                if os.path.exists(dest): shutil.rmtree(dest)
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            print(f"[PHOENIX_SYNC]: Restored {folder}")

    print("[PHOENIX_COMPLETE]: System Resurrection successful. Rebooting Kernel...")

if __name__ == "__main__":
    # Can be run directly: python core/recovery/phoenix.py [backup_id]
    bid = sys.argv[1] if len(sys.argv) > 1 else None
    restore_system(bid)
