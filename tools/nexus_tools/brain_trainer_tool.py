
import os
import subprocess
import sys
from typing import Dict, Any
from tools.nexus_tools.base_tool import BaseTool, ToolResult

class BrainTrainerTool(BaseTool):
    """
    NEXUS BRAIN TRAINER 1.0
    Automates the local-first lifecycle: Train (SafeTensors) -> Export (GGUF) -> Deploy.
    """
    name = "brain_trainer"
    description = (
        "Handles the NEXUS model lifecycle. "
        "Modes: 'train' (Fine-tune SafeTensors), 'export' (Convert to GGUF), 'cycle' (Train + Export)."
    )

    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir

    def call(self, mode: str = "cycle", steps: int = 100) -> ToolResult:
        try:
            results = []
            
            # 1. Training Phase (SafeTensors)
            if mode in ("train", "cycle"):
                trainer_script = os.path.join(self.root, "scripts", "nexus_trainer.py")
                if not os.path.exists(trainer_script):
                    return ToolResult(success=False, error=f"Trainer script not found: {trainer_script}")
                
                results.append("[*] PHASE_1: Initiating SafeTensors Training...")
                # We call the trainer as a subprocess to avoid memory pollution in the main loop
                cmd = [sys.executable, trainer_script]
                process = subprocess.run(cmd, capture_output=True, text=True)
                if process.returncode != 0:
                    return ToolResult(success=False, error=f"Training failed: {process.stderr}")
                results.append(process.stdout[-500:]) # Capture last 500 chars of output

            # 2. Export Phase (GGUF)
            if mode in ("export", "cycle"):
                export_script = os.path.join(self.root, "scripts", "nexus_export_gguf.py")
                if not os.path.exists(export_script):
                    return ToolResult(success=False, error=f"Export script not found: {export_script}")
                
                results.append("[*] PHASE_2: Converting to GGUF (llama.cpp)...")
                cmd = [sys.executable, export_script]
                process = subprocess.run(cmd, capture_output=True, text=True)
                if process.returncode != 0:
                    results.append(f"[!] Export warning: {process.stdout[-200:]}")
                    # We don't fail the whole tool if export fails (might be missing llama.cpp)
                else:
                    results.append("[+] GGUF Export Successful.")

            return ToolResult(success=True, data="\n".join(results))
            
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["train", "export", "cycle"], "description": "Phase of the lifecycle to execute."},
                    "steps": {"type": "integer", "description": "Number of training steps (for 'train' mode)."}
                }
            }
        }
