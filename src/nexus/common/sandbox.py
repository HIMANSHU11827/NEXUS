import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple


class NexusSandbox:
    """
    NEXUS SOVEREIGN SANDBOX v1.0
    Provides an isolated 'Shadow Workspace' for executing risky code.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.sandbox_base = os.path.join(self.root, ".nexus", "workspace", "sandboxes")
        os.makedirs(self.sandbox_base, exist_ok=True)

    def execute(self, command: str, files_to_mount: Optional[list] = None) -> Tuple[int, str, str]:
        """
        Executes a command in a fresh temporary directory.
        Clones specified files into the sandbox before execution.
        """
        with tempfile.TemporaryDirectory(dir=self.sandbox_base) as tmp_dir:
            # 1. Mount Phase
            if files_to_mount:
                for f in files_to_mount:
                    src = os.path.join(self.root, f)
                    if os.path.exists(src):
                        dest = os.path.join(tmp_dir, f)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        if os.path.isdir(src):
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dest)

            # 2. Execution Phase
            try:
                env = os.environ.copy()
                env["NEXUS_SANDBOX"] = "1"
                
                cmd_list = command if isinstance(command, list) else ["cmd.exe", "/c", command]
                proc = subprocess.run(
                    cmd_list,
                    shell=False,
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env
                )
                return proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired:
                return -1, "", "[SANDBOX_TIMEOUT]: Execution exceeded safety limits."
            except Exception as e:
                return -1, "", f"[SANDBOX_ERROR]: {str(e)}"
