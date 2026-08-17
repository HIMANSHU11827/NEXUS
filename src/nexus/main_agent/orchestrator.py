"""V5 Loop Orchestrator - Integration layer for NEXUS V5 loop.

This module provides the orchestrator that integrates V5 with existing NEXUS infrastructure
and provides backward compatibility with V1/V2 loops.
"""

import asyncio
import inspect
import json
import logging
import uuid
from typing import Any, Dict, Optional
from pathlib import Path

from .core import NexusLoopV5, V5Runtime, V5TurnContext, V5LoopState
from nexus.runtime import safe_session_id

logger = logging.getLogger(__name__)


class V5Orchestrator:
    """Orchestrator for V5 loop integration with NEXUS infrastructure."""

    def __init__(self, root_dir: str, session_id: str = "default"):
        self.root_dir = root_dir
        self.session_id = safe_session_id(session_id)
        self.v5_loop = NexusLoopV5(root_dir, self.session_id)
        self.logger = logging.getLogger("nexus.v5.orchestrator")
        
        # Integration with existing NEXUS kernel
        self.kernel = None
        self._init_kernel()

    def _init_kernel(self):
        """Initialize NEXUS kernel for integration."""
        try:
            from nexus.runtime.kernel import get_nexus_kernel
            self.kernel = get_nexus_kernel(root_dir=self.root_dir)
            self.logger.info("V5 orchestrator connected to NEXUS kernel")
        except Exception as e:
            self.logger.warning(f"Could not connect to kernel: {e}")

    async def run(self, user_input: str, input_type: str = "text") -> Dict[str, Any]:
        """Run V5 loop with NEXUS infrastructure integration.
        
        Args:
            user_input: User's input
            input_type: Type of input (text, voice, vision, code)
        
        Returns:
            Dict with execution results
        """
        self.logger.info(f"V5 orchestrator running with input type: {input_type}")
        
        # Run V5 loop
        result = await self.v5_loop.run(user_input, input_type)
        
        # Integrate with NEXUS subsystems if kernel available
        if self.kernel:
            result = await self._integrate_with_subsystems(result)
        
        return result

    async def _integrate_with_subsystems(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Integrate V5 results with NEXUS subsystems.

        Each integration method guards its own dependency and degrades
        gracefully with a warning when the subsystem is unavailable.
        """
        # Integrate with memory
        await self._save_to_memory(result)
        
        # Integrate with event system
        await self._emit_events(result)
        
        # Integrate with evolution
        await self._log_evolution(result)
        
        return result

    async def _save_to_memory(self, result: Dict[str, Any]):
        """Save V5 execution to memory."""
        memory_manager = getattr(self.v5_loop, "_memory_manager", None)
        if memory_manager is None:
            self.logger.debug("No memory manager available, skipping memory save")
            return
        try:
            memory_entry = {
                "type": "v5_execution",
                "success": result.get("success", False),
                "confidence": result.get("output", {}).get("confidence", 0.0),
                "output_type": result.get("output_type", "text"),
                "timestamp": result.get("timestamp", "")
            }
            await asyncio.to_thread(
                memory_manager.set,
                "v5_last_execution",
                json.dumps(memory_entry, default=str)
            )
            self.logger.debug("Saved V5 execution to memory")
        except Exception as e:
            self.logger.warning(f"Failed to save to memory: {e}")

    async def _emit_events(self, result: Dict[str, Any]):
        """Emit canonical V5 run.completed event through the work event sink."""
        sink = getattr(self.v5_loop.runtime, "work_event_sink", None)
        if sink is None:
            self.logger.debug("No work event sink bound, skipping event emission")
            return
        try:
            current_turn = getattr(self.v5_loop.runtime, "current_turn", None)
            turn_id = getattr(current_turn, "turn_id", None) if current_turn else None
            run_id = f"v5_{self.session_id}_{uuid.uuid4().hex[:8]}"
            
            event = {
                "id": turn_id or run_id,
                "event_type": "run.completed",
                "run_id": run_id,
                "turn_id": turn_id or "",
                "kind": "run",
                "title": "V5 run completed",
                "action": "completed",
                "status": "completed",
                "parent_id": self.session_id,
                "payload": {
                    "success": result.get("success", False),
                    "output_type": result.get("output_type", "text"),
                    "session_id": self.session_id
                },
                "visibility": "public"
            }
            
            if inspect.iscoroutinefunction(sink):
                await sink(event)
            else:
                emitted = sink(event)
                if inspect.isawaitable(emitted):
                    await emitted
            
            self.logger.debug("Emitted V5 run.completed event")
        except Exception as e:
            self.logger.warning(f"Failed to emit events: {e}")

    async def _log_evolution(self, result: Dict[str, Any]):
        """Log V5 execution to evolution log."""
        evolution_log = getattr(self.kernel, "evolution_log", None)
        if evolution_log is None:
            self.logger.debug("No evolution log available, skipping evolution logging")
            return
        try:
            evolution_entry = {
                "type": "v5_execution",
                "result": result,
                "learnings": self._extract_learnings(result)
            }
            
            log_entry = getattr(evolution_log, "log_entry", None)
            if callable(log_entry):
                await asyncio.to_thread(log_entry, evolution_entry)
            else:
                improvement = getattr(evolution_log, "improvement", None)
                if callable(improvement):
                    await asyncio.to_thread(
                        improvement,
                        "v5_execution",
                        metadata=evolution_entry
                    )
                else:
                    self.logger.warning(
                        "Evolution log has neither log_entry nor improvement API; skipping"
                    )
                    return
            
            self.logger.debug("Logged V5 execution to evolution")
        except Exception as e:
            self.logger.warning(f"Failed to log evolution: {e}")

    def _extract_learnings(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract learnings from V5 execution."""
        learnings = {}
        
        # Extract consciousness learnings
        if "mental_state" in result:
            learnings["confidence"] = result["mental_state"].get("confidence", 0.0)
            learnings["cognitive_load"] = result["mental_state"].get("cognitive_load", 0.0)
        
        # Extract swarm learnings
        if "swarm_result" in result:
            learnings["swarm_effectiveness"] = result["swarm_result"].get("average_confidence", 0.0)
        
        # Extract quantum learnings
        if "quantum_results" in result:
            learnings["quantum_effectiveness"] = result["quantum_results"].get("confidence", 0.0)
        
        return learnings

    def configure_v5(self, config: Dict[str, Any]):
        """Configure V5 loop parameters.
        
        Args:
            config: Configuration dict with keys:
                - meta_learning_enabled (bool)
                - quantum_mode (bool)
                - consciousness_level (int)
                - swarm_size (int)
                - evolution_enabled (bool)
        """
        if "meta_learning_enabled" in config:
            self.v5_loop.runtime.meta_learning_enabled = config["meta_learning_enabled"]
        
        if "quantum_mode" in config:
            self.v5_loop.runtime.quantum_mode = config["quantum_mode"]
        
        if "consciousness_level" in config:
            self.v5_loop.runtime.consciousness_level = config["consciousness_level"]
        
        if "swarm_size" in config:
            self.v5_loop.runtime.swarm_size = config["swarm_size"]
        
        if "evolution_enabled" in config:
            self.v5_loop.runtime.evolution_enabled = config["evolution_enabled"]
        
        self.logger.info(f"V5 configured: {config}")

    def get_runtime_state(self) -> Dict[str, Any]:
        """Get current runtime state."""
        return {
            "session_id": self.v5_loop.runtime.session_id,
            "turn_count": len(self.v5_loop.runtime.turn_history),
            "meta_learning_enabled": self.v5_loop.runtime.meta_learning_enabled,
            "quantum_mode": self.v5_loop.runtime.quantum_mode,
            "consciousness_level": self.v5_loop.runtime.consciousness_level,
            "swarm_size": self.v5_loop.runtime.swarm_size,
            "evolution_enabled": self.v5_loop.runtime.evolution_enabled,
            "current_state": self.v5_loop.runtime.current_turn.state.value if self.v5_loop.runtime.current_turn else None
        }

    async def reset(self):
        """Reset V5 loop state."""
        self.v5_loop.runtime.turn_history = []
        self.v5_loop.runtime.current_turn = None
        self.logger.info("V5 loop reset")


def create_v5_loop(root_dir: str, session_id: str = "default", config: Optional[Dict[str, Any]] = None) -> V5Orchestrator:
    """Factory function to create V5 loop orchestrator.
    
    Args:
        root_dir: Root directory for NEXUS
        session_id: Session identifier
        config: Optional configuration dict
    
    Returns:
        V5Orchestrator instance
    """
    orchestrator = V5Orchestrator(root_dir, session_id)
    
    if config:
        orchestrator.configure_v5(config)
    
    return orchestrator
