import json
import os
import time

from .base_tool import BaseTool, ToolResult
from kernel import get_nexus_kernel

class HiveTool(BaseTool):
    """
    NEXUS HIVE — Collective Signal Broadcasting.
    Allows agents within a hive to share discoveries and results.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_broadcast"
        self.description = (
            "Broadcast a discovery or result to the collective Hive Mind. "
            "Params: 'message' (str), 'hive_id' (opt)."
        )

    def call(self, **kwargs) -> ToolResult:
        message = kwargs.get("message")
        hive_id = kwargs.get("hive_id", "GLOBAL")
        
        if not message:
            return ToolResult(error="Message is required for broadcast.")

        kernel = get_nexus_kernel()
        kernel.hive.broadcast_signal("AGENT", hive_id, message)
        
        return ToolResult(data=f"[HIVE_SENT]: Broadcast to {hive_id} completed.")

class HivePulseTool(BaseTool):
    """
    NEXUS PULSE — Collective Signal Retrieval.
    Retrieves the latest signals from the hive mind.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_pulse"
        self.description = "Retrieves recent signals from the hive. Params: 'hive_id' (opt)."

    def call(self, **kwargs) -> ToolResult:
        hive_id = kwargs.get("hive_id")
        kernel = get_nexus_kernel()
        signals = kernel.hive.get_live_signals(hive_id)
        
        if not signals:
            return ToolResult(data="No signals found in the hive buffer.")
            
        return ToolResult(data="\n".join(signals))

class HiveSpawnTool(BaseTool):
    """
    NEXUS SPAWN — Autonomous Agent Delegation.
    Allows NEXUS to delegate work by queuing a Hive worker.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_spawn"
        self.description = (
            "Delegate a task to a specialized Hive worker. "
            "Params: 'objective' (str), 'persona' (str - e.g. ENGINEER, AUDITOR, or a custom specialist), "
            "'persona_description' (opt), 'hive_id' (opt)."
        )

    def call(self, **kwargs) -> ToolResult:
        objective = kwargs.get("objective")
        persona = kwargs.get("persona", "WORKER")
        persona_description = kwargs.get("persona_description")
        hive_id = kwargs.get("hive_id")
        
        if not objective:
            return ToolResult(error="Objective is required to spawn an agent.")

        kernel = get_nexus_kernel()
        result = kernel.hive.spawn_agent(
            objective,
            persona=persona,
            hive_id=hive_id,
            persona_description=persona_description,
        )
        
        return ToolResult(data=result)

class HiveIntentTool(BaseTool):
    """
    NEXUS INTENT — Collective Purpose Alignment.
    Allows agents to declare an 'Intent' that others can follow or assist with.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_intent"
        self.description = (
            "Declare a collaborative intent (e.g., 'REFACTORING_AUTH', 'DEBUGGING_OOM'). "
            "Other agents will see this intent in their context. "
            "Params: 'intent' (str), 'hive_id' (opt)."
        )

    def call(self, **kwargs) -> ToolResult:
        intent = kwargs.get("intent")
        hive_id = kwargs.get("hive_id", "GLOBAL")
        
        if not intent:
            return ToolResult(error="Intent description is required.")

        kernel = get_nexus_kernel()
        kernel.hive.post_to_blackboard("AGENT", hive_id, f"DECLARE_INTENT: {intent}")
        
        return ToolResult(data=f"[HIVE_INTENT]: Intent '{intent}' broadcasted to {hive_id}.")

class HiveTeamTool(BaseTool):
    """
    NEXUS TEAM — Shared Workspace Collaboration.
    Allows agents to read/write to a shared 'Mission Board' for real-time team coordination.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_team"
        self.description = (
            "Manage the shared Team Mission Board. "
            "Params: 'action' (write/read), 'content' (str), 'hive_id' (opt)."
        )

    def call(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "read")
        content = kwargs.get("content")
        hive_id = kwargs.get("hive_id", "GLOBAL")
        
        kernel = get_nexus_kernel()
        board_path = os.path.join(kernel.hive.logs_dir, f"{hive_id}_mission_board.txt")
        
        if action == "write":
            if not content:
                return ToolResult(error="Content is required to write to the mission board.")
            with open(board_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- TEAM UPDATE [{time.ctime()}] ---\n{content}\n")
            kernel.hive.post_to_blackboard("TEAM", hive_id, f"Updated the Mission Board: {content[:100]}...")
            return ToolResult(data=f"[HIVE_TEAM]: Update posted to {hive_id} mission board.")
        else:
            if not os.path.exists(board_path):
                return ToolResult(data="Mission board is currently empty.")
            with open(board_path, "r", encoding="utf-8") as f:
                data = f.read()
            return ToolResult(data=f"--- {hive_id} MISSION BOARD ---\n{data}")


class HiveMergePlanTool(BaseTool):
    """
    NEXUS MERGE PLAN — conflict-aware consolidation for parallel Hive work.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_merge_plan"
        self.description = (
            "Inspect Hive artifacts for claimed changed files and report overlapping edits. "
            "Params: 'hive_id' (str)."
        )

    def call(self, **kwargs) -> ToolResult:
        hive_id = kwargs.get("hive_id")
        if not hive_id:
            return ToolResult(error="hive_id is required.")

        kernel = get_nexus_kernel()
        plan = kernel.hive.merge_plan(str(hive_id))
        return ToolResult(data=json.dumps(plan, indent=2))

    def is_read_only(self, input_data=None) -> bool:
        return True

    def get_schema(self):
        schema = super().get_schema()
        schema["parameters"] = {
            "type": "object",
            "properties": {"hive_id": {"type": "string"}},
            "required": ["hive_id"],
        }
        return schema


class HiveResumeTool(BaseTool):
    """
    NEXUS RESUME — restart pending or recovered Hive work.
    """

    def __init__(self, root_dir: str):
        self.root = root_dir
        self.name = "hive_resume"
        self.description = "Resume pending tasks for a Hive mission. Params: 'hive_id' (str), 'workers' (int, optional)."

    def call(self, **kwargs) -> ToolResult:
        hive_id = kwargs.get("hive_id")
        if not hive_id:
            return ToolResult(error="hive_id is required.")
        workers = kwargs.get("workers", 2)
        kernel = get_nexus_kernel()
        result = kernel.hive.resume_hive(str(hive_id), workers=int(workers or 2))
        return ToolResult(data=json.dumps(result, indent=2))

    def get_schema(self):
        schema = super().get_schema()
        schema["parameters"] = {
            "type": "object",
            "properties": {
                "hive_id": {"type": "string"},
                "workers": {"type": "integer"},
            },
            "required": ["hive_id"],
        }
        return schema
