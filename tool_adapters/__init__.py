"""Compatibility adapters over the hardened NEXUS tool registry.

These keep older orchestrators working while ensuring execution flows through
the same risk-scored, rollback-aware tools used by the main loop.
"""

from __future__ import annotations

import os


class RegistryTerminalTool:
    def __init__(self, root: str = ".") -> None:
        self.root = os.path.abspath(root)
        from tools.nexus_tools.bash_tool import BashTool
        from tools.nexus_tools.advanced_power_tool import ProcessTool

        self.bash = BashTool(self.root)
        self.process = ProcessTool(self.root)

    def execute(self, cmd: str) -> str:
        """[SOVEREIGN_EXECUTION]: Routes command through the safety sandbox."""
        from sandbox.sandbox_manager import SovereignSandbox
        sandbox = SovereignSandbox(self.root)
        return sandbox.execute(cmd)

    def execute_stream(self, cmd: str) -> str:
        return self.execute(cmd)

    def spawn(self, cmd: str, pid: str = "") -> str:
        return str(self.process.call(command="start", cmd=cmd, process_id=pid))

    def poll(self, pid: str) -> str:
        return str(self.process.call(command="poll", process_id=pid))


class RegistryFileTools:
    def __init__(self, root: str = ".") -> None:
        self.root = os.path.abspath(root)
        from tools.nexus_tools.file_edit_tool import FileEditTool

        self.editor = FileEditTool(self.root)

    def read_file(self, filename: str) -> str:
        path = self._resolve(filename)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def write_file(self, filename: str, content: str) -> str:
        path = self._resolve(filename)
        if os.path.exists(path):
            result = self.editor.call(
                command="str_replace",
                path=filename,
                old_str=self._read(path),
                new_str=content or "",
            )
        else:
            result = self.editor.call(command="create", path=filename, file_text=content or "")
        return self._legacy_status(result)

    def edit_file(self, filename: str, old: str, new: str) -> str:
        result = self.editor.call(
            command="str_replace",
            path=filename,
            old_str=old,
            new_str=new,
        )
        return self._legacy_status(result)

    def _resolve(self, filename: str) -> str:
        candidate = os.path.abspath(filename if os.path.isabs(filename) else os.path.join(self.root, filename))
        if os.path.commonpath([self.root, candidate]) != self.root:
            raise ValueError(f"Path escapes root: {filename}")
        return candidate

    @staticmethod
    def _legacy_status(result) -> str:
        return f"Success: {result}" if getattr(result, "success", False) else str(result)

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


class RegistryGitTools:
    def __init__(self, root: str = ".") -> None:
        self.root = os.path.abspath(root)
        self.terminal = RegistryTerminalTool(root)

    def execute(self, cmd: str) -> str:
        command = cmd if cmd.strip().startswith("git ") else f"git {cmd}"
        return self.terminal.execute(command)


class RegistryTestTool:
    def __init__(self, root: str = ".") -> None:
        self.root = os.path.abspath(root)
        self.terminal = RegistryTerminalTool(root)

    def run_tests(self, path: str = ".") -> str:
        target = path or "."
        if target.endswith(".py"):
            return self.terminal.execute(f"python {target}")
        return self.terminal.execute(f"python -m unittest discover -s {target}")
