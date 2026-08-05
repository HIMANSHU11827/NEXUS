"""Consciousness Layer - Self-awareness and metacognition for NEXUS V5.

This module implements:
- Self-awareness (knows own capabilities and limits)
- Metacognition (monitors own cognitive processes)
- Theory of mind (understands other agents' mental states)
- Introspection (examines own internal state)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ConsciousnessLevel(str, Enum):
    """Levels of consciousness."""
    BASIC = "basic"  # 0-3: Basic state tracking
    AWARE = "aware"  # 4-6: Self-awareness
    REFLECTIVE = "reflective"  # 7-8: Metacognition
    CONSCIOUS = "conscious"  # 9-10: Full consciousness with theory of mind


@dataclass
class SelfModel:
    """Model of self (capabilities, limits, knowledge)."""
    capabilities: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    knowledge_domains: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.7
    performance_history: List[float] = field(default_factory=list)


@dataclass
class MentalState:
    """Current mental state of the agent."""
    cognitive_load: float = 0.5
    focus_level: float = 0.8
    confidence: float = 0.7
    uncertainty: float = 0.3
    emotional_state: str = "neutral"


@dataclass
class TheoryOfMindModel:
    """Model of other agents' mental states."""
    agent_models: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ConsciousnessLayer:
    """Consciousness layer for self-awareness and metacognition."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.logger = logging.getLogger("nexus.v5.consciousness")
        self.self_model = SelfModel()
        self.mental_state = MentalState()
        self.theory_of_mind = TheoryOfMindModel()
        self.introspection_history: List[Dict[str, Any]] = []

    async def process(self, result: Dict[str, Any], consciousness_level: int = 1) -> Dict[str, Any]:
        """Process result through consciousness layer.
        
        Args:
            result: Result from previous layer
            consciousness_level: Level of consciousness (0-10)
        
        Returns:
            Dict with consciousness-processed results
        """
        self.logger.info(f"Processing with consciousness level {consciousness_level}")
        
        # Determine consciousness level
        level = self._get_consciousness_level(consciousness_level)
        
        # Apply consciousness based on level
        if level == ConsciousnessLevel.BASIC:
            processed = await self._basic_awareness(result)
        elif level == ConsciousnessLevel.AWARE:
            processed = await self._self_awareness(result)
        elif level == ConsciousnessLevel.REFLECTIVE:
            processed = await self._metacognition(result)
        elif level == ConsciousnessLevel.CONSCIOUS:
            processed = await self._full_consciousness(result)
        else:
            processed = result
        
        return {
            "success": True,
            "processed_result": processed,
            "consciousness_level": level.value,
            "mental_state": self.mental_state.__dict__
        }

    def _get_consciousness_level(self, level: int) -> ConsciousnessLevel:
        """Map numeric level to enum."""
        if level <= 3:
            return ConsciousnessLevel.BASIC
        elif level <= 6:
            return ConsciousnessLevel.AWARE
        elif level <= 8:
            return ConsciousnessLevel.REFLECTIVE
        else:
            return ConsciousnessLevel.CONSCIOUS

    async def _basic_awareness(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Basic awareness - simple state tracking."""
        self.logger.debug("Applying basic awareness")
        
        # Update mental state
        self.mental_state.confidence = result.get("confidence", 0.7)
        self.mental_state.uncertainty = 1.0 - self.mental_state.confidence
        
        return result

    async def _self_awareness(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Self-awareness - knows own capabilities and limits."""
        self.logger.debug("Applying self-awareness")
        
        # Update self model
        self._update_self_model(result)
        
        # Check if task is within capabilities
        task_feasible = self._assess_task_feasibility(result)
        
        # Adjust result based on self-awareness
        if not task_feasible:
            result["self_awareness_note"] = "Task may exceed current capabilities"
        
        return result

    async def _metacognition(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Metacognition - monitors own cognitive processes."""
        self.logger.debug("Applying metacognition")
        
        # Monitor cognitive load
        self.mental_state.cognitive_load = self._estimate_cognitive_load(result)
        
        # Monitor focus level
        self.mental_state.focus_level = self._estimate_focus_level(result)
        
        # Perform introspection
        introspection = await self._introspect()
        
        # Adjust based on metacognition
        if self.mental_state.cognitive_load > 0.8:
            result["metacognition_note"] = "High cognitive load detected"
            result["suggestion"] = "Consider breaking down task"
        
        return result

    async def _full_consciousness(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Full consciousness with theory of mind."""
        self.logger.debug("Applying full consciousness")
        
        # Apply all lower levels
        result = await self._self_awareness(result)
        result = await self._metacognition(result)
        
        # Apply theory of mind
        tom_result = await self._apply_theory_of_mind(result)
        
        # Deep introspection
        deep_introspection = await self._deep_introspect()
        
        result["theory_of_mind"] = tom_result
        result["deep_introspection"] = deep_introspection
        
        return result

    def _update_self_model(self, result: Dict[str, Any]):
        """Update self model based on result."""
        # Add capabilities based on successful actions
        if result.get("success"):
            action_type = result.get("action_type", "general")
            if action_type not in self.self_model.capabilities:
                self.self_model.capabilities.append(action_type)
        
        # Track performance
        confidence = result.get("confidence", 0.5)
        self.self_model.performance_history.append(confidence)
        
        # Keep only recent performance
        if len(self.self_model.performance_history) > 100:
            self.self_model.performance_history.pop(0)

    def _assess_task_feasibility(self, result: Dict[str, Any]) -> bool:
        """Assess if task is within capabilities."""
        # Simple heuristic based on confidence and complexity
        confidence = result.get("confidence", 0.5)
        complexity = result.get("complexity", 0.5)
        
        return confidence > 0.6 and complexity < 0.8

    def _estimate_cognitive_load(self, result: Dict[str, Any]) -> float:
        """Estimate current cognitive load."""
        # Based on task complexity and number of concurrent operations
        complexity = result.get("complexity", 0.5)
        concurrent_ops = result.get("concurrent_operations", 1)
        
        load = min((complexity * 0.6) + (concurrent_ops * 0.1), 1.0)
        return load

    def _estimate_focus_level(self, result: Dict[str, Any]) -> float:
        """Estimate current focus level."""
        # Inverse of cognitive load
        load = self._estimate_cognitive_load(result)
        return max(1.0 - load, 0.0)

    async def _introspect(self) -> Dict[str, Any]:
        """Perform introspection on current state."""
        introspection = {
            "timestamp": datetime.utcnow().isoformat(),
            "mental_state": self.mental_state.__dict__,
            "self_capabilities": len(self.self_model.capabilities),
            "avg_performance": sum(self.self_model.performance_history) / len(self.self_model.performance_history) if self.self_model.performance_history else 0.0
        }
        
        self.introspection_history.append(introspection)
        return introspection

    async def _deep_introspection(self) -> Dict[str, Any]:
        """Deep introspection with pattern recognition."""
        recent_introspections = self.introspection_history[-10:] if len(self.introspection_history) >= 10 else self.introspection_history
        
        # Identify patterns
        patterns = {
            "performance_trend": self._analyze_performance_trend(),
            "cognitive_load_pattern": self._analyze_cognitive_load_pattern(),
            "confidence_stability": self._analyze_confidence_stability()
        }
        
        return {
            "deep_introspection": True,
            "patterns": patterns,
            "introspection_count": len(self.introspection_history)
        }

    def _analyze_performance_trend(self) -> str:
        """Analyze performance trend."""
        if len(self.self_model.performance_history) < 5:
            return "insufficient_data"
        
        recent = self.self_model.performance_history[-5:]
        if recent[-1] > recent[0]:
            return "improving"
        elif recent[-1] < recent[0]:
            return "declining"
        else:
            return "stable"

    def _analyze_cognitive_load_pattern(self) -> str:
        """Analyze cognitive load pattern."""
        recent_loads = [i.get("mental_state", {}).get("cognitive_load", 0.5) for i in self.introspection_history[-10:]]
        
        if not recent_loads:
            return "insufficient_data"
        
        avg_load = sum(recent_loads) / len(recent_loads)
        
        if avg_load > 0.7:
            return "consistently_high"
        elif avg_load < 0.3:
            return "consistently_low"
        else:
            return "moderate"

    def _analyze_confidence_stability(self) -> str:
        """Analyze confidence stability."""
        recent_confidences = [i.get("mental_state", {}).get("confidence", 0.5) for i in self.introspection_history[-10:]]
        
        if len(recent_confidences) < 3:
            return "insufficient_data"
        
        variance = sum((c - sum(recent_confidences)/len(recent_confidences))**2 for c in recent_confidences) / len(recent_confidences)
        
        if variance < 0.05:
            return "very_stable"
        elif variance < 0.15:
            return "stable"
        else:
            return "unstable"

    async def _apply_theory_of_mind(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply theory of mind to understand other agents."""
        # If swarm was used, model other agents
        swarm_size = result.get("swarm_size", 0)
        
        if swarm_size > 1:
            # Deterministic capability estimates derived from result metadata
            confidence = max(0.5, min(1.0, result.get("confidence", 0.7)))
            swarm_factor = max(0.5, min(1.0, result.get("swarm_size", 1) / 10.0))
            cooperation = max(0.5, min(1.0, (confidence + swarm_factor) / 2.0))
            
            # Model each swarm agent
            for i in range(swarm_size):
                agent_id = f"swarm_agent_{i}"
                self.theory_of_mind.agent_models[agent_id] = {
                    "estimated_capability": confidence,
                    "estimated_focus": swarm_factor,
                    "cooperation_level": cooperation
                }
        
        return {
            "modeled_agents": len(self.theory_of_mind.agent_models),
            "agent_models": self.theory_of_mind.agent_models
        }
