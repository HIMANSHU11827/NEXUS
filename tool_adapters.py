"""NEXUS Tool Adapters — wraps tools for use by orchestrator."""

import os


class RegistryFileTools:
    """File operation tools via ToolRegistry."""
    def __init__(self, root_dir: str):
        self.root = root_dir

    def write_file(self, path: str, content: str) -> str:
        full_path = os.path.join(self.root, path) if not os.path.isabs(path) else path
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"SUCCESS: wrote {full_path}"

    def read_file(self, path: str) -> str:
        full_path = os.path.join(self.root, path) if not os.path.isabs(path) else path
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()


class RegistryGitTools:
    """Git operation tools via ToolRegistry."""
    def __init__(self, root_dir: str):
        self.root = root_dir


class RegistryTerminalTool:
    """Terminal tool via ToolRegistry."""
    def __init__(self, root_dir: str):
        self.root = root_dir


class RegistryTestTool:
    """Test tool via ToolRegistry."""
    def __init__(self, root_dir: str):
        self.root = root_dir
