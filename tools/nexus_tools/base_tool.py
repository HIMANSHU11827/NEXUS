"""Base classes for NEXUS tools."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    success: bool = True
    output: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTool:
    """Base class for all NEXUS tools."""

    name: str = ""
    description: str = ""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = root_dir

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError
