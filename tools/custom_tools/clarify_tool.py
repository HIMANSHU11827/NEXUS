"""
NEXUS CLARIFY TOOL — Ask user questions when you need clarification
Like Hermes clarify: presents choices for the user to pick or type free-form.
"""
from typing import Any, Dict, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ClarifyTool(BaseTool):
    """Ask the user a question when you need clarification, feedback, or a decision."""
    name = "clarify"
    description = "Ask the user a question when you need clarification, feedback, or a decision before proceeding. Presents up to 4 choices or open-ended questions."
    aliases = ["ask_user", "question", "confirm"]

    def call(self, question: str = "", choices: List[str] = None) -> ToolResult:
        if not question:
            return ToolResult(error="question is required")
        
        output = f"\n⚠️  [CLARIFY] {question}\n"
        if choices:
            output += "\nOptions:\n"
            for i, choice in enumerate(choices, 1):
                output += f"  {i}. {choice}\n"
            output += "  (or type your own answer)\n"
        
        # NEXUS will present this to the user and wait for their response
        return ToolResult(data=output + "\n[AWAITING_USER_INPUT]")

    def is_read_only(self, input_data=None):
        return True

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user."},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 120},
                        "maxItems": 4,
                        "description": "Up to 4 answer choices. User can pick or type their own.",
                    },
                },
                "required": ["question"],
            },
        }
