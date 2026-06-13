import os
import base64
import logging
from typing import Dict, Any, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("NEXUS_VISION")

class NexusVisionTool(BaseTool):
    """
    NEXUS VISION ENGINE 1.0
    Provides multi-modal grounding for screenshots, UI layouts, and diagrams.
    Supports local vision models (via LM Studio/Ollama) or cloud providers.
    """
    name = "vision_grounding"
    description = "Analyzes images/screenshots to provide visual grounding for UI, layouts, or diagrams."

    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir

    def call(self, path: str, prompt: str = "Describe this image in detail for an engineering context.") -> ToolResult:
        """
        [MULTI-MODAL_GROUNDING]: Encodes image and routes to a vision-capable brain tier.
        """
        abs_path = os.path.join(self.root, path) if not os.path.isabs(path) else path
        if not os.path.exists(abs_path):
            return ToolResult(success=False, error=f"Image not found at {abs_path}")

        try:
            # 1. Encode image to base64
            with open(abs_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

            # 2. Delegate to the brain's multi-modal capability
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel()
            
            # Construct multi-modal payload
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"}
                        }
                    ]
                }
            ]
            
            # Vision usually requires 'smart' or 'heavy' tier
            response = kernel.moe.generate(messages=messages, mode="smart")
            
            return ToolResult(success=True, data=response)

        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return ToolResult(success=False, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Local path to the image/screenshot file."},
                    "prompt": {"type": "string", "description": "Specific question or instruction for the vision analysis."}
                },
                "required": ["path"]
            }
        }
