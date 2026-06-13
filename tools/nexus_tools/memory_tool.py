from tools.nexus_tools.base_tool import BaseTool, ToolResult
from neural.memory_kernel import MemoryKernel
import os

class MemoryTool(BaseTool):
    """
    NEXUS COGNITIVE MEMORY TOOL (v1.0)
    Gives the agent sovereign control over its own Working and Episodic memory.
    """
    name = "memory_ops"
    description = "Manage working memory (Mental Notes) and episodic recall (Mental Time Travel)."
    
    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.kernel = MemoryKernel(root_dir)

    def call(self, operation: str, key: str = None, value: str = None, session_id: str = "default", limit: int = 5) -> ToolResult:
        try:
            if operation == "ram_store":
                if not key or not value: return ToolResult(error="Key and value required for ram_store.")
                self.kernel.ram_store(key, value)
                return ToolResult(data=f"Stored '{key}' in working memory.")
                
            elif operation == "ram_recall":
                if not key: return ToolResult(error="Key required for ram_recall.")
                val = self.kernel.ram_recall(key)
                return ToolResult(data=str(val) if val else "Key not found in RAM.")
                
            elif operation == "episodic_list":
                episodes = self.kernel.list_episodes(session_id, limit)
                res = "### [RECENT_EPISODES]:\n"
                for ep in episodes:
                    res += f"- {ep['episode_id']} | {ep['title']}: {ep['summary']}\n"
                return ToolResult(data=res)
                
            elif operation == "learn_fact":
                if not key or not value: return ToolResult(error="Entity (key) and Fact (value) required.")
                # Basic parsing for entity.attribute
                parts = key.split(".")
                entity = parts[0]
                attr = parts[1] if len(parts) > 1 else "general"
                self.kernel.store_fact(entity, attr, value)
                return ToolResult(data=f"Learned fact about {entity}.")
                
            else:
                return ToolResult(error=f"Unknown memory operation: {operation}")
                
        except Exception as e:
            return ToolResult(error=f"Memory Operation Error: {str(e)}")

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["ram_store", "ram_recall", "episodic_list", "learn_fact"],
                        "description": "The memory action to perform."
                    },
                    "key": {"type": "string", "description": "Key for RAM or Entity for Fact learning."},
                    "value": {"type": "string", "description": "Content to store."},
                    "session_id": {"type": "string", "description": "Session to recall episodes from."},
                    "limit": {"type": "integer", "description": "Number of episodes to list."}
                },
                "required": ["operation"]
            }
        }
