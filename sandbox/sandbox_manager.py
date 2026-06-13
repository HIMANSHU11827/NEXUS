import os
import subprocess
import logging
from typing import Dict, Any, List, Optional
from enum import Enum
from sandbox.risk import CommandRiskScorer

logger = logging.getLogger("NEXUS_SANDBOX")

class SandboxTier(Enum):
    NO_SANDBOX = "no_sandbox"  # Direct execution (Default)
    NORMAL = "normal"          # Restricted shell isolation
    DOCKER = "docker"          # Full container isolation

class SovereignSandbox:
    """
    NEXUS SOVEREIGN SANDBOX 2.0
    Implements 2-tier security (No-Sandbox vs Sandbox) with multiple isolation backends.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.risk_scorer = CommandRiskScorer()
        
        # ⚡ [DEFAULT_TIER]: Set to No-Sandbox as requested
        tier_env = os.environ.get("NEXUS_SANDBOX_TIER", "no_sandbox").lower()
        try:
            self.tier = SandboxTier(tier_env)
        except ValueError:
            self.tier = SandboxTier.NO_SANDBOX

    def execute(self, command: str, workdir: Optional[str] = None) -> str:
        """
        [SOVEREIGN_EXECUTION]: Routes command through the selected security tier.
        """
        # 1. NO_SANDBOX: Direct execution
        if self.tier == SandboxTier.NO_SANDBOX:
            return self._execute_direct(command, workdir or self.root)

        # 2. SANDBOXED: Perform risk assessment first
        assessment = self.risk_scorer.assess(command)
        if assessment.blocked:
            return f"[SANDBOX_BLOCK]: Command blocked due to critical risk: {assessment.summary()}"

        target_dir = workdir if workdir else self.root
        
        # 3. NORMAL: Restricted Shell
        if self.tier == SandboxTier.NORMAL:
            return self._execute_restricted(command, target_dir)
            
        # 4. DOCKER: Container Isolation
        if self.tier == SandboxTier.DOCKER:
            return self._execute_docker(command, target_dir)

        return "[SANDBOX_ERROR]: Invalid sandbox configuration."

    def _execute_direct(self, command: str, workdir: str) -> str:
        """Direct execution without isolation (Default)."""
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=600 # 10 minute direct limit
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except Exception as e:
            return f"[EXECUTION_ERROR]: {str(e)}"

    def _execute_restricted(self, command: str, workdir: str) -> str:
        """Restricted shell isolation."""
        try:
            safe_env = {
                "PATH": os.environ.get("PATH", ""),
                "NEXUS_ROOT": self.root,
                "USER": "nexus_worker"
            }
            process = subprocess.run(
                command,
                shell=True,
                cwd=workdir,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=300 # 5 minute restricted limit
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return "[SANDBOX_TIMEOUT]: Restricted execution exceeded safety limit."
        except Exception as e:
            return f"[SANDBOX_ERROR]: {str(e)}"

    def _execute_docker(self, command: str, workdir: str) -> str:
        """Containerized isolation via Docker."""
        try:
            # Check if docker daemon is running
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=True,
                timeout=5
            )
        except Exception:
            logger.warning("Docker daemon not available. Falling back to restricted Normal sandbox.")
            return self._execute_restricted(command, workdir)
        
        try:
            rel_workdir = os.path.relpath(workdir, self.root).replace("\\", "/")
            container_workdir = f"/workspace/{rel_workdir}" if rel_workdir != "." else "/workspace"
            
            # Map Windows path format or posix format to container volume mount
            docker_cmd = [
                "docker", "run", "--rm",
                "-v", f"{self.root}:/workspace",
                "-w", container_workdir,
                "nexus-worker",
                "sh", "-c", command
            ]
            
            process = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=300 # 5 minutes container limit
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return "[SANDBOX_TIMEOUT]: Docker execution exceeded container safety limits."
        except Exception as e:
            return f"[SANDBOX_ERROR]: Docker runtime error: {str(e)}"
