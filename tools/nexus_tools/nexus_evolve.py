from .base_tool import BaseTool, ToolResult
import os
import json
import time
from typing import Dict, Any

class NexusEvolveTool(BaseTool):
    """
    NEXUS EVOLVE — THE SELF-MODIFICATION KERNEL.
    Allows the agent to analyze its own telemetry and propose/apply code patches to itself.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "nexus_evolve"
        self.description = (
            "Analyzes telemetry and applies self-improvements. "
            "Params: 'mode' (analyze|apply), 'patch' (if apply). "
            "Use this to solve recurring tool failures by editing task logic."
        )

    def call(self, **kwargs) -> ToolResult:
        mode = kwargs.get("mode", "analyze")
        
        # ── 1. Telemetry Analysis Phase ──
        if mode == "analyze":
            from core.telemetry.database import NexusTelemetryDB
            db = NexusTelemetryDB()
            failures = db.get_recent_failures(limit=10)
            
            summary = f"Found {len(failures)} recent systemic failures.\n\n"
            if failures:
                summary += "🧠 [EVOLVE_DIAGNOSTIC]:\n"
                
                # Categorization heuristic
                improve = [f for f in failures if f['tool_name'] in ('bash', 'file_edit')]
                adapt = [f for f in failures if f['tool_name'] in ('rag', 'lsp', 'atlas_map')]
                upgrade = [f for f in failures if f['duration'] > 10.0]

                if improve: summary += f"-   **IMPROVEMENT NEEDED**: {len(improve)} tool execution errors found. Fix the scripts.\n"
                if adapt: summary += f"-   **ADAPTATION NEEDED**: {len(adapt)} search/precision issues found. Adjust your context mapping.\n"
                if upgrade: summary += f"-   **UPGRADE NEEDED**: {len(upgrade)} high-latency/timeout events found. Architect new tools.\n"

                summary += "\nRecent failure patterns:\n" + json.dumps(failures[:3], indent=2)
            else:
                summary += "System operating within normal parameters. No failures recorded."
            return ToolResult(data=summary)

        elif mode in ("apply", "improve", "adapt", "upgrade"):
            # [EVOLVE PHASE 2]: Surgical Self-Modification
            # The agent proposes a 'file_path', 'old_text', and 'new_text'.
            evolution_type = mode.upper()
            path = kwargs.get("path")
            old = kwargs.get("old_text")
            new = kwargs.get("new_text")

            if not (path and old and new):
                return ToolResult(error="Missing required params (path, old_text, new_text) for apply.")

            from tools.nexus_tools.registry import ToolRegistry
            registry = ToolRegistry()
            res = registry.execute("file_edit", path=path, old=old, new=new)
            
            # Auto-update Atlas index for the modified file
            from rag.atlas.engine import NexusAtlasEngine
            atlas = NexusAtlasEngine(self.root)
            atlas.refresh_index()

            return ToolResult(data=f"[{evolution_type}_SUCCESS]: Applied patch to {path}.\n[RAG_SYNC]: Atlas updated.")

        return ToolResult(error=f"Unknown mode: {mode}")

    def is_read_only(self, input_data: Dict[str, Any] = None) -> bool:
        return input_data.get("mode") == "analyze"
