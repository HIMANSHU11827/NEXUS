from tools.nexus_tools.base_tool import BaseTool, ToolResult
import yaml
import os

class BrainSwitchTool(BaseTool):
    """
    NEURAL TOGGLE 1.0: Manually switch between Local (NEXUS) and High-Fidelity (Big Brain).
    """
    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir
        self.config_path = os.path.join(self.root, "configs", "nexus_config.yaml")

    @property
    def name(self) -> str:
        return "nexus_switch_brain"

    @property
    def description(self) -> str:
        return "Switches the primary cognition engine. Use 'nexus' for local brain or 'big' for cloud/teacher brain."

    def call(self, target: str) -> ToolResult:
        if target.lower() not in ["nexus", "local", "big", "cloud"]:
            return ToolResult(success=False, message="Invalid target. Use 'nexus' or 'big'.")

        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)

            if target.lower() in ["nexus", "local"]:
                config["system"]["default_provider"] = "local"
                msg = "[+] SYNAPTIC SHIFT: NEXUS Sovereign Brain (Local) is now Active."
            else:
                config["system"]["default_provider"] = "cloud"
                msg = "[+] SYNAPTIC SHIFT: Master Architect Brain (Big Brain) is now Active."

            with open(self.config_path, "w") as f:
                yaml.safe_dump(config, f)

            return ToolResult(success=True, message=msg)
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to switch brain: {e}")
