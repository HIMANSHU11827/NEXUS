"""Background process manager with timeout and kill support."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import subprocess
import time
from typing import Dict, Optional

from sandbox.risk import CommandRiskScorer


@dataclass
class ManagedProcess:
    id: str
    command: str
    pid: int
    started_at: float
    status: str = "running"


class ProcessManager:
    """Tracks long-running local processes."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.processes: Dict[str, subprocess.Popen] = {}
        self.meta: Dict[str, ManagedProcess] = {}
        self.risk = CommandRiskScorer()

    def start(self, command: str, process_id: Optional[str] = None) -> ManagedProcess:
        assessment = self.risk.assess(command)
        if assessment.blocked:
            raise ValueError(f"Blocked unsafe background command: {assessment.summary()}")
        pid = process_id or f"proc_{abs(hash(command + str(time.time()))) % 1000000}"
        proc = subprocess.Popen(command, shell=True, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes[pid] = proc
        meta = ManagedProcess(pid, command, proc.pid, time.time())
        self.meta[pid] = meta
        return meta

    def poll(self, process_id: str) -> Dict[str, object]:
        proc = self.processes.get(process_id)
        meta = self.meta.get(process_id)
        if not proc or not meta:
            return {"status": "missing"}
        code = proc.poll()
        if code is None:
            return {**asdict(meta), "returncode": None}
        stdout, stderr = proc.communicate()
        meta.status = "succeeded" if code == 0 else "failed"
        return {**asdict(meta), "returncode": code, "stdout": stdout[-4000:], "stderr": stderr[-4000:]}

    def kill(self, process_id: str) -> bool:
        proc = self.processes.get(process_id)
        meta = self.meta.get(process_id)
        if not proc:
            return False
        if proc.poll() is None:
            proc.kill()
        if meta:
            meta.status = "killed"
        return True
