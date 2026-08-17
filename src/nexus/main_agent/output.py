"""Output Layer - Multi-modal output generation for NEXUS V5.

This module implements:
- Multi-modal output generation (text, voice, visuals, code)
- Explanation generation
- Confidence scoring
- Alternative suggestions
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class OutputType(str, Enum):
    """Types of output."""
    TEXT = "text"
    VOICE = "voice"
    VISUAL = "visual"
    CODE = "code"
    MULTIMODAL = "multimodal"


@dataclass
class OutputResult:
    """Result of output generation."""
    content: str
    output_type: OutputType
    confidence: float
    explanation: str = ""
    alternatives: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OutputLayer:
    """Output layer for multi-modal response generation."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.logger = logging.getLogger("nexus.v5.output")

    async def generate(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Generate multi-modal output.
        
        Args:
            result: Result from consciousness layer
        
        Returns:
            Dict with generated output
        """
        self.logger.info("Generating output")
        
        # Pre-generated response from the loop takes precedence
        response = result.get("response")
        if isinstance(response, str) and response.strip():
            content = response
            output_type = OutputType.TEXT
        else:
            # Determine output type
            output_type = self._determine_output_type(result)
            
            # Generate main content
            content = await self._generate_content(result, output_type)
        
        # Generate explanation
        explanation = await self._generate_explanation(result)
        
        # Generate alternatives
        alternatives = await self._generate_alternatives(result)
        
        # Calculate confidence
        confidence = result.get("confidence", 0.7)
        
        output_result = OutputResult(
            content=content,
            output_type=output_type,
            confidence=confidence,
            explanation=explanation,
            alternatives=alternatives,
            metadata={"source": "v5_output_layer"}
        )
        
        return {
            "success": True,
            "output": output_result.__dict__,
            "output_type": output_type.value
        }

    def _determine_output_type(self, result: Dict[str, Any]) -> OutputType:
        """Determine appropriate output type."""
        # Check if result suggests specific output type
        if result.get("code_related"):
            return OutputType.CODE
        elif result.get("visual_required"):
            return OutputType.VISUAL
        elif result.get("voice_output"):
            return OutputType.VOICE
        else:
            return OutputType.TEXT

    async def _generate_content(self, result: Dict[str, Any], output_type: OutputType) -> str:
        """Generate main content based on output type."""
        if output_type == OutputType.CODE:
            return self._generate_code_content(result)
        elif output_type == OutputType.VISUAL:
            return self._generate_visual_content(result)
        elif output_type == OutputType.VOICE:
            return self._generate_voice_content(result)
        else:
            return self._generate_text_content(result)

    def _generate_text_content(self, result: Dict[str, Any]) -> str:
        """Generate text content."""
        # Extract main result
        main_result = result.get("result", result.get("processed_result", {}))
        
        if isinstance(main_result, dict):
            # Format dict as text
            return str(main_result)
        elif isinstance(main_result, str):
            return main_result
        else:
            return str(main_result)

    def _generate_code_content(self, result: Dict[str, Any]) -> str:
        """Generate code content."""
        # Extract code from result
        code = result.get("code", result.get("implementation", ""))
        
        if not code:
            return ""
        
        return code

    def _generate_visual_content(self, result: Dict[str, Any]) -> str:
        """Generate visual content description."""
        # Return description of visual
        return f"[VISUAL] {result.get('visual_description', 'Visual representation of result')}"

    def _generate_voice_content(self, result: Dict[str, Any]) -> str:
        """Generate voice content."""
        # Return text that would be spoken
        text = self._generate_text_content(result)
        return f"[VOICE] {text}"

    async def _generate_explanation(self, result: Dict[str, Any]) -> str:
        """Generate explanation of the reasoning."""
        explanation_parts = []
        
        # Add consciousness explanation
        if "mental_state" in result:
            explanation_parts.append(f"Confidence: {result['mental_state'].get('confidence', 0.7):.2f}")
        
        # Add reflection if available
        if "reflection" in result:
            reflection = result["reflection"]
            if reflection.get("success"):
                explanation_parts.append("Task completed successfully")
            else:
                explanation_parts.append(f"Encountered issues: {', '.join(reflection.get('root_causes', []))}")
        
        # Add quantum explanation if applicable
        if "quantum_results" in result:
            explanation_parts.append("Quantum parallel execution used")
        
        # Add swarm explanation if applicable
        if "swarm_result" in result:
            explanation_parts.append(f"Swarm of {result.get('swarm_size', 1)} agents used")
        
        return " | ".join(explanation_parts) if explanation_parts else "Standard execution"

    async def _generate_alternatives(self, result: Dict[str, Any]) -> List[str]:
        """Generate alternative suggestions."""
        alternatives = []
        
        # Add alternative strategies
        if "alternative_plans" in result:
            alternatives.append("Consider alternative execution plans")
        
        # Add swarm alternatives
        if "swarm_size" in result and result["swarm_size"] > 1:
            alternatives.append("Try different swarm topology")
        
        # Add quantum alternatives
        if "quantum_mode" in result:
            alternatives.append("Disable quantum mode for deterministic execution")
        
        # Add consciousness alternatives
        if "consciousness_level" in result:
            alternatives.append("Adjust consciousness level for different processing")
        
        return alternatives[:3]  # Limit to 3 alternatives
