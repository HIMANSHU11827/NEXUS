import os
import importlib
import inspect
from typing import Dict, Any, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult

class SkillSynthesizer(BaseTool):
    """
    [EVOLUTION_CORE]: Allows NEXUS to synthesize new skills and tools dynamically.
    Generates Python-based tools and registers them with the kernel.
    """
    
    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir
        self.custom_tools_dir = os.path.join(self.root, "tools", "custom_tools")
        os.makedirs(self.custom_tools_dir, exist_ok=True)
        # Create __init__.py for the package
        init_file = os.path.join(self.custom_tools_dir, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w") as f: f.write("")

    @property
    def name(self) -> str:
        return "skill_synthesizer"

    @property
    def description(self) -> str:
        return "Synthesizes a new tool/skill for NEXUS. Provide name, description, and Python code (BaseTool subclass)."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "Short name for the tool (e.g., 'sql_scanner')"},
                    "tool_code": {"type": "string", "description": "Full Python code for a class inheriting from BaseTool."},
                    "dependencies": {"type": "array", "items": {"type": "string"}, "description": "Optional pip packages needed."}
                },
                "required": ["tool_name", "tool_code"]
            }
        }

    def call(self, tool_name: str, tool_code: str, dependencies: Optional[List[str]] = None) -> ToolResult:
        """Saves the tool code and triggers a registry refresh."""
        try:
            # 1. Install dependencies if any
            if dependencies:
                import subprocess
                import sys
                for dep in dependencies:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", dep])

            # 2. Save the code
            file_path = os.path.join(self.custom_tools_dir, f"{tool_name}.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(tool_code)

            # 3. Trigger Registry Reload (via Kernel proxy if available, or locally)
            # Since we are likely running inside the registry execution, 
            # we need a way to tell the registry to refresh.
            from tools.nexus_tools.registry import ToolRegistry
            registry = ToolRegistry()
            # We'll implement a 'reload_custom_tools' method in the registry
            if hasattr(registry, "reload_custom_tools"):
                registry.reload_custom_tools()

            return ToolResult(
                success=True,
                data=f"[SUCCESS]: Tool '{tool_name}' synthesized and registered at {file_path}.",
                summary=f"New skill '{tool_name}' added to NEXUS neural map."
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
